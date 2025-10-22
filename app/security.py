# app/security.py
import os
import hmac
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Annotated

import jwt
from fastapi import HTTPException, status, Request, Depends
from fastapi.responses import Response
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import User
from app.database import get_db

# ================== Config ==================
JWT_SECRET = os.getenv("JWT_SECRET") or None
if not JWT_SECRET or JWT_SECRET.strip().lower() in {"changeme", "change-me", "secret", "123", "none"}:
    raise RuntimeError("JWT_SECRET no configurado de forma segura en entorno de ejecución")

ALGO = "HS256"
TOKEN_TTL_MIN = int(os.getenv("TOKEN_TTL_MIN", "60"))  # 60 min por defecto

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
COOKIE_HTTPONLY = True
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"   # en prod: true
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")                   # "Lax" o "None"

# CSRF
CSRF_COOKIE = os.getenv("CSRF_COOKIE", "csrftoken")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ================== Utilidades ==================
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _secure_compare(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except Exception:
        return False

# ================== Password hashing ==================
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

# ================== JWT helpers ==================
def _encode(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGO)

def _decode(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGO])

def issue_access_cookie(response: Response, claims: Dict[str, Any]) -> str:
    """Genera JWT con expiración y lo setea en cookie HttpOnly."""
    exp = _utc_now() + timedelta(minutes=TOKEN_TTL_MIN)
    payload = {**claims, "exp": exp}
    token = _encode(payload)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_MIN * 60,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )
    return token

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return _decode(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

def get_current_user_cookie(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token")
    data = decode_token(token)
    uid = data.get("user_id") or data.get("uid") or data.get("sub")
    if uid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")
    user = db.get(User, int(uid))  # SQLAlchemy 2.x friendly
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    return user

# ================== CSRF (para formularios HTML) ==================
def issue_csrf(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,  # legible por JS/form
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    return token

async def validate_csrf(request: Request):
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.headers.get("X-CSRF-Token")
    if not sent:
        # si es form-urlencoded o multipart, intentamos leer del form
        try:
            form = await request.form()
            sent = form.get("csrf_token")
        except Exception:
            sent = None
    cookie = request.cookies.get(CSRF_COOKIE)
    if not sent or not cookie or not _secure_compare(sent, cookie):
        raise HTTPException(status_code=403, detail="CSRF token inválido")

# ================== Debug helpers opcionales ==================
def _debug_cookie_flags() -> Dict[str, Any]:
    return {
        "COOKIE_NAME": COOKIE_NAME,
        "COOKIE_HTTPONLY": COOKIE_HTTPONLY,
        "COOKIE_SECURE": COOKIE_SECURE,
        "COOKIE_SAMESITE": COOKIE_SAMESITE,
        "COOKIE_PATH": COOKIE_PATH,
        "TOKEN_TTL_MIN": TOKEN_TTL_MIN,
    }
