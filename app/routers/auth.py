# app/routers/auth.py
import os
import secrets
import time
from typing import Optional

from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import (
    get_password_hash, verify_password,
    issue_access_cookie, clear_access_cookie,
    get_current_user_cookie, issue_csrf, validate_csrf
)

# ---------- Templates ----------
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------- Rate limiting (login) ----------
from collections import defaultdict, deque

_LOGIN_WINDOW = int(os.getenv("LOGIN_WINDOW_SEC", "300"))        # 5 min
_LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10")) # 10 intentos
_login_attempts = defaultdict(deque)

def _rl_check(ip: str):
    now = time.time()
    q = _login_attempts[ip]
    while q and now - q[0] > _LOGIN_WINDOW:
        q.popleft()
    if len(q) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Demasiados intentos, probá más tarde")

def _rl_hit(ip: str, success: bool):
    now = time.time()
    q = _login_attempts[ip]
    q.append(now)
    if success:
        q.clear()

# ---------- Email verification ----------
_CODE_TTL_MIN = int(os.getenv("EMAIL_CODE_TTL_MIN", "15"))

def _issue_email_code(user: User, db: Session) -> str:
    code = secrets.token_urlsafe(8)
    user.email_code = code
    user.email_code_expires = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MIN)
    db.add(user); db.commit(); db.refresh(user)
    # TODO: enviar correo real; por ahora, log:
    print(f"[verify-email] code={code} for {user.email}")
    return code

def _must_verify(user: User) -> bool:
    # Si existe columna is_email_verified, la usamos; de lo contrario no bloqueamos
    return bool(getattr(user, "is_email_verified", True) is False)

# ---------- Schemas ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

# ---------- Rutas ----------
@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    try:
        resp = templates.TemplateResponse("login.html", {"request": request})
        issue_csrf(resp)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except TemplateNotFound:
        html = """<!doctype html><meta charset='utf-8'>
        <title>Login — AlertTrail</title>
        <form method="post" action="/auth/login/web"
              style="font-family:system-ui;padding:24px;display:grid;gap:8px;max-width:320px">
          <h2>Iniciar sesión</h2>
          <input name="email" type="email" placeholder="Email" required>
          <input name="password" type="password" placeholder="Contraseña" required>
          <input type="hidden" name="csrf_token" id="csrf_token">
          <button>Entrar</button>
          <script>
            // lee csrftoken de cookie
            const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
            if (m) document.getElementById('csrf_token').value = decodeURIComponent(m[1]);
          </script>
        </form>"""
        return HTMLResponse(html)

@router.post("/login")
async def login_api(request: Request, response: Response, email: EmailStr = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    await validate_csrf(request)
    ip = request.client.host if request.client else "unknown"
    _rl_check(ip)
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
    if not user or not verify_password(password, hp or ""):
        _rl_hit(ip, success=False)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    _rl_hit(ip, success=True)
    issue_access_cookie(response, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    return {"ok": True, "user_id": user.id}

@router.post("/login/web")
async def login_web(request: Request, email: EmailStr = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    await validate_csrf(request)
    ip = request.client.host if request.client else "unknown"
    _rl_check(ip)
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
    if not user or not verify_password(password, hp or ""):
        _rl_hit(ip, success=False)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    _rl_hit(ip, success=True)
    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    return r

@router.post("/logout")
def logout_api():
    r = JSONResponse({"ok": True, "logged_out": True}); clear_access_cookie(r); return r

@router.get("/logout", include_in_schema=False)
def logout_get():
    r = RedirectResponse(url="/", status_code=303); clear_access_cookie(r); return r

@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    u = get_current_user_cookie(request, db)
    return {
        "id": getattr(u, "id", None),
        "email": getattr(u, "email", None),
        "name": getattr(u, "name", None),
        "role": getattr(u, "role", None),
        "plan": getattr(u, "plan", None),
        "is_pro": bool(getattr(u, "is_pro", False)),
        "is_email_verified": bool(getattr(u, "is_email_verified", True)),
    }

@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    user = User(
        email=email,
        name=(payload.name or email.split("@")[0]),
        hashed_password=get_password_hash(payload.password),
        plan=getattr(User, "plan").default.arg if hasattr(getattr(User, "plan"), "default") else "free",
        is_email_verified=False if hasattr(User, "is_email_verified") else True,
    )
    db.add(user); db.commit(); db.refresh(user)
    # emitir código si corresponde
    try:
        if _must_verify(user):
            _issue_email_code(user, db)
    except Exception as e:
        print("[register] warn issue email code:", e)
    return {"ok": True, "user_id": user.id}

@router.post("/resend-code")
def resend_code(request: Request, db: Session = Depends(get_db)):
    u = get_current_user_cookie(request, db)
    if not _must_verify(u):
        return {"ok": True, "already_verified": True}
    _issue_email_code(u, db)
    return {"ok": True}

@router.post("/verify")
def verify_email(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    u = get_current_user_cookie(request, db)
    if not hasattr(u, "is_email_verified"):
        return {"ok": True, "skipped": True}
    if not u.email_code or not u.email_code_expires:
        raise HTTPException(400, "No hay código pendiente")
    now = datetime.now(timezone.utc)
    if now > u.email_code_expires:
        raise HTTPException(400, "Código expirado")
    if code != u.email_code:
        raise HTTPException(400, "Código inválido")
    u.is_email_verified = True
    u.email_code = None
    u.email_code_expires = None
    db.add(u); db.commit()
    return {"ok": True, "verified": True}
