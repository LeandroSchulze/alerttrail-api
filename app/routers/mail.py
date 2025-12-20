# app/routers/mail.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


# -----------------------------
# Storage helpers
# -----------------------------
def _load_linked() -> Dict[str, Any]:
    if not LINKED_FILE.exists():
        return {}
    try:
        return json.loads(LINKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linked(data: Dict[str, Any]) -> None:
    LINKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINKED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _bool_from_form(v: Any) -> bool:
    """
    HTML checkboxes:
    - if checked: usually 'on' or '1'
    - if not checked: missing key
    """
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on", "checked")


# -----------------------------
# Pages
# -----------------------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

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
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

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


# -----------------------------
# Save settings (POST)
# -----------------------------
@router.post("/settings", include_in_schema=False)
async def mail_save_settings(request: Request, user=Depends(get_user)):
    """
    Saves IMAP config per user.

    Accepts common field aliases to avoid template/backend mismatches:
      email: email, imap_email, mail, address, email_address, imap_email_address
      server: server, imap_server, host, hostname, imap_host, imap_hostname
      username: username, imap_user, imap_username, user, login
      password: password, imap_password, pass, app_password
      port: port, imap_port
      folder: folder, imap_folder
      use_ssl: use_ssl, imap_use_ssl, ssl
      mark_read: mark_read, imap_mark_read
    """
    if not user:
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)

    form = await request.form()

    def pick(*keys: str) -> Optional[str]:
        for k in keys:
            v = form.get(k)
            if v is not None and str(v).strip() != "":
                return str(v)
        return None

    def pick_int(*keys: str) -> Optional[int]:
        v = pick(*keys)
        if v is None:
            return None
        try:
            return int(float(v))
        except Exception:
            return None

    # Pull with aliases
    final_email = pick(
        "email", "imap_email", "mail", "address", "email_address", "imap_email_address"
    )
    final_server = pick(
        "server", "imap_server", "host", "hostname", "imap_host", "imap_hostname"
    )
    final_port = pick_int("port", "imap_port")
    final_username = pick("username", "imap_user", "imap_username", "user", "login")
    final_password = pick("password", "imap_password", "pass", "app_password")
    final_folder = (pick("folder", "imap_folder") or "INBOX").strip() or "INBOX"

    use_ssl = _bool_from_form(pick("use_ssl", "imap_use_ssl", "ssl"))
    mark_read = _bool_from_form(pick("mark_read", "imap_mark_read"))

    # Required
    missing = {
        "email": not bool(final_email),
        "server": not bool(final_server),
        "username": not bool(final_username),
        "password": not bool(final_password),
    }
    if any(missing.values()):
        return JSONResponse(
            {
                "ok": False,
                "error": "Faltan campos requeridos",
                "missing": missing,
                "hint": "Revisá que el <form> tenga name=email, server, username, password (o aliases imap_*).",
            },
            status_code=422,
        )

    # Normalize
    final_email = str(final_email).strip()
    final_server = str(final_server).strip()
    final_username = str(final_username).strip()
    final_password = str(final_password).strip()

    if final_port is None:
        final_port = 993

    # Save per-user
    data = _load_linked()
    uid = str(user["sub"])

    data[uid] = {
        "email": final_email,
        "server": final_server,
        "port": int(final_port),
        "username": final_username,
        # NOTE: en producción real conviene cifrar esto (FERNET_SECRET) y NO guardarlo plano.
        "password": final_password,
        "folder": final_folder,
        "use_ssl": bool(use_ssl),
        "mark_read": bool(mark_read),
    }
    _save_linked(data)

    # Si el POST vino desde el form, redirigimos a /mail para mostrar estado
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        return RedirectResponse(url="/mail", status_code=303)

    return {"ok": True}


# -----------------------------
# Compatibility
# -----------------------------
@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    # GET /mail/settings -> /mail
    return RedirectResponse(url="/mail", status_code=302)
