# app/routers/mail.py
from __future__ import annotations

import os
import json
import ssl
import imaplib
import logging
import traceback
import socket
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

logger = logging.getLogger("alerttrail.mail")

# Persistencia (Render disk)
MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


# -----------------------------
# Helpers storage
# -----------------------------
def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_id(user: Dict[str, Any]) -> str:
    if not user:
        return "anon"
    for k in ("sub", "id", "user_id", "email"):
        v = user.get(k)
        if v:
            return str(v)
    return "unknown"


def _load_linked() -> Dict[str, Any]:
    data = _load_json(LINKED_FILE, {}) or {}
    return data if isinstance(data, dict) else {}


def _save_linked(all_linked: Dict[str, Any]) -> None:
    _save_json(LINKED_FILE, all_linked)


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", "imap.gmail.com"),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1").lower() in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0").lower() in ("1", "true", "yes", "on"),
    }


def _compute_plan(user: Dict[str, Any]) -> str:
    role = (user or {}).get("role") or ""
    if str(role).lower() == "admin":
        try:
            user["plan"] = "PRO"
        except Exception:
            pass
        return "PRO"
    return (user or {}).get("plan") or "FREE"


def get_user(request: Request):
    return get_current_user_cookie(request)


def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"


def _truthy(v: Optional[str]) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on", "checked")


# -----------------------------
# IMAP helpers
# -----------------------------
def _imap_client(server: str, port: int, use_ssl: bool):
    # evita cuelgues eternos
    timeout_s = int(os.getenv("IMAP_TIMEOUT", "25"))
    socket.setdefaulttimeout(timeout_s)

    if use_ssl:
        ctx = ssl.create_default_context()
        return imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
    return imaplib.IMAP4(server, port)


def _decode_header_value(v: str) -> str:
    """
    Decodifica headers tipo =?UTF-8?Q?...?= (muchos newsletters vienen así).
    No importamos `email` para mantenerlo simple y rápido.
    """
    try:
        # import local para no cargar si no hace falta
        from email.header import decode_header

        parts = decode_header(v or "")
        out = ""
        for txt, enc in parts:
            if isinstance(txt, bytes):
                out += txt.decode(enc or "utf-8", errors="replace")
            else:
                out += str(txt)
        return out.strip()
    except Exception:
        return (v or "").strip()


