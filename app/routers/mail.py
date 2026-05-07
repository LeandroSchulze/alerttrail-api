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
from app.models import MailAccount, PushSubscription
from app.routers.push import trigger_push_notification

# --- DEFINICIÓN DEL ROUTER (Esto faltaba o estaba abajo) ---
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
    if not user or not isinstance(user, dict): return None
    raw_id = user.get("id") or user.get("user_id") or user.get("sub")
    try: return int(raw_id)
    except: return None

def _user_id_str(user: Dict[str, Any]) -> str: 
    uid = _extract_uid(user)
    return str(uid) if uid else str(user.get("email") or "anon")

def _scan_file_for(user: Dict[str, Any]) -> Path: 
    return MAIL_DATA_DIR / f"scan_last_{_user_id_str(user)}.json"

# --- RUTAS ---

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie_optional), db: Session = Depends(get_db)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    uid = _extract_uid(user)
    linked = None
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc: linked = {"address": acc.email}
    last_scan_raw = _load_json(_scan_file_for(user), {})
    # Aseguramos compatibilidad con el template
    last_scan = {
        "ts": last_scan_raw.get("scanned_at") or "", 
        "total": last_scan_raw.get("total", 0),
        "folder": last_scan_raw.get("folder", "INBOX")
    }
    return templates.TemplateResponse(request=request, name="mail_scanner.html", context={
        "lang": lang, "t": t_func, "user": user, "linked": linked, 
        "last_scan": last_scan, "scan_items": last_scan_raw.get("items", [])
    })

@router.get("/scan")
def scan_get(request: Request, user=Depends(get_current_user_cookie_optional), db: Session = Depends(get_db), limit: int = Query(20)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    uid = _extract_uid(user)
    print(f"🔍 Iniciando escaneo manual para usuario ID: {uid}")
    
    acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first() if uid else None
    if not acc or not acc.password_encrypted: 
        return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(host=acc.host, port=acc.port or 993, username=acc.username or acc.email, password=acc.password_encrypted, folder="INBOX", use_ssl=acc.use_ssl, limit=limit)

    items = []
    high_threat_found = False
    verdict_map = {
        "ALTA": "alerts.severity_high",
        "MEDIA": "alerts.severity_medium",
        "BAJA": "alerts.severity_low"
    }

    for it in (res.items or []):
        raw_reasons = getattr(it.analysis, "reasons", [])
        subject = str(it.subject).lower()
        reasons_flat = str(raw_reasons).lower()
        
        score = 0
        if "links_count" in reasons_flat and "20" in reasons_flat: score += 20
        if "phishing" in reasons_flat: score += 10
        if any(w in subject for w in ["alerta", "urgente", "bloqueo", "confirm"]): score += 10
            
        if score >= 15:
            final_lvl = "ALTA"
            high_threat_found = True
        elif score >= 8:
            final_lvl = "MEDIA"
        else:
            final_lvl = "BAJA"

        print(f"   -> {it.subject[:30]} | Score: {score} | Nivel: {final_lvl}")

        items.append({
            "uid": str(it.uid), 
            "subject": str(it.subject), 
            "from": str(it.from_email), 
            "date": str(it.date), 
            "date_ts": _parse_date_ts(str(it.date)), 
            "verdict": final_lvl,
            "verdict_key": verdict_map[final_lvl],
            "reasons": raw_reasons
        })
    
    items.sort(key=lambda x: x["date_ts"], reverse=True)
    _save_json(_scan_file_for(user), {
        "ok": res.ok, 
        "scanned_at": _now_iso(), 
        "items": items, 
        "total": res.total_found,
        "folder": "INBOX"
    })

    if high_threat_found and uid:
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == uid).all()
        print(f"🔔 AMENAZA ALTA. Suscripciones en DB: {len(subs)}")
        if len(subs) > 0:
            trigger_push_notification(user_id=uid, title="🚨 ALERTA CRÍTICA", body="Se detectó un posible correo malicioso.")

    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
