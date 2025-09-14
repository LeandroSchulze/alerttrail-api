import os
import imaplib, email
from email.header import decode_header
from typing import List
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MailAccount, MailScan
from app.security import fernet_encrypt, fernet_decrypt, get_current_user_id

router = APIRouter(prefix="/mail", tags=["mail"])

# Ruta a templates: .../app/templates
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/connect", response_class=HTMLResponse)
async def connect_form(request: Request, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    account = db.query(MailAccount).filter(MailAccount.user_id == user_id).first()
    return templates.TemplateResponse("mail_connect.html", {"request": request, "account": account})

@router.post("/connect")
async def connect_save(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    imap_host: str = Form(...),
    imap_port: int = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    enc = fernet_encrypt(password)
    acc = db.query(MailAccount).filter(MailAccount.user_id == user_id).first()
    if acc:
        acc.imap_host, acc.imap_port, acc.email, acc.enc_password = imap_host, imap_port, email, enc
    else:
        acc = MailAccount(user_id=user_id, imap_host=imap_host, imap_port=imap_port, email=email, enc_password=enc)
        db.add(acc)
    db.commit()

    # Test rápido de conexión
    try:
        M = imaplib.IMAP4_SSL(imap_host, imap_port)
        M.login(email, password)
        M.logout()
    except Exception as e:
        raise HTTPException(400, f"No se pudo conectar: {e}")

    return RedirectResponse("/dashboard", status_code=302)

@router.post("/scan", response_class=HTMLResponse)
async def scan(request: Request, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    acc = db.query(MailAccount).filter(MailAccount.user_id == user_id).first()
    if not acc:
        # No hay cuenta vinculada: enviar al formulario
        return RedirectResponse("/mail/connect", status_code=302)

    pwd = fernet_decrypt(acc.enc_password)
    items = []

    def _decode(s: str) -> str:
        if not s:
            return ""
        parts = decode_header(s)
        out = ""
        for t, enc in parts:
            if isinstance(t, bytes):
                out += t.decode(enc or "utf-8", errors="ignore")
            else:
                out += t
        return out

    try:
        M = imaplib.IMAP4_SSL(acc.imap_host, acc.imap_port)
        M.login(acc.email, pwd)
        M.select("INBOX")
        typ, data = M.search(None, "ALL")
        ids = data[0].split()[-30:]  # últimos 30
        for uid in reversed(ids):
            typ, msg_data = M.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = _decode(msg.get("From"))
            subject = _decode(msg.get("Subject"))
            # Reglas simples de sospecha
            text = (subject or "").lower()
            verdict = "SAFE"
            red_flags = ["urgent", "verify account", "password", "bitcoin", "transfer", "invoice", "factura", "pago", "suspendido", "confirmar"]
            if any(k in text for k in red_flags):
                verdict = "SUSPICIOUS"
            items.append({"sender": sender, "subject": subject, "verdict": verdict})
            db.add(MailScan(user_id=user_id, sender=sender, subject=subject, verdict=verdict))
        db.commit()
        M.logout()
    except Exception as e:
        raise HTTPException(400, f"Fallo al escanear: {e}")

    summary = f"Escaneados {len(items)} correos. Sospechosos: {sum(1 for i in items if i['verdict']=='SUSPICIOUS')}"
    return templates.TemplateResponse("mail_scan_result.html", {"request": request, "summary": summary, "items": items})
