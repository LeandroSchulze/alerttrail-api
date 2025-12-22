# app/routers/mail.py
from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.i18n import get_lang, t
from app.security import get_current_user_cookie
from app.ui import templates

from app.services.mail_scan import scan_mailbox  # motor real

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


def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"


def _load_linked() -> Dict[str, Any]:
    data = _load_json(LINKED_FILE, {}) or {}
    return data if isinstance(data, dict) else {}


def _save_linked(all_linked: Dict[str, Any]) -> None:
    _save_json(LINKED_FILE, all_linked)


def _truthy(v: Optional[str]) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on", "checked")


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
    """
    ✅ Importante: NO tirar 401 desde Depends, para que podamos redirigir a /auth/login.
    """
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None


def _render_safe(template_name: str, context: Dict[str, Any], status_code: int = 200):
    """
    Render con fallback si el template no existe o falla.
    """
    try:
        return templates.TemplateResponse(template_name, context, status_code=status_code)
    except Exception as e:
        logger.error("Template error (%s): %s", template_name, e)
        logger.error(traceback.format_exc())
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

    last_scan_raw = _load_json(_scan_file_for(user), None)
    if not isinstance(last_scan_raw, dict):
        last_scan_raw = {}

    scan_items = last_scan_raw.get("items", [])
    if not isinstance(scan_items, list):
        scan_items = []

    # View-model para evitar last_scan.items (método dict) en Jinja
    last_scan = {
        "ts": last_scan_raw.get("scanned_at") or last_scan_raw.get("ts") or "",
        "folder": last_scan_raw.get("folder") or "",
        "found": int(last_scan_raw.get("total") or 0),
        "limit": int(last_scan_raw.get("limit") or 0),
        "error": last_scan_raw.get("error"),
    }

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
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "summary": "No hay cuenta IMAP vinculada.",
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
        scan_res = scan_mailbox(
            host=server,
            port=port,
            username=username,
            password=password,
            folder=folder,
            use_ssl=use_ssl,
            limit=int(limit),
            mark_read=False,
        )

        items = []
        for it in scan_res.items:
            level_raw = (getattr(it.analysis, "danger_level", "") or "low").lower()
            reasons = getattr(it.analysis, "reasons", []) or []

            if level_raw in ("high", "alto"):
                verdict = "ALTO"
                badge = {"bg": "#fee2e2", "fg": "#991b1b", "bd": "#fecaca"}
            elif level_raw in ("medium", "medio"):
                verdict = "MEDIO"
                badge = {"bg": "#ffedd5", "fg": "#9a3412", "bd": "#fed7aa"}
            else:
                verdict = "BAJO"
                badge = {"bg": "#dcfce7", "fg": "#166534", "bd": "#bbf7d0"}

            # ✅ Guardamos también analysis completo para /alerts/pending
            analysis_dict = {
                "risk_score": int(getattr(it.analysis, "risk_score", 0) or 0),
                "danger_level": level_raw,
                "reasons": reasons,
                "iocs": dict(getattr(it.analysis, "iocs", {}) or {}),
                "hints": dict(getattr(it.analysis, "hints", {}) or {}),
            }

            items.append({
                "uid": str(it.uid or ""),
                "from": it.from_email or "—",
                "subject": it.subject or "—",
                "date": it.date or "",
                "verdict": verdict,
                "badge": badge,
                "reasons": reasons,
                "analysis": analysis_dict,
            })

        result["ok"] = True
        result["total"] = int(scan_res.total_found or 0)
        result["items"] = items

        _save_json(_scan_file_for(user), result)

        summary = f"Scan IMAP OK ✅ | Server: {server} | Folder: {folder} | Found: {result['total']} | Showing: {len(items)}"

        return _render_safe(
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
            "mail_scan_result.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "summary": f"Scan failed: {str(e)}",
                "items": [],
                "result": result,
            },
            status_code=500,
        )
