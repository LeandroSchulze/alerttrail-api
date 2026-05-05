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
    except: return 0

def _load_json(path: Path, default):
    try:
        if not path.exists(): return default
        return json.loads(path.read_text(encoding="utf-8"))
    except: return default

def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _extract_uid(user: Any) -> Optional[int]:
    if not user or not isinstance(user, dict):
        return None
    raw_id = user.get("id") or user.get("user_id") or user.get("sub")
    try:
        return int(raw_id) if raw_id is not None else None
    except (ValueError, TypeError):
        return None

def _user_id_str(user: Dict[str, Any]) -> str: 
    uid = _extract_uid(user)
    return str(uid) if uid else str(user.get("email") or "anon")

def _scan_file_for(user: Dict[str, Any]) -> Path: 
    return MAIL_DATA_DIR / f"scan_last_{_user_id_str(user)}.json"

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
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    uid = _extract_uid(user)
    linked = None
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc:
            # Mapeamos los nombres de la DB a los nombres que usa el HTML
            linked = {
                "address": acc.email, 
                "host": acc.host, 
                "username": acc.username, 
                "port": acc.port, 
                "folder": "INBOX", # Si no hay columna folder, dejamos default
                "use_ssl": acc.use_ssl
            }

    return templates.TemplateResponse(
        request=request, 
        name="mail.html", 
        context={"lang": lang, "t": t_func, "user": user, "linked": linked, "defaults": _defaults_from_env()}
    )

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    uid = _extract_uid(user)
    linked = None
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc:
            linked = {"address": acc.email}
    
    last_scan_raw = _load_json(_scan_file_for(user), {})
    last_scan = {"ts": last_scan_raw.get("scanned_at") or "", "total": last_scan_raw.get("total", 0)}
    
    return templates.TemplateResponse(
        request=request, 
        name="mail_scanner.html", 
        context={"lang": lang, "t": t_func, "user": user, "linked": linked, "last_scan": last_scan, "scan_items": last_scan_raw.get("items", [])}
    )

@router.post("/settings")
def mail_settings_save(
    request: Request, 
    user=Depends(get_user), 
    db: Session = Depends(get_db), 
    address: str = Form(""), 
    host: str = Form("imap.gmail.com"), 
    port: str = Form("993"), 
    username: str = Form(""),
    password: str = Form(""), 
    folder: str = Form("INBOX"),
    use_ssl: bool = Form(True)
):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    
    uid = _extract_uid(user)
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if not acc:
            acc = MailAccount(user_id=uid)
            db.add(acc)
        
        # CORRECCIÓN CRÍTICA: Usar los nombres de columna que pide la DB según el log
        final_email = address.strip() or username.strip()
        acc.email = final_email  # Antes era email_address
        acc.host = host.strip()   # Antes era imap_host
        acc.port = int(port) if port.isdigit() else 993
        acc.username = username.strip() or final_email
        acc.use_ssl = use_ssl
        acc.provider = "imap"

        if password.strip():
            # El log dice que la columna es 'password_encrypted'
            acc.password_encrypted = password.strip()
        
        try:
            db.commit()
            db.refresh(acc)
            log.info(f"Éxito: Guardado {final_email} en la tabla mail_accounts.")
        except Exception as e:
            db.rollback()
            log.error(f"Error en commit: {e}")
    
    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)

@router.get("/scan")
def scan_get(request: Request, user=Depends(get_user), db: Session = Depends(get_db), limit: int = Query(20)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    uid = _extract_uid(user)
    acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first() if uid else None

    # Ajustado a los nombres reales de columna
    if not acc or not acc.password_encrypted:
        return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(
        host=acc.host, 
        port=acc.port or 993, 
        username=acc.username or acc.email, 
        password=acc.password_encrypted, 
        folder="INBOX", 
        use_ssl=acc.use_ssl, 
        limit=limit
    )

    items = []
    for it in (res.items or []):
        lvl = str(getattr(it.analysis, "danger_level", "low")).lower()
        items.append({
            "uid": str(it.uid), "subject": str(it.subject), "from": str(it.from_email), 
            "date": str(it.date), "date_ts": _parse_date_ts(str(it.date)), 
            "verdict": lvl.upper(), "reasons": getattr(it.analysis, "reasons", [])
        })
    
    items.sort(key=lambda x: x["date_ts"], reverse=True)
    _save_json(_scan_file_for(user), {"ok": res.ok, "scanned_at": _now_iso(), "items": items, "total": res.total_found})
    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
