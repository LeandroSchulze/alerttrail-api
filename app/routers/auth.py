# app/routers/auth.py
import os
import re  # requerido si activás algún debug que use regex
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
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
    create_access_token,
    issue_access_cookie,
    get_current_user_cookie,
    # Constantes de cookie: usamos las mismas que al setear para evitar desincronización
    COOKIE_NAME, COOKIE_PATH, COOKIE_HTTPONLY, COOKIE_SECURE, COOKIE_SAMESITE,
)

# COOKIE_DOMAIN puede no estar definido en algunas versiones: fallback suave
try:
    from app.security import COOKIE_DOMAIN  # type: ignore
except Exception:
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")

# --- Templates: apuntamos explícitamente a app/templates ---
APP_DIR = Path(__file__).resolve().parent.parent        # .../app
TEMPLATES_DIR = APP_DIR / "templates"                   # .../app/templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------- Helpers ----------------
def _get_user_pwd(u: models.User) -> str:
    """Devuelve el hash de password sin importar el nombre del campo del modelo."""
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
    """Renderiza el login HTML; si falta el template, entrega un fallback mínimo."""
    try:
        return templates.TemplateResponse("login.html", {"request": request, "next": next})
    except TemplateNotFound:
        inline = f"""
        <!doctype html><html lang="es"><meta charset="utf-8">
        <title>Login | AlertTrail</title>
        <body style="font-family:system-ui;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#f6f7fb;margin:0">
          <form method="post" action="/auth/login/web" style="background:#fff;max-width:420px;width:100%;padding:28px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.06)">
            <h1 style="font-size:20px;margin:0 0 14px">Ingresar a AlertTrail</h1>
            <label for="email" style="display:block;font-size:14px;margin:10px 0 6px">Email</label>
            <input id="email" name="email" type="email" required style="width:100%;padding:12px 14px;border:1px solid #dfe3ea;border-radius:10px;font-size:15px">
            <label for="password" style="display:block;font-size:14px;margin:10px 0 6px">Contraseña</label>
            <input id="password" name="password" type="password" required style="width:100%;padding:12px 14px;border:1px solid #dfe3ea;border-radius:10px;font-size:15px">
            <input type="hidden" name="next" value="{next or '/dashboard'}">
            <button type="submit" style="margin-top:16px;width:100%;padding:12px 14px;border:0;border-radius:12px;background:#0ea5e9;color:#fff;font-weight:600;font-size:15px;cursor:pointer">Entrar</button>
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
    pwd_hash = get_password_hash(payload.password)
    _set_user_pwd(user, pwd_hash)

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

    token = create_access_token({"sub": str(user.id)})
    return TokenOut(access_token=token)


# ---------------- Login Web (set-cookie + redirect) ----------------
@router.post("/login/web")
def login_web(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(default="/dashboard"),
    db: Session = Depends(get_db),
):
    email_n = _norm_email(email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email_n).first()
    if not user or not verify_password(password, _get_user_pwd(user)):
        try:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Email o password incorrectos", "next": next},
                status_code=400,
            )
        except TemplateNotFound:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token({"sub": str(user.id)})

    # Redirección con 303 para no perder el Set-Cookie
    resp = RedirectResponse(url=(next or "/dashboard"), status_code=303)
    issue_access_cookie(resp, token)
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
        "role": getattr(current_user, "role", "user"),
    }


# ---------------- Logout (UNIFICADO GET/POST) ----------------
@router.api_route("/logout", methods=["GET", "POST"])
def logout():
    # 303 garantiza que el navegador haga GET y respete Set-Cookie
    resp = RedirectResponse(url="/auth/login", status_code=303)

    # Borra cookie host-only (sin Domain)
    resp.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )

    # Y también la variante con Domain, si aplica
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


# ---------------- Debug opcional ----------------
@router.get("/_debug_templates")
def _debug_templates():
    files = []
    try:
        files = [f.name for f in (TEMPLATES_DIR).glob("*.html")]
    except Exception:
        pass
    return {"templates_dir": str(TEMPLATES_DIR), "exists": Path(TEMPLATES_DIR).exists(), "files": files}

@router.get("/_debug_cookies")
def _debug_cookies(request: Request):
    keys = []
    if "cookie" in request.headers:
        raw = request.headers.get("cookie", "")
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        for p in parts:
            k = p.split("=", 1)[0].strip()
            if k and k not in keys:
                keys.append(k)
    return {"cookies_presentes": keys}
