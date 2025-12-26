# app/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import Request, HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext

# -----------------------------------------------------------------------------
# JWT
# -----------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# -----------------------------------------------------------------------------
# Password hashing
# -----------------------------------------------------------------------------
# Mantenemos ambos esquemas para verificar hashes viejos (bcrypt)
# pero para crear hashes nuevos usamos pbkdf2_sha256 para evitar el límite de 72 bytes de bcrypt.
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    # Usamos pbkdf2_sha256 para evitar:
    # - límite de 72 bytes de bcrypt
    # - problemas de backend bcrypt/passlib en algunos entornos
    return pwd_context.hash(password, scheme="pbkdf2_sha256")

# -----------------------------------------------------------------------------
# Cookies
# -----------------------------------------------------------------------------

COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "access_token")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" funciona bien para web normal
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None

def _cookie_domain_from_host(host: str | None) -> Optional[str]:
    if not host:
        return None
    host = host.split(":")[0].strip().lower()
    if host in ("localhost", "127.0.0.1"):
        return None
    # dominio base simple: www.alerttrail.com -> alerttrail.com
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host

def issue_access_cookie(response, token: str, request: Optional[Request] = None) -> None:
    domain = COOKIE_DOMAIN
    if domain is None and request is not None:
        domain = _cookie_domain_from_host(request.headers.get("host"))

    # En Render/Proxy, el scheme puede venir como http. Permitimos override si hace falta.
    force_secure = os.getenv("FORCE_COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
    secure = force_secure or (request is not None and request.url.scheme == "https")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=domain,
    )

def clear_access_cookie(response, request: Optional[Request] = None) -> None:
    domain = COOKIE_DOMAIN
    if domain is None and request is not None:
        domain = _cookie_domain_from_host(request.headers.get("host"))

    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=domain,
    )

# -----------------------------------------------------------------------------
# Token helpers
# -----------------------------------------------------------------------------

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

# -----------------------------------------------------------------------------
# Current user via cookie
# -----------------------------------------------------------------------------

def get_current_user_cookie_optional(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        return decode_access_token(token)
    except JWTError:
        return None
    except Exception:
        return None

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    payload = get_current_user_cookie_optional(request)
    if not payload:
        raise HTTPException(status_code=401, detail="No autenticado")
    return payload

def get_current_user_id(request: Request) -> int:
    payload = get_current_user_cookie(request)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(sub)

# -----------------------------------------------------------------------------
# Billing plan normalization (optional compatibility)
# -----------------------------------------------------------------------------

def normalize_user_plan(db, user) -> None:
    """
    Mantengo esta función por compatibilidad porque algunos routers la importan.
    Si tu lógica real está en app/security/billing_guard.py, podés seguir usándola desde ahí.
    Esta versión NO pisa PRO -> FREE (evita que se te "rebaje" la cuenta).
    """
    try:
        # Si el usuario ya tiene plan, no lo tocamos.
        if getattr(user, "plan", None):
            return
        # Si no tiene plan, dejamos FREE por default
        if hasattr(user, "plan"):
            user.plan = "FREE"
        db.add(user)
        db.commit()
    except Exception:
        db.rollback()
        # no romper el login por billing
        return
