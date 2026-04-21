# app/routers/mail.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session # <-- Agregado

from app.i18n import get_lang, t
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.services.mail_scan import scan_mailbox
from app.database import get_db # <-- Agregado
from app.models import MailAccount # <-- Agregado

router = APIRouter(prefix="/mail", tags=["mail"])
log = logging.getLogger(__name__)

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"

# --- HELPERS ---

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _parse_date_ts(v: str) -> int:
    s = (v or "").strip()
    if not s: return 0
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except: pass
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except: return 0

def _load_json(path: Path, default):
    try:
        if not path.exists(): return default
        return json.loads(path.read_text(encoding="utf-8"))
    except: return default

def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _truthy(v: Any) -> bool:
    if v is None: return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on", "si", "sí")

def _user_id(user: Dict[str, Any]) -> str:
    # IMPORTANTE: Usamos el ID numérico si está disponible para la DB
    return str(user.get("id") or user.get("email") or "anon")

def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"

def _compute_plan(user: Dict[str, Any]) -> str:
    return str(user.get("plan") or "FREE").upper()

def _defaults_from_env() -> Dict[str, Any]:
    return {
        "host": os.getenv("MAIL_DEFAULT_HOST", "imap.gmail.com"),
        "port": int(os.getenv("MAIL_DEFAULT_PORT", "993")),
        "folder": os.getenv("MAIL_DEFAULT_FOLDER", "INBOX"),
        "use_ssl": os.getenv("MAIL_DEFAULT_SSL", "1"),
        "mark_read": os.getenv("MAIL_DEFAULT_MARK_READ", "0"),
    }

def _verdict_from_level(level: str) -> str:
    lvl = (level or "").lower()
    if lvl == "high": return "ALTO"
    if lvl == "medium": return "MEDIO"
    return "BAJO"

def _load_linked_all() -> Dict[str, Any]:
    data = _load_json(LINKED_FILE, {}) or {}
    return data if isinstance(data, dict) else {}

def _load_linked_one(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _load_linked_all().get(_user_id(user))

def _save_linked_one(user: Dict[str, Any], payload: Dict[str, Any]) -> None:
    all_linked = _load_linked_all()
    all_linked[_user_id(user)] = payload
    _save_json(LINKED_FILE, all_linked)

def get_user(request: Request):
    return get_current_user_cookie_optional(request)

# --- RUTAS ---

@router.get("", response_class=HTMLResponse)
def mail_settings(request: Request, user=Depends(get_user)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked_one(user)
    return templates.TemplateResponse("mail.html", {
        "request": request, "lang": lang, "t": t, "current_user": user,
        "user": user, "plan": plan, "defaults": _defaults_from_env(), "linked": linked,
    })

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked_one(user)
    last_scan_raw = _load_json(_scan_file_for(user), {}) or {}
    scan_items = last_scan_raw.get("items", [])
    if not isinstance(scan_items, list): scan_items = []
    try:
        scan_items.sort(key=lambda x: int(x.get("date_ts") or 0), reverse=True)
    except: pass
    last_scan = {
        "ts": last_scan_raw.get("scanned_at") or last_scan_raw.get("ts") or "",
        "folder": last_scan_raw.get("folder") or "",
        "found": last_scan_raw.get("total") if isinstance(last_scan_raw.get("total"), int) else last_scan_raw.get("found", 0),
        "limit": last_scan_raw.get("limit", 0),
        "error": last_scan_raw.get("error"),
    }
    return templates.TemplateResponse("mail_scanner.html", {
        "request": request, "lang": lang, "t": t, "current_user": user,
        "user": user, "plan": plan, "defaults": _defaults_from_env(), "linked": linked,
        "last_scan": last_scan, "scan_items": scan_items,
    })

@router.post("/settings")
def mail_settings_save(
    request: Request,
    user=Depends(get_user),
    db: Session = Depends(get_db), # Inyectamos la DB
    address: str = Form(""),
    host: str = Form("imap.gmail.com"),
    port: str = Form("993"),
    username: str = Form(""),
    password: str = Form(""),
    folder: str = Form("INBOX"),
    use_ssl: Optional[str] = Form(None),
    mark_read: Optional[str] = Form(None),
):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)

    try: port_i = int(port or 993)
    except: port_i = 993

    # Preparar datos
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

    # 1. GUARDAR EN JSON (Para la UI actual)
    _save_linked_one(user, payload)

    # 2. GUARDAR EN DB (Para el Background Scanner persistente)
    try:
        uid = user.get("id")
        if uid:
            acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
            if not acc:
                acc = MailAccount(user_id=uid)
                db.add(acc)
            
            acc.email_address = payload["address"]
            acc.imap_host = payload["host"]
            acc.imap_port = payload["port"]
            acc.imap_username = payload["username"]
            acc.imap_password = payload["password"] # Aquí queda fija la App Password
            acc.imap_folder = payload["folder"]
            acc.imap_ssl = payload["use_ssl"]
            acc.mark_read = payload["mark_read"]
            acc.is_active = True
            
            db.commit()
            log.info(f"Cuenta persistida en DB para usuario {uid}")
    except Exception as e:
        db.rollback()
        log.error(f"Error al persistir en DB: {e}")

    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)

# ... [El resto de las funciones scan_get y scan_post quedan igual] ...
