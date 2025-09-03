from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from .config import settings
from .database import SessionLocal
from .models import User, PlanEnum

# Registrar el esquema de seguridad en OpenAPI.
# IMPORTANTE: usar ruta relativa SIN “/” inicial y auto_error=False para que Swagger no pinche
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

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
    cookie = request.cookies.get("access_token")
    if cookie:
        return cookie
    return None

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    bearer_token: str | None = Depends(oauth2_scheme)
) -> User:
    # 1) Header/Cookie  2) Bearer de Swagger (si existe)
    token = _extract_token(request) or bearer_token
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
