# app/routers/mail.py
import os
import imaplib
import email
from email.header import decode_header, make_header
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Session

from cryptography.fernet import Fernet, InvalidToken

from app.database import Base, engine, get_db
from app.security import get_current_user_cookie

# ---- PRO guard (mail sólo PRO/BIZ) ----
def _is_pro(u) -> bool:
    plan = (getattr(u, "plan", "free") or "free").lower()
    return bool(getattr(u, "is_pro", False)) or plan in {"pro", "biz"}

def require_pro_user(request: Request, current_user=Depends(get_current_user_cookie)):
    if not current_user:
        raise HTTPException(status_code=401, detail="No autenticado")
    if not _is_pro(current_user):
        # 303 con Location -> /billing (lo captura tu handler global para HTML)
        raise HTTPException(
            status_code=303,
            detail="Funcionalidad disponible sólo para PRO",
            headers={"Location": "/billing?upgrade=mail"}
        )

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_pro_user)])

# ---- Templates ----
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---- Alerta in-app (opcional) ----
try:
    from app.services.pro_alerts import queue_or_push  # type: ignore
except Exception:
    queue_or_push = None  # si no existe el módulo, no rompemos

def _notify_alert(user_id: int, subject: str, sender: str, reasons: List[str]) -> None:
    """Envía alerta in-app si está disponible app.services.pro_alerts.queue_or_push."""
    if not queue_or_push:
        return
    try:
        msg = f"Correo sospechoso: {subject} — {sender} ({'; '.join(reasons)})"
        # Ajustá los campos si tu servicio espera otros nombres
        queue_or_push(user_id=user_id, title="Alerta de correo", message=msg, level="warning")
    except Exception:
        pass

# ---- Cifrado credenciales ----
def _get_fernet() -> Fernet:
    """
    Usa MAIL_CRYPT_KEY (Fernet urlsafe-base64) si está; si no, deriva de JWT_SECRET.
    """
    import base64, hashlib
    env_key = os.getenv("MAIL_CRYPT_KEY")
    if env_key:
        try:
            return Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
        except Exception:
            pass
    seed = (os.getenv("JWT_SECRET", "change-me") + "_mail").encode()
    derived = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(derived)

# ---- Modelos locales ----
class MailAccount(Base):
    __tablename__ = "mail_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email = Column(String, nullable=False)

    imap_host   = Column(String, nullable=False, default="imap.gmail.com")  # compat legado
    imap_server = Column(String, nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    enc_blob     = Column(Text, nullable=False, default="")  # JSON cifrado {username,password}
    enc_password = Column(Text, nullable=False, default="")  # legado (NOT NULL en DBs viejas)

    created_at = Column(DateTime, default=datetime.utcnow)

class MailAlert(Base):
    __tablename__ = "mail_alerts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    msg_uid = Column(String, index=True)
    subject = Column(Text)
    sender = Column(String)
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

# Crear tablas si no existen
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[mail] aviso creando tablas: {e}")

# ---- Heurísticas de riesgo ----
SUS_ATTACH_EXTS = {".exe", ".js", ".scr", ".bat", ".cmd", ".vbs", ".html", ".htm", ".zip", ".rar"}
SUS_SUBJECT_WORDS = {"suspend","suspendida","password","contraseña","verify","verificar","urgente","factura","pago","bloqueada","blocked"}

def _decode_hdr(v):
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v or ""

def _risky(msg: email.message.Message) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    subj = _decode_hdr(msg.get("Subject", ""))
    if any(w in subj.lower() for w in SUS_SUBJECT_WORDS):
        reasons.append("Asunto sospechoso")
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            fn = part.get_filename()
            if fn:
                fn_d = _decode_hdr(fn).lower()
                for ext in SUS_ATTACH_EXTS:
                    if fn_d.endswith(ext):
                        reasons.append(f"Adjunto peligroso ({ext})")
                        break
    # enlaces acortados en HTML
    try:
        from bs4 import BeautifulSoup
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True) or b""
                soup = BeautifulSoup(html, "html.parser")  # type: ignore
                for a in soup.find_all("a"):
                    href = (a.get("href") or "").lower()
                    if any(x in href for x in ("bit.ly","tinyurl","goo.gl")):
                        reasons.append("Acortador de URL")
                        break
    except Exception:
        pass
    return (len(reasons) > 0, reasons)

