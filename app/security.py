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
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None  # e.g. ".alerttrail.com"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # "lax"|"strict"|"none"
COOKIE_HTTPONLY = os.getenv("COOKIE_HTTPONLY", "1").lower() in ("1", "true", "yes", "on")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# bcrypt helpers (72 bytes limit)
# =============================================================================

def _truncate_bcrypt_secret(secret: str) -> str:
    """Ensure bcrypt input is <= 72 bytes (bcrypt limitation)."""
    if not isinstance(secret, str):
        secret = str(secret)

    b = secret.encode("utf-8")
    if len(b) <= 72:
        return secret

    out_chars: list[str] = []
    size = 0
    for ch in secret:
        cb = ch.encode("utf-8")
        if size + len(cb) > 72:
            break
        out_chars.append(ch)
        size += len(cb)
    return "".join(out_chars)


# =============================================================================
# Passwords
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_password = _truncate_bcrypt_secret(plain_password)
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    password = _truncate_bcrypt_secret(password)
    return pwd_context.hash(password)


def verify_and_rehash(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    plain_password = _truncate_bcrypt_secret(plain_password)
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
# Cookie domain helpers
# =============================================================================

def _cookie_domain_from_host(host: str) -> str | None:
    """
    Given "www.alerttrail.com" -> ".alerttrail.com"
    Given "alerttrail.com"     -> ".alerttrail.com"
    Given "localhost" / IP     -> None
    """
    if not host:
        return None

    host = host.strip().lower()
    if ":" in host:
        host = host.split(":")[0].strip()

    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return None
    if host.count(".") < 1:
        return None

    parts = host.split(".")
    if len(parts) < 2:
        return None
    return "." + ".".join(parts[-2:])


def _host_from_request(request: Request) -> str | None:
    host_hdr = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("X-Forwarded-Host")
        or request.headers.get("host")
        or request.headers.get("Host")
    )
    if host_hdr:
        host = host_hdr.split(",")[0].strip()
        if ":" in host:
            host = host.split(":")[0].strip()
        return host.lower() or None

    try:
        return (request.url.hostname or "").lower() or None
    except Exception:
        return None


def _is_https(request: Request) -> bool:
    xf_proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
    if xf_proto:
        return xf_proto.split(",")[0].strip().lower() == "https"
    try:
        return (request.url.scheme or "").lower() == "https"
    except Exception:
        return False


# =============================================================================
# Cookies
# =============================================================================

def issue_access_cookie(response: Response, token: str, request: Request | None = None) -> None:
    """Set the auth cookie (proxy-safe)."""
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    secure = COOKIE_SECURE
    samesite = COOKIE_SAMESITE
    httponly = COOKIE_HTTPONLY

    host: str | None = None
    if request is not None:
        host = _host_from_request(request)
        if _is_https(request):
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


def clear_access_cookie(response: Response, request: Request | None = None) -> None:
    """
    IMPORTANT:
    Borramos TODAS las variantes comunes del cookie para evitar el loop:
      - host-only (domain=None)
      - domain calculado por host (".alerttrail.com")
      - COOKIE_DOMAIN si viene por env
    """
    # 1) host-only
    try:
        response.delete_cookie(COOKIE_NAME, path="/", domain=None)
    except Exception:
        pass

    # 2) domain explícito por env
    if COOKIE_DOMAIN:
        try:
            response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)
        except Exception:
            pass

    # 3) domain calculado por request (proxy-safe)
    if request is not None:
        try:
            host = _host_from_request(request) or ""
            dom = _cookie_domain_from_host(host)
            if dom:
                response.delete_cookie(COOKIE_NAME, path="/", domain=dom)
        except Exception:
            pass


def _get_cookie_last_value(raw_cookie_header: str, name: str) -> str | None:
    """
    Si el browser manda dos cookies con el mismo nombre,
    tomamos la ÚLTIMA (normalmente es la más nueva).
    """
    if not raw_cookie_header:
        return None

    # Split naive por ';' (suficiente para cookies normales)
    parts = [p.strip() for p in raw_cookie_header.split(";") if p.strip()]
    found: list[str] = []
    prefix = name + "="
    for p in parts:
        if p.startswith(prefix):
            found.append(p[len(prefix):])
    if not found:
        return None
    return found[-1] or None


def get_token_from_request(request: Request) -> str | None:
    # 0) Cookie header raw (maneja duplicados de forma determinística)
    raw = request.headers.get("cookie") or request.headers.get("Cookie") or ""
    v = _get_cookie_last_value(raw, COOKIE_NAME)
    if v:
        return v

    # 1) Fallback: parsed cookies
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
