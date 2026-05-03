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

from app.utils import get_lang_and_translator 
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.services.mail_scan import scan_mailbox
from app.database import get_db
from app.models import MailAccount

router = APIRouter(prefix="/mail", tags=["mail"])
log = logging.getLogger(__name__)

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)
LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"

# --- HELPERS ---
def _now_iso() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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

def _user_id(user: Dict[str, Any]) -> str:
    return str(user.get("id") or user.get("email") or "anon")

def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"

def _load_linked_one(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = _load_json(LINKED_FILE, {})
    return data.get(_user_id(user)) if isinstance(data, dict) else None

def _save_linked_one(user: Dict[str, Any], payload: Dict[str, Any]) -> None:
    all_linked = _load_json(LINKED_FILE, {})
    if not isinstance(all_linked, dict): all_linked = {}
    all_linked[_user_id(user)] = payload
    _save_json(LINKED_FILE, all_linked)

def get_user(request: Request): return get_current_user_cookie_optional(request)

# --- RUTAS ---

@router.get("", response_class=HTMLResponse)
def mail_settings(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    linked = _load_linked_one(user)
    if not linked and user.get("id"):
        acc = db.query(MailAccount).filter(MailAccount.user_id == user.get("id")).first()
        if acc:
            linked = {"address": acc.email_address, "host": acc.imap_host, "username": acc.email_address, "port": 993, "folder": "INBOX", "use_ssl": True}

    return templates.TemplateResponse(request=request, name="mail.html", context={"lang": lang, "t": t_func, "user": user, "linked": linked})

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    
    linked = _load_linked_one(user)
    if not linked and user.get("id"):
        acc = db.query(MailAccount).filter(MailAccount.user_id == user.get("id")).first()
        if acc:
            linked = {"address": acc.email_address, "host": acc.imap_host, "password": acc.imap_password, "username": acc.email_address, "port": 993, "folder": "INBOX", "use_ssl": True}
    
    last_scan_raw = _load_json(_scan_file_for(user), {})
    scan_items = last_scan_raw.get("items", [])
    last_scan = {"ts": last_scan_raw.get("scanned_at") or "", "total": last_scan_raw.get("total", 0)}
    
    return templates.TemplateResponse(request=request, name="mail_scanner.html", context={"lang": lang, "t": t_func, "user": user, "linked": linked, "last_scan": last_scan, "scan_items": scan_items})

@router.post("/settings")
def mail_settings_save(request: Request, user=Depends(get_user), db: Session = Depends(get_db), address: str = Form(""), host: str = Form("imap.gmail.com"), port: str = Form("993"), username: str = Form(""), password: str = Form(""), folder: str = Form("INBOX"), use_ssl: Optional[str] = Form(None), mark_read: Optional[str] = Form(None)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    
    payload = {"address": address.strip(), "host": host.strip(), "port": int(port or 993), "username": username.strip() or address.strip(), "password": password.strip(), "folder": folder.strip() or "INBOX", "use_ssl": (use_ssl is not None), "mark_read": (mark_read is not None), "updated_at": _now_iso()}
    _save_linked_one(user, payload)

    uid = user.get("id")
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if not acc: acc = MailAccount(user_id=uid); db.add(acc)
        acc.email_address = payload["address"]; acc.imap_host = payload["host"]; acc.imap_password = payload["password"]; acc.is_active = True
        db.commit()
    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)

@router.get("/scan")
def scan_get(request: Request, user=Depends(get_user), db: Session = Depends(get_db), limit: int = Query(20)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    
    # IMPORTANTE: Fallback a Postgres si el JSON se borró
    linked = _load_linked_one(user)
    if not linked and user.get("id"):
        acc = db.query(MailAccount).filter(MailAccount.user_id == user.get("id")).first()
        if acc:
            linked = {"host": acc.imap_host, "port": 993, "password": acc.imap_password, "username": acc.email_address, "folder": "INBOX", "use_ssl": True}

    if not linked: return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(host=linked["host"], port=linked["port"], username=linked["username"], password=linked["password"], folder=linked["folder"], use_ssl=linked["use_ssl"], limit=limit)

    items = []
    for it in (res.items or []):
        lvl = str(getattr(it.analysis, "danger_level", "low")).lower()
        items.append({"uid": str(it.uid), "subject": str(it.subject), "from": str(it.from_email), "date": str(it.date), "date_ts": _parse_date_ts(str(it.date)), "verdict": lvl.upper(), "reasons": getattr(it.analysis, "reasons", [])})
    items.sort(key=lambda x: x["date_ts"], reverse=True)

    _save_json(_scan_file_for(user), {"ok": res.ok, "scanned_at": _now_iso(), "items": items, "total": res.total_found})
    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
