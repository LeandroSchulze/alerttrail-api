# app/routers/auth.py
import os
import re
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
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
    issue_access_cookie_for_user,  # 👈 importado
    # Constantes para cookies
    COOKIE_NAME, COOKIE_PATH, COOKIE_HTTPONLY, COOKIE_SECURE, COOKIE_SAMESITE,
)

# COOKIE_DOMAIN puede no existir en algunas versiones -> fallback
try:
    from app.security import COOKIE_DOMAIN  # type: ignore
except Exception:
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")

# Templates en app/templates
APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/auth", tags=["auth"])

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

# ---------------- Schemas ----------------
class LoginJSON(BaseModel):
    email: EmailStr
    password: str

class RegisterJSON(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

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
          </form>
        </body></html>
        """
        return HTMLResponse(inline, status_code=200)

# ---------------- JSON APIs ----------------
@router.post("/register", response_model=dict)
def register(payload: RegisterJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password requerido")

    exists = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if exists:
        raise HTTPException(status_code=409, detail="El email ya está registrado")

    user = models.User(email=email, name=(payload.name or email.split("@")[0]))
    _set_user_pwd(user, get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "name": getattr(user, "name", None)}

@router.post("/login", response_model=TokenOut)
def login_json(payload: LoginJSON, db: Session = Depends(get_db)):
    email = _norm_email(payload.email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if not user or not verify_password(payload.password, _get_user_pwd(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    # 👇 Usamos issue_access_cookie_for_user en vez de create_access_token simple
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

    resp = RedirectResponse(url=(next_url or "/dashboard"), status_code=303)

    # 👇 Generamos cookie con claims completos
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
        db.commit()
        action = "actualizado"
    else:
        user = models.User(email=email, name=name)
        _set_user_pwd(user, get_password_hash(password))
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
    return {"ok": ok, "user_id": getattr(user, "id", None)}
