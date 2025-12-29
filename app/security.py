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

# If set, used as-is. If empty, we compute from request host (proxy-safe).
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None  # e.g. ".alerttrail.com"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # "lax"|"strict"|"none"
COOKIE_HTTPONLY = os.getenv("COOKIE_HTTPONLY", "1").lower() in ("1", "true", "yes", "on")

# IMPORTANT:
# - Using bcrypt_sha256 avoids the bcrypt 72-byte limitation AND passlib/bcrypt backend issues seen on Render.
# - This prevents crashes like: ValueError: password cannot be longer than 72 bytes
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
    """Verify password and (optionally) return a rehashed version if needed."""
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

def _first_header_value(v: str | None) -> str | None:
    if not v:
        return None
    # X-Forwarded-Host / Proto may contain multiple values: "a,b"
    v = v.split(",")[0].strip()
    return v or None


def _host_without_port(host: str | None) -> str | None:
    if not host:
        return None
    host = host.strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0].strip()
    return host or None


def _cookie_domain_from_host(host: str | None) -> str | None:
    """
    Given "www.alerttrail.com" -> ".alerttrail.com"
    Given "alerttrail.com"     -> ".alerttrail.com"
    Given "localhost" / IP     -> None
    """
    host = _host_without_port(host)
    if not host:
        return None

    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return None

    # naive IP check
    if host.replace(".", "").isdigit():
        return None

    parts = host.split(".")
    if len(parts) < 2:
        return None

    # NOTE: for most custom domains this is fine
    return "." + ".".join(parts[-2:])


def _is_https_request(request: Request | None) -> bool:
    if request is None:
        return False

    xf_proto = _first_header_value(
        request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
    )
    if xf_proto:
        return xf_proto.lower() == "https"

    try:
        return (request.url.scheme or "").lower() == "https"
    except Exception:
        return False


def _best_host_for_cookie(request: Request | None) -> str | None:
    if request is None:
        return None

    host = _first_header_value(
        request.headers.get("x-forwarded-host")
        or request.headers.get("X-Forwarded-Host")
        or request.headers.get("host")
        or request.headers.get("Host")
    )
    host = _host_without_port(host)
    if host:
        return host

    try:
        return _host_without_port(request.url.hostname)
    except Exception:
        return None


# =============================================================================
# Cookies
# =============================================================================

def issue_access_cookie(
    response: Response,
    token: str,
    request: Request | None = None,
) -> None:
    """Set the auth cookie in a proxy-safe way.

    Fixes login-loop caused by:
    - cookie set as host-only on www, then user navigates to apex (or another domain)
    - wrong domain computed behind proxy
    - SameSite=None without Secure (browser silently drops cookie)
    """
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Decide secure based on env OR https request
    secure = COOKIE_SECURE or _is_https_request(request)

    samesite = (COOKIE_SAMESITE or "lax").lower()
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"

    # Browsers require Secure when SameSite=None
    if samesite == "none":
        secure = True

    httponly = COOKIE_HTTPONLY

    # Determine domain
    host = _best_host_for_cookie(request)
    domain = COOKIE_DOMAIN
    if not domain:
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


def clear_access_cookie(response: Response, request: Request | None = None) -> None:
    """Delete auth cookie in ALL likely variants to avoid duplicated cookies causing auth loops."""
    # 1) host-only
    response.delete_cookie(COOKIE_NAME, path="/")

    # 2) configured domain (if any)
    if COOKIE_DOMAIN:
        response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

    # 3) computed base domain from request host (www/apex)
    host = _best_host_for_cookie(request)
    computed = _cookie_domain_from_host(host)
    if computed:
        response.delete_cookie(COOKIE_NAME, path="/", domain=computed)


def get_token_from_request(request: Request) -> str | None:
    # 1) Cookie
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    # 2) Authorization: Bearer
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()

    return None


def get_current_user_cookie(request: Request) -> dict[str, Any]:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        payload = decode_token(token)
        return payload
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
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token inválido")
    try:
        return int(sub)
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")


# =============================================================================
# Billing helpers (kept for backwards-compat imports)
# =============================================================================

def normalize_user_plan(db, user) -> None:
    """
    Backwards-compat shim:
    Some routers import normalize_user_plan from app.security.
    """
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
