# app/routers/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from sqlalchemy import func

from app.database import get_db
from app import models
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,
    get_current_user_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------- Templates ----------------
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---------------- Schemas ----------------
class RegisterIn(BaseModel):
    name: str | None = None
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

# ---------------- Helpers ----------------
def _get_user_password_hash(u: models.User) -> str:
    # Soporta modelos con password_hash o hashed_password
    return getattr(u, "password_hash", None) or getattr(u, "hashed_password", "") or ""

def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        # domain="alerttrail.com",  # descomenta si API/Front van en dominios distintos
        max_age=60 * 60 * 24 * 7,  # 7 días
    )

# =========================================================
# Login HTML (GET) — muestra formulario
# =========================================================
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# =========================================================
# Login JSON (POST) — para Swagger/Postman
# =========================================================
@router.post("/login", response_model=dict)
def login_json(payload: LoginIn, db: Session = Depends(get_db)):
    email_norm = payload.email.strip().lower()
    user = (
        db.query(models.User)
        .filter(func.lower(models.User.email) == email_norm)
        .first()
    )
    if not user or not verify_password(payload.password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_access_token_from_sub(user.email)
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, token)
    return resp

# =========================================================
# Login desde formulario web (POST del HTML)
# =========================================================
@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(func.lower(models.User.email) == email.lower()).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    _set_cookie(resp, token)
    return resp

# =========================================================
# Logout (borra cookie) — GET y POST
# =========================================================
@router.get("/logout")
def logout_get():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    return resp

@router.post("/logout")
def logout_post():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    return resp

# =========================================================
# Me (requiere cookie)
# =========================================================
@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "name": getattr(current, "name", ""),
        "email": getattr(current, "email", ""),
        "plan": getattr(current, "plan", "FREE"),
    }

# =========================================================
# Register API (JSON) — opcional si ya tenés /register en main
# =========================================================
@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email_norm = data.email.strip().lower()
    exists = (
        db.query(models.User)
        .filter(func.lower(models.User.email) == email_norm)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")

    user = models.User(email=email_norm, name=(data.name or ""), plan="FREE")
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):
        user.password_hash = pwd
    if hasattr(user, "hashed_password"):
        user.hashed_password = pwd
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "name": user.name, "plan": getattr(user, "plan", "FREE")}

# =========================================================
# Emergencia: resetear/crear admin desde ENV y secret
# =========================================================
@router.post("/_force_admin_reset", include_in_schema=True)
def _force_admin_reset(
    secret: str = Query(..., description="Debe coincidir con ADMIN_SETUP_SECRET (o JWT_SECRET)"),
    db: Session = Depends(get_db),
):
    """
    Crea/actualiza el admin usando env:
      ADMIN_EMAIL, ADMIN_PASS, ADMIN_NAME
    Protegido por ADMIN_SETUP_SECRET (o JWT_SECRET). Eliminar luego de usar.
    """
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")

    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASS")
    name = os.getenv("ADMIN_NAME", "Admin")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Faltan ADMIN_EMAIL o ADMIN_PASS")

    pwd_hash = get_password_hash(password)
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        if hasattr(user, "hashed_password"):
            user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):
            user.password_hash = pwd_hash
        if hasattr(user, "is_admin"):  user.is_admin = True
        if hasattr(user, "is_active"): user.is_active = True
        if not getattr(user, "name", "") and name:
            user.name = name
        action = "actualizado"
    else:
        user = models.User(email=email, name=name)
        if hasattr(user, "hashed_password"):
            user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):
            user.password_hash = pwd_hash
        if hasattr(user, "is_admin"):  user.is_admin = True
        if hasattr(user, "is_active"): user.is_active = True
        db.add(user)
        action = "creado"

    db.commit()
    return {"ok": True, "admin": email, "action": action}

# =========================================================
# Debug de autenticación (temporal)
# =========================================================
@router.get("/_debug_auth", include_in_schema=True)
def _debug_auth(
    email: EmailStr,
    password: str,
    secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"),
    db: Session = Depends(get_db),
):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")

    users = (
        db.query(models.User)
        .filter(func.lower(models.User.email) == email.lower())
        .all()
    )
    out = []
    for u in users:
        hp = getattr(u, "hashed_password", None)
        ph = getattr(u, "password_hash", None)
        ok_h = verify_password(password, hp) if hp else None
        ok_p = verify_password(password, ph) if ph else None
        out.append({
            "id": u.id,
            "email": u.email,
            "hashed_password_len": len(hp or "") if hp else None,
            "password_hash_len": len(ph or "") if ph else None,
            "verify_hashed_password": ok_h,
            "verify_password_hash": ok_p,
        })
    return {"count": len(users), "results": out}
