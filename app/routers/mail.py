# app/routers/mail.py
import os, json
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


def _load_linked() -> Dict[str, Any]:
    if not LINKED_FILE.exists():
        return {}
    try:
        return json.loads(LINKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", ""),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1") in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0") in ("1", "true", "yes", "on"),
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


@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(str(user["sub"]))
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
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(str(user["sub"]))
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
        },
    )


@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    return RedirectResponse(url="/mail", status_code=302)