def _imap_scan(
    server: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    limit: int,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Scan en UNA sola sesión IMAP:
    - search ALL
    - total = len(ids)
    - fetch headers de últimos N
    """
    folder = (folder or "INBOX").strip() or "INBOX"
    limit = max(1, min(int(limit), 200))

    imap = _imap_client(server, port, use_ssl)
    try:
        imap.login(username, password)

        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"No pude abrir carpeta IMAP: {folder}")

        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return 0, []

        ids = data[0].split()
        total = len(ids)

        pick = ids[-limit:] if total > limit else ids

        items: List[Dict[str, Any]] = []
        for mid in reversed(pick):  # más recientes primero
            typ2, msg_data = imap.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ2 != "OK" or not msg_data:
                continue

            raw = ""
            try:
                if msg_data[0] and len(msg_data[0]) > 1 and msg_data[0][1]:
                    raw = msg_data[0][1].decode(errors="ignore")
            except Exception:
                raw = ""

            frm = ""
            subj = ""
            dt = ""

            for line in raw.splitlines():
                low = line.lower()
                if low.startswith("from:"):
                    frm = line[5:].strip()
                elif low.startswith("subject:"):
                    subj = line[8:].strip()
                elif low.startswith("date:"):
                    dt = line[5:].strip()

            frm = _decode_header_value(frm)
            subj = _decode_header_value(subj)
            dt = _decode_header_value(dt)

            verdict = "OK"
            subj_l = subj.lower()
            if any(k in subj_l for k in ("verify", "verification", "password", "cuenta", "contraseña", "paypal", "urgente")):
                verdict = "REVISAR"

            items.append(
                {
                    "from": frm,
                    "subject": subj,
                    "date": dt,
                    "sender": frm or "—",
                    "verdict": verdict,
                }
            )

        return total, items

    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _render_safe(request: Request, template_name: str, context: Dict[str, Any], status_code: int = 200):
    """
    Si el template no existe (TemplateNotFound) o revienta, devolvemos HTML “de emergencia”
    en vez de dejar 500 genérico.
    """
    try:
        return templates.TemplateResponse(template_name, context, status_code=status_code)
    except Exception as e:
        logger.error("Template error (%s): %s", template_name, e)
        logger.error(traceback.format_exc())
        # fallback mínimo
        summary = context.get("summary") or context.get("error") or "Error"
        return HTMLResponse(
            f"<h1>Mail Scan</h1><p>{summary}</p><p><a href='/mail/scanner'>Volver</a></p>",
            status_code=status_code,
        )


# -----------------------------
# Routes
# -----------------------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(_user_id(user))

    return templates.TemplateResponse(
        "mail.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "plan": plan,
            "defaults": _defaults_from_env(),
            "linked": linked,
        },
    )


@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(_user_id(user))

    last_scan = _load_json(_scan_file_for(user), None)
    if not isinstance(last_scan, dict):
        last_scan = {}

    scan_items = last_scan.get("items", [])
    if not isinstance(scan_items, list):
        scan_items = []

    return templates.TemplateResponse(
        "mail_scanner.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "plan": plan,
            "defaults": _defaults_from_env(),
            "linked": linked,
            "last_scan": last_scan,
            "scan_items": scan_items,
        },
    )


@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    return RedirectResponse(url="/mail", status_code=302)


@router.post("/settings", include_in_schema=False)
def mail_settings_save(
    request: Request,
    user=Depends(get_user),

    email: Optional[str] = Form(None),
    address: Optional[str] = Form(None),

    server: Optional[str] = Form(None),
    imap_server: Optional[str] = Form(None),

    port: Optional[int] = Form(None),
    imap_port: Optional[int] = Form(None),

    username: Optional[str] = Form(None),
    imap_user: Optional[str] = Form(None),

    password: Optional[str] = Form(None),
    imap_password: Optional[str] = Form(None),

    folder: Optional[str] = Form(None),
    imap_folder: Optional[str] = Form(None),

    use_ssl: Optional[str] = Form(None),
    imap_ssl: Optional[str] = Form(None),

    mark_read: Optional[str] = Form(None),
    imap_mark_read: Optional[str] = Form(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    addr = (email or address or "").strip()
    srv = (server or imap_server or "").strip()
    prt = port or imap_port or 993
    usr = (username or imap_user or "").strip()
    pwd = (password or imap_password or "").strip()
    fld = (folder or imap_folder or "INBOX").strip() or "INBOX"

    ssl_on = _truthy(use_ssl) or _truthy(imap_ssl)
    mark_on = _truthy(mark_read) or _truthy(imap_mark_read)

    missing = {
        "email": not bool(addr),
        "server": not bool(srv),
        "username": not bool(usr),
        "password": not bool(pwd),
    }
    if any(missing.values()):
        return {
            "ok": False,
            "error": "Faltan campos requeridos",
            "missing": missing,
            "hint": 'Revisá que el <form> tenga name=email (o address), server, username, password (o aliases imap_*)',
        }

    all_linked = _load_linked()
    all_linked[_user_id(user)] = {
        "address": addr,
        "server": srv,
        "port": int(prt),
        "username": usr,
        "password": pwd,
        "folder": fld,
        "use_ssl": bool(ssl_on),
        "mark_read": bool(mark_on),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _save_linked(all_linked)

    return RedirectResponse(url="/mail", status_code=303)


@router.get("/scan", response_class=HTMLResponse)
def mail_scan(
    request: Request,
    user=Depends(get_user),
    limit: int = Query(25, ge=1, le=200),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)

    linked = _load_linked().get(_user_id(user))
    if not linked:
        return _render_safe(
            request,
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "summary": "No hay cuenta IMAP vinculada. Configurá primero en /mail.",
                "items": [],
            },
            status_code=400,
        )

    server = linked.get("server") or "imap.gmail.com"
    port = int(linked.get("port") or 993)
    folder = linked.get("folder") or "INBOX"
    use_ssl = bool(linked.get("use_ssl", True))
    username = linked.get("username") or linked.get("address") or ""
    password = linked.get("password") or ""

    logger.info("MAIL_SCAN user=%s server=%s folder=%s limit=%s ssl=%s", _user_id(user), server, folder, limit, use_ssl)

    result: Dict[str, Any] = {
        "ok": False,
        "scanned_at": datetime.utcnow().isoformat() + "Z",
        "server": server,
        "folder": folder,
        "total": 0,
        "items": [],
        "error": None,
        "limit": int(limit),
    }

    try:
        total, items = _imap_scan(server, port, use_ssl, username, password, folder, int(limit))

        result["ok"] = True
        result["total"] = total
        result["items"] = items

        _save_json(_scan_file_for(user), result)

        summary = f"Scan IMAP OK ✅ | Servidor: {server} | Carpeta: {folder} | Correos: {total} | Mostrando: {len(items)}"

        return _render_safe(
            request,
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "summary": summary,
                "items": items,
                "result": result,
            },
            status_code=200,
        )

    except Exception as e:
        result["error"] = str(e)
        _save_json(_scan_file_for(user), result)

        logger.error("MAIL_SCAN ERROR user=%s err=%s", _user_id(user), str(e))
        logger.error(traceback.format_exc())

        return _render_safe(
            request,
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "summary": f"Error de IMAP: {str(e)}",
                "items": [],
                "result": result,
            },
            status_code=500,
        )
