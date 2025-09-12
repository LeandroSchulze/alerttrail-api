# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas import RegisterIn, LoginIn, UserOut
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,
    issue_access_cookie,
    COOKIE_NAME,
    get_current_user_cookie,   # para /me leyendo la cookie
)

router = APIRouter()


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
        plan="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", tags=["auth"])
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Login por JSON. Devuelve token y setea cookie HTTPOnly."""
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    token = create_access_token_from_sub(user.email)
    issue_access_cookie(response, token)  # set-cookie: access_token=...
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
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=UserOut, tags=["auth"])
def me(current: models.User = Depends(get_current_user_cookie)):
    """Obtiene el usuario actual leyendo el JWT de la cookie."""
    return current
