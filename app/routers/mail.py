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
from app.routers.push import trigger_push_notification

router = APIRouter(prefix="/mail", tags=["mail"])
log = logging.getLogger(__name__)

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- HELPERS (Se mantienen igual) ---
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
def _extract_uid(user: Any) -> Optional[int]:
    if not user or not isinstance(user, dict): return None
    raw_id = user.get("id") or user.get("user_id") or user.get("sub")
    try: return int(raw_id)
    except: return None
def _user_id_str(user: Dict[str, Any]) -> str: 
    uid = _extract_uid(user)
    return str(uid) if uid else str(user.get("email") or "anon")
def _scan_file_for(user: Dict[str, Any]) -> Path: return MAIL_DATA_DIR / f"scan_last_{_user_id_str(user)}.json"
def _defaults_from_env() -> Dict[str, Any]:
    return {"host": os.getenv("MAIL_HOST", "imap.gmail.com"), "port": int(os.getenv("MAIL_PORT", "993")), "folder": "INBOX", "use_ssl": True}
def get_user(request: Request): return get_current_user_cookie_optional(request)

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
            linked = {"address": acc.email, "host": acc.host, "username": acc.username, "port": acc.port, "folder": "INBOX", "use_ssl": acc.use_ssl}
    return templates.TemplateResponse(request=request, name="mail.html", context={"lang": lang, "t": t_func, "user": user, "linked": linked, "defaults": _defaults_from_env()})

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user), db: Session = Depends(get_db)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    lang, t_func = get_lang_and_translator(request, user=user)
    uid = _extract_uid(user)
    linked = None
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if acc: linked = {"address": acc.email}
    last_scan_raw = _load_json(_scan_file_for(user), {})
    last_scan = {"ts": last_scan_raw.get("scanned_at") or "", "total": last_scan_raw.get("total", 0)}
    return templates.TemplateResponse(request=request, name="mail_scanner.html", context={"lang": lang, "t": t_func, "user": user, "linked": linked, "last_scan": last_scan, "scan_items": last_scan_raw.get("items", [])})

@router.post("/settings")
def mail_settings_save(request: Request, user=Depends(get_user), db: Session = Depends(get_db), address: str = Form(""), host: str = Form("imap.gmail.com"), port: str = Form("993"), username: str = Form(""), password: str = Form(""), folder: str = Form("INBOX"), use_ssl: bool = Form(True)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    uid = _extract_uid(user)
    if uid:
        acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first()
        if not acc:
            acc = MailAccount(user_id=uid)
            db.add(acc)
        final_email = address.strip() or username.strip()
        acc.email, acc.host, acc.port, acc.username, acc.use_ssl, acc.provider = final_email, host.strip(), (int(port) if port.isdigit() else 993), (username.strip() or final_email), use_ssl, "imap"
        if password.strip(): acc.password_encrypted = password.strip()
        try:
            db.commit()
            db.refresh(acc)
            log.info(f"Éxito: Guardado {final_email}.")
        except Exception as e:
            db.rollback()
            log.error(f"Error: {e}")
    return RedirectResponse(url="/mail/scanner?saved=1", status_code=303)

@router.get("/scan")
def scan_get(request: Request, user=Depends(get_user), db: Session = Depends(get_db), limit: int = Query(20)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    uid = _extract_uid(user)
    acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first() if uid else None
    if not acc or not acc.password_encrypted: return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(host=acc.host, port=acc.port or 993, username=acc.username or acc.email, password=acc.password_encrypted, folder="INBOX", use_ssl=acc.use_ssl, limit=limit)

    items = []
    total_high_threats = 0

    for it in (res.items or []):
        raw_reasons = getattr(it.analysis, "reasons", [])
        subject = str(it.subject).lower()
        sender = str(it.from_email).lower()
        
        # --- MOTOR DE PUNTUACIÓN DE AMENAZAS (COMPLEJO) ---
        score = 0
        
        # 1. Análisis de estructura de motivos
        for r in raw_reasons:
            if isinstance(r, dict):
                key = r.get("key")
                if key == "links_count":
                    count = r.get("count", 0)
                    if count > 10: score += 12 # Crítico
                    elif count > 3: score += 5
                elif key == "phishing_words":
                    words = r.get("words", [])
                    score += (len(words) * 3) # Cada palabra suma 3 puntos
            elif isinstance(r, str):
                if "link" in r.lower(): score += 4

        # 2. Análisis Semántico y de Urgencia
        urgency_list = ["alerta", "urgente", "bloqueo", "suspension", "seguridad", "acceso", "verify", "atencion", "identidad"]
        if any(w in subject for w in urgency_list):
            score += 8
        
        # 3. Detección de Suplantación de Marca (Spoofing)
        # Si el correo dice ser de "AlertTrail" pero no viene de alerttrail.com
        if "alerttrail" in subject and "alerttrail.com" not in sender:
            score += 15 # Penalización masiva
            
        # 4. Veredicto del motor base
        base_lvl = str(getattr(it.analysis, "danger_level", "low")).lower()
        if base_lvl == "high": score += 10
        elif base_lvl == "medium": score += 5

        # Asignación final basada en peso acumulado
        if score >= 18:
            final_lvl = "ALTA"
            total_high_threats += 1
        elif score >= 8:
            final_lvl = "MEDIA"
        else:
            final_lvl = "BAJA"
        # --------------------------------------------------

        items.append({
            "uid": str(it.uid), "subject": str(it.subject), "from": str(it.from_email), 
            "date": str(it.date), "date_ts": _parse_date_ts(str(it.date)), 
            "verdict": final_lvl, "reasons": [str(r) for r in raw_reasons]
        })
    
    items.sort(key=lambda x: x["date_ts"], reverse=True)
    _save_json(_scan_file_for(user), {"ok": res.ok, "scanned_at": _now_iso(), "items": items, "total": res.total_found})

    if total_high_threats > 0 and uid:
        try:
            trigger_push_notification(
                user_id=uid,
                title="🚨 Amenaza Crítica",
                body=f"AlertTrail detectó {total_high_threats} correos altamente peligrosos."
            )
        except Exception as e:
            log.error(f"Error en push: {e}")

    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
