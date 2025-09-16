# app/routers/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app import models
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,
    get_current_user_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])  # ← SIN dependencies aquí

# -------------------------------------------------
# Templates
# -------------------------------------------------
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# -------------------------------------------------
# Schemas (fallback si no existen en app.schemas)
# -------------------------------------------------
try:
    from app.schemas import RegisterIn, LoginIn  # opcional
except Exception:
    class RegisterIn(BaseModel):
        name: str | None = None
        email: EmailStr
        password: str

    class LoginIn(BaseModel):
        email: EmailStr
        password: str

# -------------------------------------------------
# Helpers
# -------------------------------------------------
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
        max_age=60 * 60 * 24 * 7,  # 7 días
    )

# -------------------------------------------------
# Login HTML (form)
# -------------------------------------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# -------------------------------------------------
# Login JSON (Swagger/Postman) — declara request body
# -------------------------------------------------
@router.post("/login")
def login_json(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_access_token_from_sub(user.email)
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, token)
    return resp

# -------------------------------------------------
# Login de formulario (POST desde /auth/login HTML)
# -------------------------------------------------
@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        # devolvemos 401 para que el template pueda mostrar error si querés
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_access_token_from_sub(user.email)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    _set_cookie(resp, token)
    return resp

# -------------------------------------------------
# Logout (borra cookie)
# -------------------------------------------------
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

# -------------------------------------------------
# Me (requiere cookie)
# -------------------------------------------------
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

# -------------------------------------------------
# Register (público)
# -------------------------------------------------
@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.email == data.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")

    user = models.User(email=data.email, name=(data.name or ""), plan="FREE")
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):
        user.password_hash = pwd
    if hasattr(user, "hashed_password"):
        user.hashed_password = pwd

    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "name": user.name, "plan": getattr(user, "plan", "FREE")}