def _imap_login(acct: MailAccount) -> imaplib.IMAP4:
    import json
    f = _get_fernet()
    try:
        data = json.loads(f.decrypt(acct.enc_blob.encode()).decode())
    except (InvalidToken, Exception):
        raise HTTPException(status_code=500, detail="No se pudo descifrar las credenciales")

    server = acct.imap_server or acct.imap_host or "imap.gmail.com"
    port = acct.imap_port or 993

    M = imaplib.IMAP4_SSL(server, port) if acct.use_ssl else imaplib.IMAP4(server, port)
    M.login(data["username"], data["password"])
    return M

# ---- UI Conectar casilla ----
@router.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request):
    return templates.TemplateResponse("mail_connect.html", {"request": request})

@router.post("/connect", response_class=HTMLResponse)
async def connect_submit(request: Request, db: Session = Depends(get_db)):
    """
    Acepta JSON o FormData:
      JSON: {email_addr, username, password, imap_server?, imap_port?, use_ssl?}
      Form: campos con mismos nombres (use_ssl presente => True)
    """
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    stage = "init"
    try:
        stage = "parse-body"
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("application/json"):
            body = await request.json() or {}
            email_addr  = (body.get("email_addr") or "").strip()
            username    = (body.get("username") or "").strip()
            password    = (body.get("password") or "").strip()
            imap_server = (body.get("imap_server") or "imap.gmail.com").strip()
            imap_port   = int(body.get("imap_port") or 993)
            use_ssl     = str(body.get("use_ssl") or "true").lower() in {"1","true","on","yes"}
        else:
            form = await request.form()
            email_addr  = (form.get("email_addr") or "").strip()
            username    = (form.get("username") or "").strip()
            password    = (form.get("password") or "").strip()
            imap_server = (form.get("imap_server") or "imap.gmail.com").strip()
            imap_port   = int(form.get("imap_port") or 993)
            use_ssl     = bool(form.get("use_ssl"))

        if not email_addr or not username or not password:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": "Faltan campos (email, usuario o contraseña)."},
                status_code=400,
            )

        # Test de login
        stage = "test-imap"
        try:
            M = imaplib.IMAP4_SSL(imap_server, imap_port) if use_ssl else imaplib.IMAP4(imap_server, imap_port)
            M.login(username, password)
            M.logout()
        except Exception as e:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": f"Error de conexión IMAP: {e}"},
                status_code=400,
            )

        # Cifrado y commit
        stage = "encrypt"
        import json
        f = _get_fernet()
        blob = f.encrypt(json.dumps({"username": username, "password": password}).encode()).decode()

        stage = "db-commit"
        acct = db.query(MailAccount).filter(
            MailAccount.user_id == user.id,
            MailAccount.email == email_addr
        ).first()

        if acct is None:
            acct = MailAccount(
                user_id=user.id,
                email=email_addr,
                imap_host=imap_server,          # compat
                imap_server=imap_server,
                imap_port=imap_port,
                use_ssl=use_ssl,
                enc_blob=blob,
                enc_password=blob,              # compat
            )
            db.add(acct)
        else:
            acct.imap_host   = imap_server
            acct.imap_server = imap_server
            acct.imap_port   = imap_port
            acct.use_ssl     = use_ssl
            acct.enc_blob    = blob
            acct.enc_password= blob

        db.commit()

        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "ok": True, "email_addr": email_addr},
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "error": f"Fallo en etapa '{stage}': {e}"},
            status_code=500,
        )

