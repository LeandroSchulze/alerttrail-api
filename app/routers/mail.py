# app/routers/mail.py
from __future__ import annotations

import os
import json
import ssl
import imaplib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

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
    """
    Evita KeyError si el JWT trae 'id' o 'email' en vez de 'sub'.
    """
    if not user:
        return "anon"
    for k in ("sub", "id", "user_id", "email"):
        v = user.get(k)
        if v:
            return str(v)
    return "unknown"


def _load_linked() -> Dict[str, Any]:
    return _load_json(LINKED_FILE, {}) or {}


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


# -----------------------------
# IMAP scanning (simple MVP)
# -----------------------------
def _imap_count(server: str, port: int, use_ssl: bool, username: str, password: str, folder: str) -> int:
    folder = folder or "INBOX"
    if use_ssl:
        imap = imaplib.IMAP4_SSL(server, port, ssl_context=ssl.create_default_context())
    else:
        imap = imaplib.IMAP4(server, port)

    try:
        imap.login(username, password)
        imap.select(folder, readonly=True)
        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return 0
        ids = data[0].split()
        return len(ids)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _imap_sample_headers(
    server: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Trae una muestra pequeña (últimos N) con headers básicos.
    Esto no es análisis de phishing todavía; sirve para que el usuario vea "resultados".
    """
    folder = folder or "INBOX"
    if use_ssl:
        imap = imaplib.IMAP4_SSL(server, port, ssl_context=ssl.create_default_context())
    else:
        imap = imaplib.IMAP4(server, port)

    try:
        imap.login(username, password)
        imap.select(folder, readonly=True)
        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []

        ids = data[0].split()
        # últimos N
        ids = ids[-limit:] if len(ids) > limit else ids

        out: List[Dict[str, Any]] = []
        for mid in reversed(ids):  # más recientes primero
            typ2, msg_data = imap.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ2 != "OK" or not msg_data:
                continue
            raw = msg_data[0][1].decode(errors="ignore") if msg_data[0] and len(msg_data[0]) > 1 else ""
            # parseo simple
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

            out.append({"from": frm, "subject": subj, "date": dt})
        return out
    finally:
        try:
            imap.logout()
        except Exception:
            pass


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

    # cargar último scan guardado
    last_scan = _load_json(_scan_file_for(user), None)

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
            "last_scan": last_scan,  # para que el template muestre resultados
        },
    )


@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    # compat con links viejos
    return RedirectResponse(url="/mail", status_code=302)


@router.post("/settings", include_in_schema=False)
def mail_settings_save(
    request: Request,
    user=Depends(get_user),

    # Aceptamos ambos nombres: email/address, server/imap_server, username/imap_user...
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

    # normalizar inputs
    addr = (email or address or "").strip()
    srv = (server or imap_server or "").strip()
    prt = port or imap_port or 993
    usr = (username or imap_user or "").strip()
    pwd = (password or imap_password or "").strip()
    fld = (folder or imap_folder or "INBOX").strip() or "INBOX"

    def _truthy(v: Optional[str]) -> bool:
        if v is None:
            return False
        return str(v).lower() in ("1", "true", "yes", "on", "checked")

    ssl_on = _truthy(use_ssl) or _truthy(imap_ssl)
    mark_on = _truthy(mark_read) or _truthy(imap_mark_read)

    # Si el form no manda server/email, damos un error legible en /mail/settings
    missing = {
        "email": not bool(addr),
        "server": not bool(srv),
        "username": not bool(usr),
        "password": not bool(pwd),
    }
    if any(missing.values()):
        # devolvemos una respuesta simple para debug rápido
        # (lo ideal después: volver a /mail con flash message)
        return {
            "ok": False,
            "error": "Faltan campos requeridos",
            "missing": missing,
            "hint": 'Revisá que el <form> tenga name=email (o address), server, username, password (o aliases imap_*)',
        }

    # guardamos por usuario
    all_linked = _load_linked()
    all_linked[_user_id(user)] = {
        "address": addr,
        "server": srv,
        "port": int(prt),
        "username": usr,
        "password": pwd,  # (si ya tenés cifrado en otra parte, reemplazar acá)
        "folder": fld,
        "use_ssl": bool(ssl_on),
        "mark_read": bool(mark_on),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _save_linked(all_linked)

    return RedirectResponse(url="/mail", status_code=303)


@router.get("/scan", response_class=HTMLResponse)
def mail_scan(request: Request, user=Depends(get_user)):
    """
    Endpoint que ejecuta un scan rápido y muestra un resultado simple.
    Además guarda un resumen en /var/data/mail/scan_last_<user>.json
    para que /mail/scanner pueda mostrarlo.
    """
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)

    linked = _load_linked().get(_user_id(user))
    if not linked:
        return templates.TemplateResponse(
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "ok": False,
                "error": "No hay cuenta IMAP vinculada. Configurá primero en /mail.",
            },
            status_code=400,
        )

    server = linked.get("server") or "imap.gmail.com"
    port = int(linked.get("port") or 993)
    folder = linked.get("folder") or "INBOX"
    use_ssl = bool(linked.get("use_ssl", True))
    username = linked.get("username") or linked.get("address") or ""
    password = linked.get("password") or ""

    result: Dict[str, Any] = {
        "ok": False,
        "scanned_at": datetime.utcnow().isoformat() + "Z",
        "server": server,
        "folder": folder,
        "total": 0,
        "items": [],
        "error": None,
    }

    try:
        total = _imap_count(server, port, use_ssl, username, password, folder)
        items = _imap_sample_headers(server, port, use_ssl, username, password, folder, limit=25)

        result["ok"] = True
        result["total"] = total
        result["items"] = items

        # guardar para que /mail/scanner muestre resultados
        _save_json(_scan_file_for(user), result)

        return templates.TemplateResponse(
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "ok": True,
                "result": result,
            },
        )
    except Exception as e:
        result["error"] = str(e)
        _save_json(_scan_file_for(user), result)

        return templates.TemplateResponse(
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "ok": False,
                "error": str(e),
                "result": result,
            },
            status_code=500,
        )
