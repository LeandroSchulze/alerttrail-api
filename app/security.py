# app/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request, Response
from jose import JWTError, jwt
from passlib.context import CryptContext

# =============================================================================
# Config
# =============================================================================

JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_PLEASE")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None  # e.g. ".alerttrail.com"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # "lax"|"strict"|"none"
COOKIE_HTTPONLY = os.getenv("COOKIE_HTTPONLY", "1").lower() in ("1", "true", "yes", "on")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Helpers
# =============================================================================

def _bcrypt72(secret: Any) -> bytes:
    """
    bcrypt limita el input a 72 BYTES.
    Esta función SIEMPRE devuelve bytes <= 72 para hash/verify (sin excepciones).
    """
    if secret is None:
        s = ""
    elif isinstance(secret, bytes):
        b = secret
        return b[:72]
    else:
        s = secret if isinstance(secret, str) else str(secret)

    b = s.encode("utf-8")
    return b[:72]


def _cookie_domain_from_host(host: str) -> Optional[str]:
    if not host:
        return None

    host = host.strip().lower()
    if "," in host:
        host = host.split(",", 1)[0].strip()
    if ":" in host:
        host = host.split(":", 1)[0].strip()

    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return None
    if host.count(".") < 1:
        return None

    parts = host.split(".")
    if len(parts) < 2:
        return None
    return "." + ".".join(parts[-2:])


def _proxy_safe_host_and_proto(request: Request) -> tuple[Optional[str], Optional[str]]:
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("X-Forwarded-Host")
        or request.headers.get("host")
        or request.headers.get("Host")
    )
    if host:
        host = host.split(",", 1)[0].strip().lower()
        if ":" in host:
            host = host.split(":", 1)[0].strip() or None
    else:
        try:
            host = (request.url.hostname or "").lower() or None
        except Exception:
            host = None

    proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
    if proto:
        proto = proto.split(",", 1)[0].strip().lower()
    else:
        try:
            proto = request.url.scheme.lower()
        except Exception:
            proto = None

    return host, proto


# =============================================================================
# Passwords
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # usamos bytes <=72
        return pwd_context.verify(_bcrypt72(plain_password), hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    # usamos bytes <=72
    return pwd_context.hash(_bcrypt72(password))


def verify_and_rehash(plain_password: str, hashed_password: str) -> tuple[bool, Optional[str]]:
    try:
        ok, new_hash = pwd_context.verify_and_update(_bcrypt72(plain_password), hashed_password)
        return ok, new_hash
    except Exception:
        return False, None


# =============================================================================
# Tokens
# =============================================================================

def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# =============================================================================
# Cookies
# =============================================================================

def issue_access_cookie(response: Response, token: str, request: Optional[Request] = None) -> None:
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    secure = COOKIE_SECURE
    samesite = COOKIE_SAMESITE
    httponly = COOKIE_HTTPONLY

    host: Optional[str] = None
    proto: Optional[str] = None
    if request is not None:
        host, proto = _proxy_safe_host_and_proto(request)
        if proto == "https":
            secure = True

    # SameSite=None requiere Secure=True en browsers modernos
    if samesite == "none":
        secure = True

    domain = COOKIE_DOMAIN
    if not domain and host:
        domain = _cookie_domain_from_host(host)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=secure,
        httponly=httponly,
        samesite=samesite,
        domain=domain or None,
    )


def clear_access_cookie(response: Response, request: Optional[Request] = None) -> None:
    domain = COOKIE_DOMAIN
    if not domain and request is not None:
        host, _ = _proxy_safe_host_and_proto(request)
        if host:
            domain = _cookie_domain_from_host(host)
    response.delete_cookie(COOKIE_NAME, path="/", domain=domain or None)


def get_token_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()

    return None


def get_current_user_cookie(request: Request) -> dict[str, Any]:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        return decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


def get_current_user_cookie_optional(request: Request) -> Optional[dict[str, Any]]:
    token = get_token_from_request(request)
    if not token:
        return None
    try:
        return decode_token(token)
    except JWTError:
        return None


def get_current_user_id(request: Request) -> int:
    payload = get_current_user_cookie(request)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token inválido")
    try:
        return int(sub)
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")


# =============================================================================
# Billing helpers (compat)
# =============================================================================

def normalize_user_plan(db, user) -> None:
    try:
        plan = getattr(user, "plan", None)
        is_pro = getattr(user, "is_pro", None)
        exp = getattr(user, "pro_expires_at", None)

        now = datetime.now(timezone.utc)

        if exp is not None:
            try:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        active_pro = bool(is_pro) or (exp is not None and exp > now)

        if hasattr(user, "plan"):
            if active_pro:
                user.plan = "PRO"
            else:
                if plan is None:
                    user.plan = "FREE"

        if hasattr(user, "is_pro"):
            user.is_pro = bool(active_pro)

        db.add(user)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