# ---- Escaneo manual UI ----
@router.get("/scanner", response_class=HTMLResponse)
def manual_scan(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    acct = db.query(MailAccount).filter(MailAccount.user_id == user.id).order_by(MailAccount.id.desc()).first()
    if not acct:
        return RedirectResponse(url="/mail/connect", status_code=302)

    findings: List[Tuple[str, str, List[str]]] = []
    try:
        M = _imap_login(acct)
        M.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, data = M.search(None, f'(SINCE {since})')
        if status != "OK":
            raise RuntimeError("No pude listar correos")

        uids = data[0].split()[-30:]
        for uid in reversed(uids):
            st, msg_data = M.fetch(uid, "(RFC822)")
            if st != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            risky, reasons = _risky(msg)
            if risky:
                subject = _decode_hdr(msg.get("Subject", ""))
                sender = _decode_hdr(msg.get("From", ""))
                findings.append((subject, sender, reasons))  # <-- AHORA sí se agrega a la lista

                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                exists = db.query(MailAlert).filter(
                    MailAlert.user_id == user.id,
                    MailAlert.msg_uid == uid_str
                ).first()
                if not exists:
                    db.add(MailAlert(
                        user_id=user.id, msg_uid=uid_str,
                        subject=subject, sender=sender,
                        reason="; ".join(reasons),
                    ))
                    db.commit()
                    _notify_alert(user_id=user.id, subject=subject, sender=sender, reasons=reasons)
        M.logout()
    except Exception as e:
        return HTMLResponse(f"<h2>Error escaneando: {e}</h2>", status_code=500)

    items = "".join(
        f"<li><b>{subj}</b><br><small>{sender}</small><br><i>{'; '.join(reas)}</i></li>"
        for (subj, sender, reas) in findings
    ) or "<li>Sin hallazgos recientes</li>"

    html = f"""
    <html><body style="font-family:system-ui">
      <h2>Mail Scanner</h2>
      <p>Cuenta: {acct.email}</p>
      <ul>{items}</ul>
      <p><a href="/mail/alerts">Ver alertas guardadas</a> · <a href="/dashboard">Volver</a></p>
    </body></html>
    """
    return HTMLResponse(html)

# ---- Vista simple de alertas guardadas ----
@router.get("/alerts", response_class=HTMLResponse)
def list_alerts(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    rows = db.query(MailAlert).filter(MailAlert.user_id == user.id).order_by(MailAlert.created_at.desc()).limit(100).all()
    lis = "".join(
        f"<li><b>{_decode_hdr(r.subject or '')}</b> — <small>{_decode_hdr(r.sender or '')}</small>"
        f"<br><i>{r.reason or ''}</i><br><small>{r.created_at}</small></li>"
        for r in rows
    ) or "<li>Sin alertas</li>"
    return HTMLResponse(f"<h2 style='font-family:system-ui'>Alertas</h2><ul>{lis}</ul><p><a href='/dashboard'>Volver</a></p>")

# ---- Helpers para cron / API ----
MAIL_CRON_SECRET = os.getenv("MAIL_CRON_SECRET", "")

def _scan_account(db: Session, acct: MailAccount) -> dict:
    scans = alerts = errors = 0
    try:
        M = _imap_login(acct)
        M.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, data = M.search(None, f'(SINCE {since})')
        if status != "OK":
            raise RuntimeError("No pude listar correos")

        uids = data[0].split()[-30:]
        for uid in reversed(uids):
            st, msg_data = M.fetch(uid, "(RFC822)")
            if st != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            risky, reasons = _risky(msg)
            scans += 1
            if risky:
                subject = _decode_hdr(msg.get("Subject", ""))
                sender = _decode_hdr(msg.get("From", ""))
                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                exists = db.query(MailAlert).filter(
                    MailAlert.user_id == acct.user_id,
                    MailAlert.msg_uid == uid_str
                ).first()
                if not exists:
                    db.add(MailAlert(
                        user_id=acct.user_id, msg_uid=uid_str,
                        subject=subject, sender=sender,
                        reason="; ".join(reasons),
                    ))
                    db.commit()
                    _notify_alert(user_id=acct.user_id, subject=subject, sender=sender, reasons=reasons)
                alerts += 1
        M.logout()
    except Exception:
        errors += 1
    return {"scans": scans, "alerts": alerts, "errors": errors}

def _run_scan_all_accounts(db: Session) -> dict:
    total = {"scans": 0, "alerts": 0, "errors": 0}
    accounts = db.query(MailAccount).all()
    for acct in accounts:
        r = _scan_account(db, acct)
        total["scans"] += r["scans"]
        total["alerts"] += r["alerts"]
        total["errors"] += r["errors"]
    return total

# ---- Endpoint cron seguro ----
@router.get("/poll")
def mail_poll(secret: str, db: Session = Depends(get_db)):
    if not MAIL_CRON_SECRET:
        raise HTTPException(status_code=503, detail="MAIL_CRON_SECRET no configurado")
    if secret != MAIL_CRON_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    result = _run_scan_all_accounts(db)
    return {"status": "ok", "source": "cron", **result}

# ---- Endpoint API manual ----
@router.api_route("/scan", methods=["GET", "POST"])
def mail_scan_api(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    acct = db.query(MailAccount).filter(MailAccount.user_id == user.id).order_by(MailAccount.id.desc()).first()
    if not acct:
        raise HTTPException(status_code=404, detail="No hay casillas vinculadas")

    result = _scan_account(db, acct)
    return {"status": "ok", "source": "manual", **result}
