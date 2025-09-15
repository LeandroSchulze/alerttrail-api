# app/routers/mail.py
import os
import imaplib
import email
from email.header import decode_header, make_header
from datetime import datetime, timedelta
from typing import List, Tuple

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Session

from cryptography.fernet import Fernet, InvalidToken

from app.database import Base, engine, get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

# ---------------- Templates ----------------
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---------------- Cifrado ----------------
def _get_fernet() -> Fernet:
    """
    Usa MAIL_CRYPT_KEY si está y es válida; si no, deriva una clave de JWT_SECRET.
    MAIL_CRYPT_KEY debe ser una key Fernet válida (32 bytes urlsafe-base64).
    """
    import base64, hashlib
    env_key = os.getenv("MAIL_CRYPT_KEY")
    if env_key:
        key_bytes = env_key.encode() if isinstance(env_key, str) else env_key
        try:
            return Fernet(key_bytes)
        except Exception:
            pass
    seed = (os.getenv("JWT_SECRET", "change-me") + "_mail").encode()
    derived = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(derived)

# ---------------- Modelos mínimos ----------------
class MailAccount(Base):
    __tablename__ = "mail_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email = Column(String, nullable=False)

    # Compatibilidad: algunos DBs viejos tienen `imap_host` NOT NULL
    imap_host   = Column(String, nullable=False, default="imap.gmail.com")
    # Campo "nuevo" usado por el código
    imap_server = Column(String, nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    enc_blob  = Column(Text, nullable=False, default="")
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

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[mail] aviso creando tablas: {e}")

# ---------------- Utilidades ----------------
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
    if acct.use_ssl:
        M = imaplib.IMAP4_SSL(acct.imap_server, acct.imap_port)
    else:
        M = imaplib.IMAP4(acct.imap_server, acct.imap_port)
    M.login(data["username"], data["password"])
    return M

# ---------------- Rutas ----------------
@router.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request):
    return templates.TemplateResponse("mail_connect.html", {"request": request})

@router.post("/connect", response_class=HTMLResponse)
async def connect_submit(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    stage = "init"
    try:
        stage = "parse-body"
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("application/json"):
            body = await request.json() or {}
            email_addr  = body.get("email_addr")
            username    = body.get("username")
            password    = body.get("password")
            imap_server = body.get("imap_server") or "imap.gmail.com"
            imap_port   = int(body.get("imap_port") or 993)
            use_ssl     = str(body.get("use_ssl") or "true").lower() in {"1","true","on","yes"}
        else:
            form = await request.form()
            email_addr  = form.get("email_addr")
            username    = form.get("username")
            password    = form.get("password")
            imap_server = form.get("imap_server") or "imap.gmail.com"
            imap_port   = int(form.get("imap_port") or 993)
            use_ssl     = bool(form.get("use_ssl"))

        if not email_addr or not username or not password:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": "Faltan campos (email, usuario o contraseña)."},
                status_code=400,
            )

        stage = "test-imap"
        try:
            if use_ssl:
                M = imaplib.IMAP4_SSL(imap_server, imap_port)
            else:
                M = imaplib.IMAP4(imap_server, imap_port)
            M.login(username, password)
            M.logout()
        except Exception as e:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": f"Error de conexión IMAP: {e}"},
                status_code=400,
            )

        stage = "encrypt"
        import json
        try:
            f = _get_fernet()
            blob = f.encrypt(json.dumps({"username": username, "password": password}).encode()).decode()
        except Exception as e:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": f"Error cifrando credenciales (MAIL_CRYPT_KEY inválida?): {e}"},
                status_code=500,
            )

        stage = "db-commit"
        acct = db.query(MailAccount).filter(
            MailAccount.user_id == user.id,
            MailAccount.email == email_addr
        ).first()
        if acct is None:
            acct = MailAccount(
                user_id=user.id, email=email_addr,
                imap_server=imap_server, imap_port=imap_port,
                use_ssl=use_ssl, enc_blob=blob,
            )
            db.add(acct)
        else:
            acct.imap_server = imap_server
            acct.imap_port = imap_port
            acct.use_ssl = use_ssl
            acct.enc_blob = blob
            db.add(acct)
        db.commit()

        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "ok": True, "email_addr": email_addr},
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "error": f"Fallo en etapa '{stage}': {e}"},
            status_code=500,
        )

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
                findings.append((subject, sender, reasons))
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
      <p><a href="/dashboard">Volver</a></p>
    </body></html>
    """
    return HTMLResponse(html)
