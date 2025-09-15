# app/security.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Request, Depends, HTTPException
from fastapi.responses import Response
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

# ------------------------------
# Config
# ------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-please")
JWT_ALG = "HS256"
# Duración del token (cookie) – 30 días por defecto
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", str(30 * 24 * 60)))

# Nombre de la cookie donde guardamos el JWT
COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "access_token")

# Detectar si estamos en prod para marcar cookie secure
_IS_PROD = os.getenv("RENDER") is not None or os.getenv("ENV", "").lower() in {"prod", "production"}

# Hash de contraseñas (bcrypt)
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ------------------------------
# Password helpers
# ------------------------------
def get_password_hash(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_ctx.verify(plain_password, password_hash)
    except Exception:
        return False


# ------------------------------
# JWT helpers
# ------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token_from_sub(sub: str, minutes: int = ACCESS_TOKEN_MINUTES, extra: Optional[Dict[str, Any]] = None) -> str:
    """
    Crea un JWT cuyo 'sub' es típicamente el email.
    """
    now = _utcnow()
    payload: Dict[str, Any] = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ------------------------------
# Cookies
# ------------------------------
def issue_access_cookie(response: Response, token: str) -> None:
    """
    Setea la cookie HTTPOnly con el JWT.
    """
    max_age = ACCESS_TOKEN_MINUTES * 60
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=_IS_PROD,      # en prod va Secure
        samesite="lax",
        path="/",
    )


# ------------------------------
# Current user (dependencias)
# ------------------------------
def _user_from_cookie(request: Request, db: Session) -> Optional[models.User]:
    """
    Intenta leer la cookie JWT y traer el usuario. Devuelve None si no hay sesión válida.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    email = payload.get("sub")
    if not email:
        return None

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not getattr(user, "is_active", True):
        return None
    return user


def get_current_user_cookie_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """
    Versión que NO levanta 401. Útil en vistas donde querés redirigir manualmente si no hay sesión.
    """
    return _user_from_cookie(request, db)


def get_current_user_cookie(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    """
    Dependencia que valida sesión leyendo la cookie JWT. Si no hay usuario válido, levanta 401.
    Usala en endpoints que requieren auth.
    """
    user = _user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_current_user_id(
    request: Request,
    db: Session = Depends(get_db),
) -> int:
    """
    Compat para routers que esperan 'get_current_user_id'. Levanta 401 si no hay sesión.
    """
    user = get_current_user_cookie(request, db)
    return int(user.id)
