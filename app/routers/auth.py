# app/routers/auth.py
import os
import re  # <-- agregado
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
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
    # Importamos las constantes de cookie para NO desincronizarnos
    COOKIE_NAME, COOKIE_PATH, COOKIE_HTTPONLY, COOKIE_SECURE, COOKIE_SAMESITE,
)

# COOKIE_DOMAIN puede no existir en algunas versiones; hacemos fallback elegante
try:
    from app.security import COOKIE_DOMAIN  # type: ignore
except Exception:  # pragma: no cover
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")

# Templates (opcional: si no usás login HTML, esto no molesta)
try:
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")
except Exception:  # pragma: no cover
    templates = None

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
        # Último recurso: usamos un nombre estándar
        setattr(u, "hashed_password", pwd_hash)

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()


# ---------------- Schemas (mínimos) ----------------
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


# ---------------- Vistas HTML opcionales ----------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = Query(default="/dashboard")):
    if not templates:
        return PlainTextResponse("Templates no configurados. Usa /auth/login/web.", status_code=200)
    return templates.TemplateResponse("login.html", {"request": request, "next": next})


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
        if templates:
            # devolvemos la misma página con error
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Email o password incorrectos", "next": next},
                status_code=400,
            )
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token({"sub": str(user.id)})
    # Redirigimos con 303 para no perder Set-Cookie
    resp = RedirectResponse(url=(next or "/dashboard"), status_code=303)
    issue_access_cookie(resp, token)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------- Yo (sesión por cookie) ----------------
@router.get("/me")
def me(current_user=Depends(get_current_user_cookie)):
    if not current_user:
        raise HTTPException(status_code=401, detail="No autenticado")
    # devolvemos campos básicos
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

    # Y también borra la variante con Domain, si aplica
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


# ---------------- Debug opcional (no exponer en prod) ----------------
@router.get("/_debug_cookies")
def _debug_cookies(request: Request):
    # No mostramos el token, solo keys presentes
    keys = []
    if "cookie" in request.headers:
        raw = request.headers.get("cookie", "")
        # mostramos nombres de cookies (antes del '=')
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        for p in parts:
            k = p.split("=", 1)[0].strip()
            if k and k not in keys:
                keys.append(k)
    return {"cookies_presentes": keys}
