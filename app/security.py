# app/security.py
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status
from starlette.responses import Response
from jose import jwt, JWTError
from passlib.context import CryptContext


# =========================
# Password hashing
# =========================
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],  # compat con hashes viejos y nuevos
    deprecated="auto",
)

def get_password_hash(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password inválido")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def verify_and_rehash(plain_password: str, hashed_password: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica la contraseña y, si el hash está desactualizado, retorna (True, new_hash).
    Si no hay que rehashear, retorna (True, None). Si falla, (False, None).
    """
    if not plain_password or not hashed_password:
        return False, None
    try:
        ok = pwd_context.verify(plain_password, hashed_password)
        if not ok:
            return False, None
        if pwd_context.needs_update(hashed_password):
            return True, pwd_context.hash(plain_password)
        return True, None
    except Exception:
        return False, None


# =========================
# JWT
# =========================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": _now_utc()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado") from e


# =========================
# Cookies
# =========================
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

def _env_bool(var_name: str, default: bool) -> bool:
    v = os.getenv(var_name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y")

COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" | "strict" | "none"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)       # e.g. ".tudominio.com" o None
COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(60 * 60 * 24 * 7)))  # 7 días

def issue_access_cookie(response: Response, token: str, max_age: Optional[int] = None) -> None:
    samesite = (COOKIE_SAMESITE or "lax").lower()
    secure = COOKIE_SECURE or (samesite == "none")
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age if max_age is not None else COOKIE_MAX_AGE,
        expires=max_age if max_age is not None else COOKIE_MAX_AGE,
        path="/",
        domain=COOKIE_DOMAIN,
        secure=secure,
        httponly=True,
        samesite=samesite,
    )

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)


# =========================
# Helpers de request
# =========================
def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    """
    Devuelve el payload del JWT (p.ej. {"sub": "...", "email": "..."}).
    Si necesitás el objeto User real, hacé el lookup en la vista usando 'sub'.
    """
    token = get_token_from_request(request)
    payload = decode_token(token)
    if "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto (sub)")
    return payload
