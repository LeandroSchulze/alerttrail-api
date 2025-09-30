# app/routers/auth_email_verification_web.py
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import secrets, string

from app.database import SessionLocal
from app.models import User
from app.mailer import send_email

router = APIRouter(prefix="/auth", tags=["auth"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _gen_code(n=6, digits_only=True):
    alphabet = (string.digits if digits_only else (string.ascii_uppercase + string.digits))
    return "".join(secrets.choice(alphabet) for _ in range(n))

# --- Página simple para pedir código ---
@router.get("/verify", response_class=HTMLResponse, include_in_schema=False)
def verify_page(request: Request, email: str = ""):
    html = f"""<!doctype html><meta charset="utf-8">
    <title>Verificación de email</title>
    <div style="font-family:system-ui;max-width:420px;margin:40px auto;padding:20px;border:1px solid #e5e7eb;border-radius:12px">
      <h2>Verificá tu email</h2>
      <form method="post" action="/auth/register/email-code/web" style="display:grid;gap:8px;margin-top:10px">
        <label>Email</label>
        <input name="email" type="email" required value="{email}">
        <button style="padding:10px;border-radius:8px;background:#2563eb;color:#fff;border:0">Enviar código</button>
      </form>
      <hr style="margin:16px 0;border:none;border-top:1px solid #e5e7eb">
      <form method="post" action="/auth/verify-email/web" style="display:grid;gap:8px">
        <label>Email</label>
        <input name="email" type="email" required value="{email}">
        <label>Código</label>
        <input name="code" inputmode="numeric" minlength="4" maxlength="12" required>
        <button style="padding:10px;border-radius:8px;background:#16a34a;color:#fff;border:0">Verificar</button>
      </form>
      <p style="color:#64748b;margin-top:10px">El código vence a los 15 minutos.</p>
      <p style="margin-top:10px"><a href="/login">Volver al login</a></p>
    </div>"""
    return HTMLResponse(html)

# --- Enviar código (web, vía <form>) ---
@router.post("/register/email-code/web", include_in_schema=False)
def send_code_web(email: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.query(User).filter(User.email.ilike(email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if getattr(user, "email_verified", False):
        # idempotente: ya verificado
        return RedirectResponse(url=f"/auth/verify?email={email}", status_code=303)

    code = _gen_code(6, digits_only=True)
    user.verification_code = code
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
    user.verification_attempts = 0
    db.add(user); db.commit()

    subject = "Verificá tu email en AlertTrail"
    body = f"Hola,\n\nTu código de verificación es: {code}\nVence en 15 minutos.\n\nGracias,\nAlertTrail"
    html = f"<p>Hola,</p><p>Tu código de verificación es: <b>{code}</b></p><p>Vence en 15 minutos.</p><p>Gracias,<br>AlertTrail</p>"
    try:
        send_email(to=email, subject=subject, body=body, html=html)
    except Exception:
        # Podés mostrar un mensaje más amistoso si querés
        pass

    # Volvemos a la página con el email precargado
    return RedirectResponse(url=f"/auth/verify?email={email}", status_code=303)

# --- Verificar código (web, vía <form>) ---
@router.post("/auth/verify-email/web", include_in_schema=False)
def verify_email_web(email: str = Form(...), code: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    code = code.strip()
    user = db.query(User).filter(User.email.ilike(email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if getattr(user, "email_verified", False):
        return RedirectResponse(url="/dashboard", status_code=303)

    attempts = int(getattr(user, "verification_attempts", 0) or 0)
    if attempts >= 10:
        raise HTTPException(status_code=429, detail="Demasiados intentos, pedí un código nuevo")

    if not user.verification_code or not user.verification_expires_at:
        raise HTTPException(status_code=400, detail="No hay un código activo, pedí uno nuevo")
    if datetime.utcnow() > user.verification_expires_at:
        raise HTTPException(status_code=410, detail="Código expirado, pedí uno nuevo")

    if not secrets.compare_digest(code, user.verification_code):
        user.verification_attempts = attempts + 1
        db.add(user); db.commit()
        raise HTTPException(status_code=400, detail="Código inválido")

    user.email_verified = True
    user.verification_code = None
    user.verification_expires_at = None
    user.verification_attempts = 0
    db.add(user); db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)
