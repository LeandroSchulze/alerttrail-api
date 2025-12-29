# app/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

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
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()
COOKIE_HTTPONLY = os.getenv("COOKIE_HTTPONLY", "1").lower() in ("1", "true", "yes", "on")

# 🔐 bcrypt_sha256 evita el límite de 72 bytes y bugs de bcrypt en Render
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# =============================================================================
# Passwords
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_and_rehash(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    try:
        ok, new_hash = pwd_context.verify_and_update(plain_password, hashed_password)
        return ok, new_hash
    except Exception:
        return False, None

# =============================================================================
# Tokens
# =============================================================================

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

# =============================================================================
# Cookie helpers
# =============================================================================

def _first(v: str | None) -> str | None:
    return v.split(",")[0].strip() if v else None


def _host_no_port(host: str | None) -> str | None:
    if not host:
        return None
    return host.split(":")[0].lower()


def _cookie_domain_from_host(host: str | None) -> str | None:
    host = _host_no_port(host)
    if not host:
        return None
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return None
    if host.replace(".", "").isdigit():
        return None
    parts = host.split(".")
    if len(parts) < 2:
        return None
    return "." + ".".join(parts[-2:])


def _is_https(request: Request | None) -> bool:
    if not request:
        return False
    proto = _first(request.headers.get("x-forwarded-proto"))
    if proto:
        return proto == "https"
    try:
        return request.url.scheme == "https"
    except Exception:
        return False


def _best_host(request: Request | None) -> str | None:
    if not request:
        return None
    return _host_no_port(
        _first(
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
        )
    )

# =============================================================================
# Cookies
# =============================================================================

def issue_access_cookie(response: Response, token: str, request: Request | None = None) -> None:
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    secure = COOKIE_SECURE or _is_https(request)
    samesite = COOKIE_SAMESITE if COOKIE_SAMESITE in ("lax", "strict", "none") else "lax"

    if samesite == "none":
        secure = True

    domain = COOKIE_DOMAIN or _cookie_domain_from_host(_best_host(request))

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=secure,
        httponly=COOKIE_HTTPONLY,
        samesite=samesite,
        domain=domain,
    )


def clear_access_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")

    if COOKIE_DOMAIN:
        response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

    domain = _cookie_domain_from_host(_best_host(request))
    if domain:
        response.delete_cookie(COOKIE_NAME, path="/", domain=domain)

# =============================================================================
# Current user
# =============================================================================

def get_token_from_request(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    auth = request.headers.get("authorization")
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


def get_current_user_cookie_optional(request: Request) -> dict[str, Any] | None:
    token = get_token_from_request(request)
    if not token:
        return None
    try:
        return decode_token(token)
    except JWTError:
        return None


def get_current_user_id(request: Request) -> int:
    payload = get_current_user_cookie(request)
    try:
        return int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

# =============================================================================
# Billing compat
# =============================================================================

def normalize_user_plan(db, user) -> None:
    try:
        now = datetime.now(timezone.utc)
        exp = getattr(user, "pro_expires_at", None)
        is_pro = getattr(user, "is_pro", False)

        active = bool(is_pro) or (exp and exp > now)

        if hasattr(user, "plan"):
            user.plan = "PRO" if active else "FREE"
        if hasattr(user, "is_pro"):
            user.is_pro = active

        db.add(user)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
