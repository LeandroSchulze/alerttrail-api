# app/security.py
import os
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.models import User

# ---- Config ----
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")  # ¡poné un secreto real en Render!
JWT_ALG = "HS256"

COOKIE_NAME = "access_token"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" o "none"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN")  # opcional (tu dominio)

# Hash PBKDF2
ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "240000"))
SALT = os.getenv("PASSWORD_SALT", "alerttrail_salt")

# ---- Password hashing helpers ----
def _pbkdf2_sha256(password: str, salt: str, iterations: int) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return base64.b64encode(dk).decode()

def get_password_hash(password: str) -> str:
    return f"pbkdf2_sha256${ITERATIONS}${SALT}${_pbkdf2_sha256(password, SALT, ITERATIONS)}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        scheme, iters, salt, digest = hashed.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        calc = _pbkdf2_sha256(password, salt, int(iters))
        return hmac.compare_digest(calc, digest)
    except Exception:
        return False

# ---- JWT helpers ----
def create_access_token(subject: str, expires_delta: timedelta = timedelta(days=7)) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": int((now + expires_delta).timestamp())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None

# ---- Cookie helpers ----
def issue_access_cookie(response: Response, token: str, max_age: int = 7 * 24 * 3600) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path="/",
    )

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

# ---- Current user from cookie ----
def get_current_user_cookie(request: Request, db: Session) -> Optional[User]:
    """
    Lee el JWT de la cookie 'access_token', lo decodifica y devuelve el User.
    Devuelve None si no hay cookie o el token es inválido/expirado.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    data = decode_token(token)
    if not data:
        return None

    email = data.get("sub")
    if not email:
        return None

    user = db.query(User).filter(User.email == email).first()
    return user
