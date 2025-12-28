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

# Nota:
# Igual vamos a truncar nosotros a 72 bytes SIEMPRE.
# Esta opción ayuda a evitar errores si alguna vez se saltea nuestro helper.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,
)

BCRYPT_MAX_BYTES = 72


def _to_bytes(secret: Any) -> bytes:
    if secret is None:
        return b""
    if isinstance(secret, (bytes, bytearray, memoryview)):
        return bytes(secret)
    # forzar a str y encode UTF-8
    return str(secret).encode("utf-8", errors="ignore")


def _bcrypt72(secret: Any) -> bytes:
    """Return bytes <= 72 for bcrypt (hard limit)."""
    b = _to_bytes(secret)
    if len(b) <= BCRYPT_MAX_BYTES:
        return b
    return b[:BCRYPT_MAX_BYTES]


# =============================================================================
# Passwords
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # PASAMOS BYTES ya truncados: evita ValueError sí o sí
        return pwd_context.verify(_bcrypt72(plain_password), hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    # PASAMOS BYTES ya truncados: evita ValueError sí o sí
    return pwd_context.hash(_bcrypt72(password))


def verify_and_rehash(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    try:
        ok, new_hash = pwd_context.verify_and_update(_bcrypt72(plain_password), hashed_password)
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


def issue_access_cookie(
    response: Response,
    token: str,
    request: Request | None = None,
) -> None:
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    secure = COOKIE_SECURE
    samesite = COOKIE_SAMESITE
    httponly = COOKIE_HTTPONLY

    # Determine host for cookie domain (proxy-safe)
    host: str | None = None
    if request is not None:
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
            host = host.lower() or None

        if not host:
            try:
                host = (request.url.hostname or "").lower() or None
            except Exception:
                host = None

        xf_proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
        if xf_proto and xf_proto.split(",")[0].strip().lower() == "https":
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


def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", domain=COOKIE_DOMAIN or None)


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


# =============================================================================
# Billing helpers (backwards-compat imports)
# =============================================================================

def normalize_user_plan(db, user) -> None:
    """
    Backwards-compat shim:
    Some routers import normalize_user_plan from app.security.
    Keeps plan/is_pro coherent.
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
