# app/routers/auth_login.py
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Form
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_password, issue_access_cookie_for_user

# Ajusta este import si tu modelo User está en otro módulo
from app.models import User  # <- si tu User está en app.database o app.schemas, cambia la ruta

router = APIRouter(tags=["auth"])

class LoginIn(BaseModel):
    email: EmailStr
    password: str

@router.post("/auth/login")
def login_api(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.password or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    plan = "PRO" if getattr(user, "is_pro", False) else "FREE"
    issue_access_cookie_for_user(response, user_id=user.id, email=user.email, is_admin=bool(getattr(user, "is_admin", False)), plan=plan)
    return {"ok": True, "user": {"email": user.email, "name": getattr(user, "name", ""), "plan": plan}}

# (opcional) login web por formulario -> redirige al dashboard
@router.post("/auth/login/web")
def login_web(response: Response,
              email: str = Form(...),
              password: str = Form(...),
              db: Session = Depends(get_db)):
    em = email.strip().lower()
    user = db.query(User).filter(User.email == em).first()
    if not user or not verify_password(password, user.password or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    plan = "PRO" if getattr(user, "is_pro", False) else "FREE"
    issue_access_cookie_for_user(response, user_id=user.id, email=user.email, is_admin=bool(getattr(user, "is_admin", False)), plan=plan)
    # Devolvemos JSON simple; si prefieres redirect puro, usa RedirectResponse("/dashboard", 302)
    return {"ok": True, "redirect": "/dashboard"}
