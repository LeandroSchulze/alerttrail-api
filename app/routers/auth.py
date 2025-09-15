# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app import models
from app.schemas import RegisterIn, LoginIn, UserOut
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,  # ver alias en security.py si no existe
    issue_access_cookie,
    COOKIE_NAME,
    get_current_user_cookie,   # depende de Request y db
)

# ✅ Prefijo para que las rutas queden en /auth/*
router = APIRouter(prefix="/auth", tags=["auth"])

# Templates (usa app/templates por defecto)
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    """Formulario de login. Si ya está logueado, va al dashboard."""
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login", tags=["auth"])
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Login por JSON. Devuelve token y setea cookie HTTPOnly."""
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    issue_access_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}

@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Login desde formulario HTML. Redirige a /dashboard con cookie seteada."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    resp = Response(status_code=303)
    resp.headers["Location"] = "/dashboard"
    issue_access_cookie(resp, token)
    return resp

@router.post("/logout", tags=["auth"])
def logout(response: Response):
    """Elimina la cookie de sesión."""
    response.delete_cookie(COOKIE_NAME, path="/")  # mismo path que se usó al setear
    return {"ok": True}

# 🔧 saco response_model para evitar choque cuando no hay cookie
@router.get("/me", tags=["auth"])
def me(request: Request, db: Session = Depends(get_db)):
    """Obtiene el usuario actual leyendo el JWT de la cookie."""
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "name": current.name,
        "email": current.email,
        "plan": getattr(current, "plan", "FREE"),
    }

@router.post("/register", response_model=UserOut, tags=["auth"])
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Crea un usuario FREE."""
    exists = db.query(models.User).filter(models.User.email == data.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    user = models.User(
        email=data.email,
        name=data.name,
        password_hash=get_password_hash(data.password),
        plan="FREE",  # mayúsculas para que el badge coincida
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
