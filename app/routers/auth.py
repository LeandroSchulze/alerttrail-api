# app/routers/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas import RegisterIn, LoginIn, UserOut  # si no usás UserOut/LoginIn, podés quitarlo
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,
    get_current_user_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])  # <- SIN dependencies aquí

APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def _get_user_password_hash(u: models.User) -> str:
    # Soporta tanto password_hash como hashed_password
    return getattr(u, "password_hash", None) or getattr(u, "hashed_password", "") or ""

# ------------------ Login (HTML) ------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# ------------------ Login (JSON y Form) ------------------
@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    """
    Acepta JSON o Form.
    - JSON: devuelve JSON y setea cookie en la respuesta (ideal para Swagger).
    - Form: redirige a /dashboard y setea cookie (para el login HTML).
    """
    ctype = (request.headers.get("content-type") or "").lower()
    is_json = ctype.startswith("application/json")
    if is_json:
        body = await request.json()
        email = (body or {}).get("email")
        password = (body or {}).get("password")
    else:
        form = await request.form()
        email = form.get("email")
        password = form.get("password")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    # Generamos token con el sub que usa tu Security (email en tu código actual)
    token = create_access_token_from_sub(user.email)

    if is_json:
        # --- Respuesta JSON con cookie robusta
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
            path="/",
        )
        return resp
    else:
        # --- Redirección para login por Form
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
            path="/",
        )
        return resp

# Ruta separada para el form clásico (si tu template lo usa directamente)
@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )
    return resp

# ------------------ Logout ------------------
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

# ------------------ Me ------------------
@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {"name": current.name, "email": current.email, "plan": getattr(current, "plan", "FREE")}

# ------------------ Register (público) ------------------
@router.post("/register", response_model=UserOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.email == data.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    user = models.User(email=data.email, name=data.name, plan="FREE")
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):
        user.password_hash = pwd
    if hasattr(user, "hashed_password"):
        user.hashed_password = pwd
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
