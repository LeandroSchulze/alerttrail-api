# app/routers/auth.py
import os
import re
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app import models
from app.security import (
    verify_password,
    get_password_hash,
    get_current_user_cookie,
    issue_access_cookie_for_user,  # cookie + token (compat)
    # Constantes para cookies
    COOKIE_NAME, COOKIE_PATH, COOKIE_HTTPONLY, COOKIE_SECURE, COOKIE_SAMESITE,
)

# COOKIE_DOMAIN puede no existir en algunas versiones -> fallback
try:
    from app.security import COOKIE_DOMAIN  # type: ignore
except Exception:
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")

# --- servicios para verificación por correo ---
from app.services.mail_send import send_email
from app.services.email_verify import gen_code, expires_at, RESEND_WINDOW_SEC, MAX_VERIFY_ATTEMPTS

# Templates en app/templates
APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------- Helpers ----------------
def _get_user_pwd(u: models.User) -> str:
    return getattr(u, "hashed_password", None) or getattr(u, "password_hash", "") or ""

def _set_user_pwd(u: models.User, pwd_hash: str) -> None:
    if hasattr(u, "hashed_password"):
        setattr(u, "hashed_password", pwd_hash)
    elif hasattr(u, "password_hash"):
        setattr(u, "password_hash", pwd_hash)
    else:
        setattr(u, "hashed_password", pwd_hash)

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _send_verification_email(to_email: str, name: str, code: str):
    subject = "Confirmá tu correo — AlertTrail"
    text = f"""Hola {name},

Usá este código para verificar tu cuenta en AlertTrail: {code}
El código vence en 15 minutos.

Si no fuiste vos, ignorá este mensaje.
"""
    html = f"""
    <div style="font-family:system-ui,Segoe UI,Roboto,Arial">
      <h2>Confirmá tu correo</h2>
      <p>Hola {name},</p>
      <p>Usá este código para verificar tu cuenta en <b>AlertTrail</b>:</p>
      <div style="font-size:28px;font-weight:800;letter-spacing:4px;margin:16px 0">{code}</div>
      <p>El código vence en 15 minutos.</p>
      <p style="color:#64748b">Si no fuiste vos, podés ignorar este mensaje.</p>
    </div>
    """
    send_email(to_email, subject, html, text)


# ---------------- Schemas ----------------
class LoginJSON(BaseModel):
    email: EmailStr
    password: str

class RegisterJSON(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

class VerifyEmailJSON(BaseModel):
    email: EmailStr
    code: str

class ResendCodeJSON(BaseModel):
    email: EmailStr

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------- Vistas HTML ----------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = Query(default="/dashboard")):
    try:
        return templates.TemplateResponse("login.html", {"request": request, "next": next})
    except TemplateNotFound:
        inline = f"""
        <!doctype html><html lang="es"><meta charset="utf-8"><title>Login | AlertTrail</title>
        <body style="font-family:system-ui;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#0b2133;margin:0">
          <form method="post" action="/auth/login/web" style="background:#fff;max-width:420px;width:100%;padding:28px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.06)">
            <h1 style="font-size:20px;margin:0 0 14px">Ingresar</h1>
            <label>Email</label><input name="email" type="email" required style="width:100%;padding:10px;margin:6px 0">
            <label>Contraseña</label><input name="password" type="password" required style="width:100%;padding:10px;margin:6px 0">
            <input type="hidden" name="next_url" value="{next or '/dashboard'}">
            <button type="submit" style="margin-top:12px;padding:10px 14px">Entrar</button>
            <p style="margin-top:10px;font-size:12px;color:#64748b">¿Aún no verificaste tu correo? <a href="#" onclick="alert('Usá /auth/resend-code');return false;">Reenviar código</a></p>
          </form>
        </body></html>
        """
        return HTMLResponse(inline, status_code=200)


