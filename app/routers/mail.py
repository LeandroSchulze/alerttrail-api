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

from app.database import Base, engine, get_db
from app.security import get_current_user_cookie

# ====== helpers de cifrado ======
def _get_fernet():
    from cryptography.fernet import Fernet
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

# ====== guard de plan ======
def _is_pro(u) -> bool:
    if bool(getattr(u, "is_admin", False)):
        return True
    plan = ((getattr(u, "plan", "") or "")).strip().lower()
    if bool(getattr(u, "is_pro", False)):
        return True
    return plan in {"pro", "biz", "business", "empresa", "empresas"}

def require_pro_user(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db=db)
    if not user:
        raise HTTPException(status_code=303, detail="login", headers={"Location": "/auth/login"})
    if not _is_pro(user):
        raise HTTPException(status_code=303, detail="Funcionalidad sólo PRO", headers={"Location": "/billing?upgrade=mail"})
    return user

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_pro_user)])

# ====== templates ======
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ====== alertas in-app opcionales ======
try:
    from app.services.pro_alerts import queue_or_push  # type: ignore
except Exception:
    queue_or_push = None

def _notify_alert(user_id: int, subject: str, sender: str, reasons: List[str]) -> None:
    if not queue_or_push:
        return
    try:
        msg = f"Correo sospechoso: {subject} — {sender} ({'; '.join(reasons)})"
        queue_or_push(user_id=user_id, title="Alerta de correo", message=msg, level="warning")
    except Exception:
        pass

# ====== modelos locales ======
class MailAccount(Base):
    __tablename__ = "mail_accounts"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email = Column(String, nullable=False)

    imap_host   = Column(String, nullable=False, default="imap.gmail.com")
    imap_server = Column(String, nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    enc_blob     = Column(Text, nullable=False, default="")  # JSON cifrado {username,password}
    enc_password = Column(Text, nullable=False, default="")  # compat DBs viejas

    created_at = Column(DateTime, default=datetime.utcnow)

class MailAlert(Base):
    __tablename__ = "mail_alerts"
    __table_args__ = {'extend_existing': True}

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

# (… resto del archivo sin cambios …)
