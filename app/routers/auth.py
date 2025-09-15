# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app import models
from app.schemas import RegisterIn, LoginIn, UserOut  # si no usás UserOut/LoginIn, no pasa nada
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,
    issue_access_cookie,
    clear_access_cookie,
    get_current_user_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def _get_user_password_hash(u: models.User) -> str:
    return getattr(u, "password_hash", None) or getattr(u, "hashed_password", "")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Acepta JSON o Form. Si es Form, redirige al /dashboard con cookie."""
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

    token = create_access_token_from_sub(user.email)

    if is_json:
        issue_access_cookie(response, token)
        return {"access_token": token, "token_type": "bearer"}
    else:
        resp = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(resp, token)
        return resp

@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    resp = Response(status_code=303); resp.headers["Location"] = "/dashboard"
    issue_access_cookie(resp, token)
    return resp

@router.get("/logout")
def logout_get():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp

@router.post("/logout")
def logout_post():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp

@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {"name": current.name, "email": current.email, "plan": getattr(current, "plan", "FREE")}

@router.post("/register", response_model=UserOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.email == data.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    user = models.User(email=data.email, name=data.name, plan="FREE")
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):   user.password_hash = pwd
    if hasattr(user, "hashed_password"): user.hashed_password = pwd
    db.add(user); db.commit(); db.refresh(user)
    return user
