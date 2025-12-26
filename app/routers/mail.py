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
from app.security import get_current_user_cookie_optional
from app.ui import templates

from app.services.mail_scan import scan_mailbox  # ✅ motor real de riesgo

router = APIRouter(prefix="/mail", tags=["mail"])
logger = logging.getLogger("alerttrail.mail")

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


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
    return get_current_user_cookie_optional(request)


def _render_safe(template_name: str, context: Dict[str, Any], status_code: int = 200):
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

# (el resto del archivo queda igual que en tu ZIP)
# IMPORTANTE: no toqué el resto porque es largo; si querés que te lo pegue entero,
# decime y lo vuelco completo. Para arreglar el 401 en UI alcanza con el cambio de arriba.
