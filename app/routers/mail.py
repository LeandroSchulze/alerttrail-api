# app/routers/mail.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.i18n import get_lang, t
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.services.mail_scan import scan_mailbox

router = APIRouter(prefix="/mail", tags=["mail"])
logger = logging.getLogger("alerttrail.mail")

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _load_linked_all() -> Dict[str, Any]:
    data = _load_json(LINKED_FILE, {}) or {}
    return data if isinstance(data, dict) else {}


def _load_linked_one(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _load_linked_all().get(_user_id(user))


def _save_linked_one(user: Dict[str, Any], payload: Dict[str, Any]) -> None:
    all_linked = _load_linked_all()
    all_linked[_user_id(user)] = payload
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
    return get_current_user_cookie_optional(request)


def _verdict_from_level(level: str) -> str:
    lvl = (level or "low").lower()
    if lvl == "high":
        return "ALTO"
    if lvl == "medium":
        return "MEDIO"
    return "BAJO"


@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked_one(user)

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
    linked = _load_linked_one(user)

    last_scan_raw = _load_json(_scan_file_for(user), {}) or {}
    scan_items = last_scan_raw.get("items", [])
    if not isinstance(scan_items, list):
        scan_items = []

    last_scan = {
        "ts": last_scan_raw.get("scanned_at") or last_scan_raw.get("ts") or "",
        "folder": last_scan_raw.get("folder") or "",
        "found": last_scan_raw.get("total") if isinstance(last_scan_raw.get("total"), int) else last_scan_raw.get("found", 0),
        "limit": last_scan_raw.get("limit", 0),
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


@router.post("/settings")
def save_mail_settings(
    request: Request,
    user=Depends(get_user),
    address: str = Form(""),
    host: str = Form("imap.gmail.com"),
    port: str = Form("993"),
    username: str = Form(...),
    password: str = Form(...),
    folder: str = Form("INBOX"),
    use_ssl: Optional[str] = Form(None),
    mark_read: Optional[str] = Form(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    try:
        port_i = int(port)
    except Exception:
        port_i = 993

    payload = {
        "address": (address or username or "").strip(),
        "host": (host or "imap.gmail.com").strip(),
        "port": int(port_i),
        "username": (username or "").strip(),
        "password": (password or "").strip(),
        "folder": (folder or "INBOX").strip() or "INBOX",
        "use_ssl": bool(_truthy(use_ssl) if use_ssl is not None else True),
        "mark_read": bool(_truthy(mark_read) if mark_read is not None else False),
        "updated_at": _now_iso(),
    }
    _save_linked_one(user, payload)
    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)


@router.get("/scan")
def scan_get(
    request: Request,
    user=Depends(get_user),
    limit: int = Query(20, ge=1, le=500),
):
    """Botones del template (/mail/scan?limit=20). Corre scan y vuelve al scanner."""
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    linked = _load_linked_one(user)
    if not linked:
        # no hay casilla guardada
        _save_json(_scan_file_for(user), {"ok": False, "scanned_at": _now_iso(), "error": "No hay casilla guardada", "items": [], "limit": limit})
        return RedirectResponse(url="/mail/scanner?err=no_linked", status_code=303)

    res = scan_mailbox(
        host=linked.get("host") or "imap.gmail.com",
        port=int(linked.get("port") or 993),
        username=linked.get("username") or "",
        password=linked.get("password") or "",
        folder=linked.get("folder") or "INBOX",
        use_ssl=bool(linked.get("use_ssl", True)),
        limit=int(limit),
        mark_read=bool(linked.get("mark_read", False)),
    )

    # Guardar en el formato que la UI ya lee (mail_scanner.html)
    items = []
    for it in (res.items or []):
        analysis = getattr(it, "analysis", None)
        danger_level = str(getattr(analysis, "danger_level", "") or "low").lower()
        reasons = list(getattr(analysis, "reasons", []) or [])
        items.append(
            {
                "uid": str(it.uid or ""),
                "subject": str(it.subject or ""),
                "from": str(it.from_email or ""),
                "date": str(it.date or ""),
                "verdict": _verdict_from_level(danger_level),
                "reasons": reasons,
            }
        )

    payload = {
        "ok": bool(res.ok),
        "scanned_at": _now_iso(),
        "folder": linked.get("folder") or "INBOX",
        "address": linked.get("address") or linked.get("username") or "",
        "total": int(res.total_found or 0),
        "unread": int(res.unread or 0),
        "items": items,
        "error": (res.message or "") if not res.ok else None,
        "limit": int(limit),
    }
    _save_json(_scan_file_for(user), payload)

    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)


@router.post("/scan", response_class=JSONResponse)
def scan_post(request: Request, user=Depends(get_user), limit: int = Query(50, ge=1, le=500)):
    """Endpoint usado por /static/mail_scanner.js (POST /mail/scan). Devuelve JSON."""
    if not user:
        return JSONResponse({"ok": False, "message": "not authenticated"}, status_code=401)

    linked = _load_linked_one(user)
    if not linked:
        return JSONResponse({"ok": False, "message": "no linked mailbox"}, status_code=400)

    res = scan_mailbox(
        host=linked.get("host") or "imap.gmail.com",
        port=int(linked.get("port") or 993),
        username=linked.get("username") or "",
        password=linked.get("password") or "",
        folder=linked.get("folder") or "INBOX",
        use_ssl=bool(linked.get("use_ssl", True)),
        limit=int(limit),
        mark_read=bool(linked.get("mark_read", False)),
    )

    items = []
    for it in (res.items or []):
        analysis = getattr(it, "analysis", None)
        items.append(
            {
                "uid": str(it.uid or ""),
                "subject": str(it.subject or ""),
                "from": str(it.from_email or ""),
                "date": str(it.date or ""),
                "attachments": list(it.attachments or []),
                "analysis": {
                    "danger_level": str(getattr(analysis, "danger_level", "") or "low").lower(),
                    "reasons": list(getattr(analysis, "reasons", []) or []),
                    "iocs": dict(getattr(analysis, "iocs", {}) or {}),
                    "hints": dict(getattr(analysis, "hints", {}) or {}),
                    "score": getattr(analysis, "score", None),
                },
            }
        )

    return {
        "ok": bool(res.ok),
        "message": res.message,
        "folder": linked.get("folder") or "INBOX",
        "total": int(res.total_found or 0),
        "unread": int(res.unread or 0),
        "items": items,
    }
