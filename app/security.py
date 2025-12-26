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
    schemes=["pbkdf2_sha256", "bcrypt"],
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
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", os.getenv("JWT_ALG", "HS256"))

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", os.getenv("JWT_EXPIRE_MIN", str(60 * 24 * 7)))
)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": _now_utc()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        ) from e

# =========================
# Cookies
# =========================
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

def _env_bool(var_name: str, default: bool) -> bool:
    v = os.getenv(var_name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")

COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # lax|strict|none
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(60 * 60 * 24 * 7)))

def _cookie_domain_from_host(host: str) -> Optional[str]:
    """
    Hace que la cookie funcione tanto en www.alerttrail.com como en alerttrail.com.
    - www.alerttrail.com / alerttrail.com -> .alerttrail.com
    - localhost/IP -> None
    """
    if not host:
        return None
    host = host.split(":")[0].strip().lower()

    if host in ("localhost",):
        return None

    parts = host.split(".")
    # IP simple
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return None

    if len(parts) < 2:
        return None

    return "." + ".".join(parts[-2:])  # .alerttrail.com

def issue_access_cookie(
    response: Response,
    token: str,
    max_age: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    ma = max_age if max_age is not None else COOKIE_MAX_AGE
    expires_dt = _now_utc() + timedelta(seconds=ma)

    samesite = COOKIE_SAMESITE
    secure = COOKIE_SECURE or (samesite == "none")

    # ✅ FIX: si no hay COOKIE_DOMAIN en env, derivamos del host (www vs root)
    domain = COOKIE_DOMAIN
    if not domain and request is not None:
        domain = _cookie_domain_from_host(request.headers.get("host", ""))

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=ma,
        expires=expires_dt,
        path="/",
        domain=domain,
        secure=secure,
        httponly=True,
        samesite=samesite,
    )

def clear_access_cookie(response: Response, request: Optional[Request] = None) -> None:
    # borrar host-only
    response.delete_cookie(key=COOKIE_NAME, path="/")

    # borrar domain explícito (si existe)
    if COOKIE_DOMAIN:
        response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

    # borrar domain derivado (www/root)
    if request is not None:
        d = _cookie_domain_from_host(request.headers.get("host", ""))
        if d:
            response.delete_cookie(key=COOKIE_NAME, path="/", domain=d)

# =========================
# Request helpers (STRICT)
# =========================
def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    token = get_token_from_request(request)
    payload = decode_token(token)
    if "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto (sub)")
    return payload

# =========================
# Request helpers (OPTIONAL) ✅ para UI/templates
# =========================
def get_current_user_cookie_optional(request: Request) -> Optional[Dict[str, Any]]:
    """
    Para páginas UI: si no hay cookie o token inválido -> None (NO 401).
    """
    try:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not isinstance(payload, dict) or "sub" not in payload:
            return None
        return payload
    except Exception:
        return None

# =========================
# Optional CSRF (compat)
# =========================
async def validate_csrf(request: Request) -> None:
    if os.getenv("CSRF_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
        return
    cookie = request.cookies.get("csrf_token") or ""
    header = request.headers.get("x-csrf") or request.headers.get("x-csrf-token") or ""
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF inválido")
