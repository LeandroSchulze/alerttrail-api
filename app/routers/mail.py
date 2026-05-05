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
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.i18n.utils import get_lang_and_translator 
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.services.mail_scan import scan_mailbox
from app.database import get_db
from app.models import MailAccount

router = APIRouter(prefix="/mail", tags=["mail"])
log = logging.getLogger(__name__)

# Directorio para resultados temporales de escaneo (caché)
MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

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
    except: 
        return 0

def _load_json(path: Path, default):
    try:
        if not path.exists(): return default
        return json.loads(path.read_text(encoding="utf-8"))
    except: 
        return default

def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _user_id(user: Dict[str, Any]) -> str: 
    return str(user.get("id") or user.get("email") or "anon")

def _scan_file_for(user: Dict[str, Any]) -> Path: 
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"

def _defaults_from_env() -> Dict[str, Any]:
    return {
        "host": os.getenv("MAIL_HOST", "imap.gmail.com"), 
        "port": int(os.getenv("MAIL_PORT", "993")), 
        "folder": os.getenv("MAIL_FOLDER", "INBOX"), 
        "use_ssl": True
    }

def get_user(request: Request): 
    return get_current_user_cookie_optional(request)

# --- RUTAS ---

@router.get("", response_class=HTMLResponse)
def mail_settings(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    """Muestra la configuración de la cuenta de correo."""
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    linked = None
    # CRÍTICO: Aseguramos que el ID sea un entero para la consulta en DB
    try:
        uid = int(user.get("id")) if user.get("id") else None
    except (ValueError, TypeError):
        uid = None

    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc:
            linked = {
                "address": acc.email_address, 
                "host": acc.imap_host, 
                "username": acc.email_address, 
                "port": 993, 
                "folder": "INBOX", 
                "use_ssl": True
            }

    return templates.TemplateResponse(
        request=request, 
        name="mail.html", 
        context={"lang": lang, "t": t_func, "user": user, "linked": linked, "defaults": _defaults_from_env()}
    )

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    """Muestra el dashboard de resultados del escaneo."""
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    linked = None
    try:
        uid = int(user.get("id")) if user.get("id") else None
    except (ValueError, TypeError):
        uid = None

    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc:
            linked = {
                "address": acc.email_address, 
                "host": acc.imap_host, 
                "username": acc.email_address, 
                "port": 993, 
                "folder": "INBOX", 
                "use_ssl": True
            }
    
    last_scan_raw = _load_json(_scan_file_for(user), {})
    scan_items = last_scan_raw.get("items", [])
    last_scan = {
        "ts": last_scan_raw.get("scanned_at") or "", 
        "total": last_scan_raw.get("total", 0)
    }
    
    return templates.TemplateResponse(
        request=request, 
        name="mail_scanner.html", 
        context={"lang": lang, "t": t_func, "user": user, "linked": linked, "last_scan": last_scan, "scan_items": scan_items}
    )

@router.post("/settings")
def mail_settings_save(
    request: Request, 
    user=Depends(get_user), 
    db: Session = Depends(get_db), 
    address: str = Form(""), 
    host: str = Form("imap.gmail.com"), 
    port: str = Form("993"), 
    username: str = Form(""), # Recibimos el username del formulario
    password: str = Form(""), 
    folder: str = Form("INBOX")
):
    """Guarda la configuración de IMAP en la base de datos persistente."""
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    
    try:
        uid = int(user.get("id")) if user.get("id") else None
    except (ValueError, TypeError):
        uid = None

    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if not acc:
            acc = MailAccount(user_id=uid)
            db.add(acc)
        
        # Priorizamos address, si está vacío usamos username
        final_email = address.strip() or username.strip()
        acc.email_address = final_email
        acc.imap_host = host.strip()
        
        if password.strip():
            acc.imap_password = password.strip()
        
        acc.is_active = True
        
        db.commit()
        db.refresh(acc)
        log.info(f"Configuración guardada para usuario {uid}: {final_email}")

    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)

@router.get("/scan")
def scan_get(request: Request, user=Depends(get_user), db: Session = Depends(get_db), limit: int = Query(20)):
    """Ejecuta el escaneo de correos usando los datos de la DB."""
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    
    try:
        uid = int(user.get("id")) if user.get("id") else None
    except (ValueError, TypeError):
        uid = None

    acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first() if uid else None

    if not acc or not acc.imap_password:
        return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(
        host=acc.imap_host, 
        port=993, 
        username=acc.email_address, 
        password=acc.imap_password, 
        folder="INBOX", 
        use_ssl=True, 
        limit=limit
    )

    items = []
    for it in (res.items or []):
        lvl = str(getattr(it.analysis, "danger_level", "low")).lower()
        items.append({
            "uid": str(it.uid), 
            "subject": str(it.subject), 
            "from": str(it.from_email), 
            "date": str(it.date), 
            "date_ts": _parse_date_ts(str(it.date)), 
            "verdict": lvl.upper(), 
            "reasons": getattr(it.analysis, "reasons", [])
        })
    
    items.sort(key=lambda x: x["date_ts"], reverse=True)

    _save_json(_scan_file_for(user), {
        "ok": res.ok, 
        "scanned_at": _now_iso(), 
        "items": items, 
        "total": res.total_found
    })
    
    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
