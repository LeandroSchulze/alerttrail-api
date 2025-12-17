# app/routers/mail.py
import os, json, socket, imaplib, email
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from email.header import decode_header

from app.i18n import get_lang, t
from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["t"] = t

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"
SUMMARY_FILE = MAIL_DATA_DIR / "mail_last_summary.json"


def _load_linked() -> Dict[str, Any]:
    if not LINKED_FILE.exists():
        return {}
    try:
        return json.loads(LINKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linked(data: Dict[str, Any]) -> None:
    LINKED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", ""),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1") in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0") in ("1", "true", "yes", "on"),
    }


def _connect_imap(server: str, port: int, use_ssl: bool):
    if use_ssl:
        return imaplib.IMAP4_SSL(server, port)
    return imaplib.IMAP4(server, port)


def _decode_mime_words(s: str) -> str:
    try:
        parts = decode_header(s or "")
        out = ""
        for part, enc in parts:
            if isinstance(part, bytes):
                out += part.decode(enc or "utf-8", errors="ignore")
            else:
                out += part
        return out
    except Exception:
        return s or ""


def get_current_user_cookie_dep(request: Request):
    return get_current_user_cookie(request)


@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie_dep)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {
        "request": request,
        "page_title": "Casillas de correo",
        "current_user": user,
        "defaults": _defaults_from_env(),
        "linked": linked,
    }
    ctx["lang"] = get_lang(request)
    return templates.TemplateResponse("mail.html", ctx)


@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie_dep)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {
        "request": request,
        "page_title": "Scanner de correos",
        "current_user": user,
        "defaults": _defaults_from_env(),
        "linked": linked,
    }
    ctx["lang"] = get_lang(request)
    return templates.TemplateResponse("mail_scanner.html", ctx)


@router.get("/settings", response_class=HTMLResponse)
def mail_settings(request: Request, user=Depends(get_current_user_cookie_dep)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {
        "request": request,
        "page_title": "Configuración IMAP",
        "current_user": user,
        "defaults": _defaults_from_env(),
        "linked": linked,
    }
    ctx["lang"] = get_lang(request)
    return templates.TemplateResponse("mail_settings.html", ctx)

# (el resto del archivo puede seguir igual que ya lo tenías)