# ---------------- Registro (JSON) ----------------
@router.post("/register", response_model=dict)
def register(payload: RegisterJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password requerido")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email inválido")

    exists = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if exists:
        raise HTTPException(status_code=409, detail="El email ya está registrado")

    user = models.User(
        email=email,
        name=(payload.name or email.split("@")[0]),
        email_verified=False,                 # 👈 bloquea login hasta verificar
        verification_attempts=0,
        plan=(getattr(models.User, "plan", None) and "FREE") or "FREE",
    )
    _set_user_pwd(user, get_password_hash(payload.password))

    # Generar y adjuntar código con vencimiento
    code = gen_code()
    user.verification_code = code
    user.verification_expires_at = expires_at()

    db.add(user)
    db.commit()
    db.refresh(user)

    # Enviar email con el código
    _send_verification_email(user.email, user.name or "¡Hola!", code)

    return {"id": user.id, "email": user.email, "name": getattr(user, "name", None), "msg": "Usuario creado. Revisá tu correo para confirmar la cuenta."}


# ---------------- Verificar correo (JSON) ----------------
@router.post("/verify-email")
def verify_email(payload: VerifyEmailJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if getattr(user, "email_verified", False):
        return {"ok": True, "msg": "El correo ya está verificado."}

    # Anti-bruteforce
    max_attempts = MAX_VERIFY_ATTEMPTS
    if (user.verification_attempts or 0) >= max_attempts:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Pedí un nuevo código.")

    now = datetime.now(timezone.utc)
    if not user.verification_code or not user.verification_expires_at or user.verification_expires_at < now:
        raise HTTPException(status_code=400, detail="El código venció. Pedí un nuevo código.")

    user.verification_attempts = (user.verification_attempts or 0) + 1

    if payload.code.strip() != user.verification_code:
        db.commit()
        raise HTTPException(status_code=400, detail="Código incorrecto.")

    # OK
    user.email_verified = True
    user.verification_code = None
    user.verification_expires_at = None
    user.verification_attempts = 0
    db.commit()

    return {"ok": True, "msg": "Correo verificado. Ya podés iniciar sesión."}


# ---------------- Reenviar código (JSON) ----------------
@router.post("/resend-code")
def resend_code(payload: ResendCodeJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if getattr(user, "email_verified", False):
        return {"ok": True, "msg": "El correo ya está verificado."}

    now = datetime.now(timezone.utc)
    # Rate limit simple usando la marca de expiración como referencia del último envío
    ref_time = None
    if user.verification_expires_at:
        ref_time = user.verification_expires_at - timedelta(minutes=15)  # cuando se generó
    if ref_time and (now - ref_time).total_seconds() < RESEND_WINDOW_SEC:
        raise HTTPException(status_code=429, detail="Esperá un momento antes de pedir otro código.")

    code = gen_code()
    user.verification_code = code
    user.verification_expires_at = now + timedelta(minutes=15)
    user.verification_attempts = 0
    db.commit()

    _send_verification_email(user.email, user.name or "¡Hola!", code)
    return {"ok": True, "msg": "Te enviamos un nuevo código."}


# ---------------- Login (JSON) — bloquea si no verificó ----------------
@router.post("/login", response_model=TokenOut)
def login_json(payload: LoginJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if not user or not verify_password(payload.password, _get_user_pwd(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    if not getattr(user, "email_verified", False):
        raise HTTPException(status_code=403, detail="Tu correo no está verificado. Revisá tu email o pedí un nuevo código.")

    # Emitimos cookie + devolvemos el token (compat con tu front actual)
    dummy_resp = Response()
    token = issue_access_cookie_for_user(
        dummy_resp,
        user.id,
        user.email,
        getattr(user, "is_admin", False),
        getattr(user, "plan", "free"),
    )
    return TokenOut(access_token=token)


# ---------------- Login Web (cookie directa + 303) ----------------
@router.post("/login/web")
def login_web(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next_url: Optional[str] = Form(default="/dashboard"),
    db: Session = Depends(get_db),
):
    email_n = _norm_email(email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email_n).first()
    if not user or not verify_password(password, _get_user_pwd(user)):
        try:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Email o password incorrectos", "next": (next_url or "/dashboard")},
                status_code=400,
            )
        except TemplateNotFound:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not getattr(user, "email_verified", False):
        # Mostrar mensaje amable en HTML si tenés template
        try:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Tu correo no está verificado. Revisa tu email o pedí un nuevo código.", "next": (next_url or "/dashboard")},
                status_code=403,
            )
        except TemplateNotFound:
            raise HTTPException(status_code=403, detail="Tu correo no está verificado. Revisá tu email o pedí un nuevo código.")

    resp = RedirectResponse(url=(next_url or "/dashboard"), status_code=303)

    # Generamos cookie con claims completos
    issue_access_cookie_for_user(
        resp,
        user.id,
        user.email,
        getattr(user, "is_admin", False),
        getattr(user, "plan", "free"),
    )

    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------- Yo (sesión por cookie) ----------------
@router.get("/me")
def me(current_user=Depends(get_current_user_cookie)):
    if not current_user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "id": getattr(current_user, "id", None),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
        "email_verified": getattr(current_user, "email_verified", False),
        "is_pro": getattr(current_user, "is_pro", False),
        "plan": (getattr(current_user, "plan", "free") or "free"),
        "role": getattr(current_user, "role", "user"),
    }


# ---------------- Logout (GET/POST, doble borrado) ----------------
@router.api_route("/logout", methods=["GET", "POST"])
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    # sin domain
    resp.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )
    # con domain (si aplica)
    if COOKIE_DOMAIN:
        resp.delete_cookie(
            key=COOKIE_NAME,
            path=COOKIE_PATH,
            domain=COOKIE_DOMAIN,
            httponly=COOKIE_HTTPONLY,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
        )
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------- Debug & Rescate ----------------
@router.get("/_debug_templates")
def _debug_templates():
    try:
        files = [f.name for f in (TEMPLATES_DIR).glob("*.html")]
    except Exception:
        files = []
    return {"templates_dir": str(TEMPLATES_DIR), "exists": Path(TEMPLATES_DIR).exists(), "files": files}

@router.get("/_debug_cookies")
def _debug_cookies(request: Request):
    keys = []
    if "cookie" in request.headers:
        raw = request.headers.get("cookie", "")
        for p in [p.strip() for p in raw.split(";") if p.strip()]:
            k = p.split("=", 1)[0].strip()
            if k and k not in keys:
                keys.append(k)
    return {"cookies_presentes": keys}

@router.post("/_force_admin_reset")
def _force_admin_reset(secret: str = Query(...), db: Session = Depends(get_db)):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET", "")
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    email = _norm_email(os.getenv("ADMIN_EMAIL", "admin@example.com"))
    password = os.getenv("ADMIN_PASS", "ChangeMe123!")
    name = os.getenv("ADMIN_NAME", "Admin")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Faltan ADMIN_EMAIL o ADMIN_PASS")

    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if user:
        _set_user_pwd(user, get_password_hash(password))
        if hasattr(user, "name"):
            user.name = name
        # asegurar admin flags
        if hasattr(user, "role"):
            user.role = "admin"
        if hasattr(user, "is_admin"):
            user.is_admin = True
        if hasattr(user, "is_superuser"):
            user.is_superuser = True
        db.commit()
        action = "actualizado"
    else:
        user = models.User(email=email, name=name)
        _set_user_pwd(user, get_password_hash(password))
        if hasattr(user, "role"):
            user.role = "admin"
        if hasattr(user, "is_admin"):
            user.is_admin = True
        if hasattr(user, "is_superuser"):
            user.is_superuser = True
        db.add(user)
        db.commit()
        db.refresh(user)
        action = "creado"
    return {"ok": True, "admin": user.email, "action": action}

@router.get("/_debug_auth")
def _debug_auth(email: str, password: str, secret: str, db: Session = Depends(get_db)):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET", "")
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    e = _norm_email(email)
    user = db.query(models.User).filter(func.lower(models.User.email) == e).first()
    if not user:
        return {"ok": False, "reason": "not_found"}
    ok = verify_password(password, _get_user_pwd(user))
    return {
        "ok": ok,
        "user_id": getattr(user, "id", None),
        "email_verified": getattr(user, "email_verified", False),
        "plan": getattr(user, "plan", None),
        "role": getattr(user, "role", None),
    }
