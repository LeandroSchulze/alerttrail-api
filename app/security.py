# app/security.py
from datetime import datetime, timedelta
from typing import Optional

import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app import models

# ──────────────────────────────────────────────────────────────────────────────
# Password hashing (PBKDF2)
# ──────────────────────────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# ──────────────────────────────────────────────────────────────────────────────
# JWT helpers
# ──────────────────────────────────────────────────────────────────────────────
COOKIE_NAME = "access_token"

def _expires(minutes: Optional[int] = None) -> datetime:
    settings = get_settings()
    return datetime.utcnow() + timedelta(
        minutes=minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

def create_access_token(data: dict, minutes: int | None = None) -> str:
    """Conserva tu firma original (data dict)."""
    settings = get_settings()
    to_encode = data.copy()
    to_encode.update({"exp": _expires(minutes)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

def create_access_token_from_sub(sub: str, minutes: int | None = None) -> str:
    """Azúcar sintáctico: permite pasar sólo el `sub`."""
    return create_access_token({"sub": sub}, minutes=minutes)

def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

def issue_access_cookie(response: Response, token: str) -> None:
    """Setea cookie HTTPOnly con el JWT."""
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", secure=True
    )

def get_user_from_token(db: Session, token: str) -> Optional[models.User]:
    payload = decode_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    return db.query(models.User).filter(models.User.email == sub).first()

# ──────────────────────────────────────────────────────────────────────────────
# Dependencias de seguridad
# ──────────────────────────────────────────────────────────────────────────────
bearer = HTTPBearer(auto_error=False)

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """Autenticación por header Authorization: Bearer <token> (como ya usabas)."""
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token")
    user = get_user_from_token(db, creds.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return user

def get_current_user_cookie(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    """Autenticación por cookie HTTPOnly (para páginas HTML)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    user = get_user_from_token(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return user
