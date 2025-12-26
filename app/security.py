# app/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response, status
from jose import jwt
from passlib.context import CryptContext

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SESSION_SECRET", "change-me-in-env"))
JWT_ALG = os.getenv("JWT_ALG", "HS256")

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(60 * 60 * 24 * 30)))  # 30 días

COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()
COOKIE_SECURE = (os.getenv("COOKIE_SECURE", "") or "").lower() in ("1", "true", "yes", "on")
COOKIE_HTTPONLY = (os.getenv("COOKIE_HTTPONLY", "1") or "1").lower() in ("1", "true", "yes", "on")

COOKIE_DOMAIN_ENV = os.getenv("COOKIE_DOMAIN", "").strip() or None

# ✅ IMPORTANTE:
# bcrypt tiene límite de 72 bytes. Para passwords largos usamos pbkdf2_sha256.
pwd_context = CryptContext(
    schemes=["bcrypt", "pbkdf2_sha256"],
    deprecated="auto",
)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(seconds=COOKIE_MAX_AGE))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    bcrypt revienta si el password supera 72 bytes.
    Para evitar que Render crashee en init_db/seed_admin,
    si supera 72 bytes usamos pbkdf2_sha256.
    """
    try:
        pw_bytes = (password or "").encode("utf-8", errors="ignore")
    except Exception:
        pw_bytes = b""

    if len(pw_bytes) > 72:
        # ✅ safe fallback (sin límite 72 bytes)
        return pwd_context.hash(password, scheme="pbkdf2_sha256")

    # bcrypt normal
    return pwd_context.hash(password, scheme="bcrypt")


def _cookie_domain_from_host(host: str) -> Optional[str]:
    if not host:
        return None

    host = host.split(":")[0].strip().lower()

    if host == "localhost" or host.replace(".", "").isdigit():
        return None

    parts = host.split(".")
    if len(parts) < 2:
        return None

    root = ".".join(parts[-2:])
    return f".{root}"


def _get_cookie_domain(request: Optional[Request] = None) -> Optional[str]:
    if COOKIE_DOMAIN_ENV:
        return COOKIE_DOMAIN_ENV
    if request is None:
        return None
    host = request.headers.get("host") or ""
    return _cookie_domain_from_host(host)


def issue_access_cookie(resp: Response, token: str, request: Optional[Request] = None) -> None:
    domain = _get_cookie_domain(request)

    samesite = COOKIE_SAMESITE
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"

    secure = COOKIE_SECURE or (samesite == "none")

    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        expires=datetime.now(timezone.utc) + timedelta(seconds=COOKIE_MAX_AGE),
        path="/",
        domain=domain,
        secure=secure,
        httponly=COOKIE_HTTPONLY,
        samesite=samesite,
    )


def clear_access_cookie(resp: Response, request: Optional[Request] = None) -> None:
    resp.delete_cookie(key=COOKIE_NAME, path="/")

    if request is not None:
        domain = _get_cookie_domain(request)
        if domain:
            resp.delete_cookie(key=COOKIE_NAME, path="/", domain=domain)

    if COOKIE_DOMAIN_ENV:
        resp.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN_ENV)


def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)

    # fallback robusto si hay cookies duplicadas
    if not token:
        raw = request.headers.get("cookie", "") or ""
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        for p in reversed(parts):
            if p.startswith(COOKIE_NAME + "="):
                token = p.split("=", 1)[1]
                break

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token


def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    token = get_token_from_request(request)
    try:
        return decode_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


def get_current_user_cookie_optional(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raw = request.headers.get("cookie", "") or ""
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        for p in reversed(parts):
            if p.startswith(COOKIE_NAME + "="):
                token = p.split("=", 1)[1]
                break

    if not token:
        return None

    try:
        return decode_token(token)
    except Exception:
        return None


def get_current_user_id(request: Request) -> int:
    payload = get_current_user_cookie(request)
    sub = payload.get("sub")
    try:
        return int(sub)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


def normalize_user_plan(db, user) -> None:
    # fallback no intrusivo
    return
