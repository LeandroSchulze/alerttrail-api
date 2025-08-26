from fastapi import Depends, HTTPException, status, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from .config import settings
from .database import SessionLocal
from .models import User, PlanEnum

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # fallback: cookie seteada por /auth/login_web
    cookie = request.cookies.get("access_token")
    if cookie:
        return cookie
    return None

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id: int = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

def require_pro(user: User = Depends(get_current_user)) -> User:
    if user.plan != PlanEnum.PRO:
        raise HTTPException(status_code=402, detail="Función disponible para el plan Pro.")
    return user
b) app/routers/auth.py (agregar endpoints web)
Agregá después de los existentes:

python
Copiar
Editar
from fastapi.responses import RedirectResponse
from fastapi import Form
from datetime import timedelta
from ..config import settings
from ..auth import create_access_token, verify_password
from ..models import User

@router.post("/login_web")
def login_web(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = create_access_token({"sub": str(user.id)}, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, max_age=60*60*24, samesite="lax")
    return resp

@router.post("/logout_web")
def logout_web():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("access_token")
    return resp