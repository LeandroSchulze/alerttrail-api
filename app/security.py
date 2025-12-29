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

# Si lo seteás en Render a ".alerttrail.com" mejor todavía.
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # lax|strict|none
COOKIE_HTTPONLY = os.getenv("COOKIE_HTTPONLY", "1").lower() in ("1", "true", "yes", "on")

# bcrypt_sha256 => evita límite 72 bytes
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def _first(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return v.split(",")[0].strip() or None


def _host_no_port(host: Optional[str]) -> Optional[str]:
    if not host:
        return None
    host = host.strip()
    if ":" in host:
        host = host.split(":", 1)[0].strip()
    return host.lower() or None


def _is_ip(host: str) -> bool:
    h = host.replace(".", "")
    return h.isdigit()


def _cookie_domain_from_host(host: Optional[str]) -> Optional[str]:
    """
    www.alerttrail.com -> .alerttrail.com
    alerttrail.com     -> .alerttrail.com
    localhost/IP       -> None
    """
    host = _host_no_port(host)
    if not host:
        return None
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return None
    if _is_ip(host):
        return None

    parts = host.split(".")
    if len(parts) < 2:
        return None
    return "." + ".".join(parts[-2:])


def _best_host(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None
    return _host_no_port(
        _first(
            request.headers.get("x-forwarded-host")
            or request.headers.get("X-Forwarded-Host")
            or request.headers.get("host")
            or request.headers.get("Host")
        )
    )


def _is_https(request: Optional[Request]) -> bool:
    if not request:
        return False
    xf_proto = _first(request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto"))
    if xf_proto:
        return xf_proto.lower() == "https"
    try:
        return request.url.scheme == "https"
    except Exception:
        return False


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
# Cookies
# =============================================================================

def issue_access_cookie(response: Response, token: str, request: Request | None = None) -> None:
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    samesite = COOKIE_SAMESITE if COOKIE_SAMESITE in ("lax", "strict", "none") else "lax"
    secure = COOKIE_SECURE or _is_https(request)

    # Si SameSite=None => Secure obligatorio (Chrome)
    if samesite == "none":
        secure = True

    host = _best_host(request)
    domain = COOKIE_DOMAIN or _cookie_domain_from_host(host)

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
    """
    MATA el loop: borra cookie host-only + cookie con domain.
    Render + www/root suelen dejar “fantasmas”.
    """
    # host-only
    response.delete_cookie(COOKIE_NAME, path="/")

    # domain explícito por env
    if COOKIE_DOMAIN:
        response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

    # domain derivado del host real (X-Forwarded-Host)
    host = _best_host(request)
    derived = _cookie_domain_from_host(host)
    if derived:
        response.delete_cookie(COOKIE_NAME, path="/", domain=derived)

    # extra: por si te quedó hardcodeado alguna vez
    response.delete_cookie(COOKIE_NAME, path="/", domain=".alerttrail.com")


def get_token_from_request(request: Request) -> str | None:
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


def normalize_user_plan(db, user) -> None:
    try:
        now = datetime.now(timezone.utc)
        exp = getattr(user, "pro_expires_at", None)
        is_pro = getattr(user, "is_pro", False)

        active = bool(is_pro) or (exp and exp > now)
        if hasattr(user, "plan"):
            user.plan = "PRO" if active else "FREE"
        if hasattr(user, "is_pro"):
            user.is_pro = bool(active)

        db.add(user)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
