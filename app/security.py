# app/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import HTTPException, Request, Response
from jose import jwt, JWTError
from passlib.context import CryptContext

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # lax/none/strict
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None

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
    if not isinstance(password, str) or not password:
        raise ValueError("Password inválido")

    # Importante: bcrypt tiene límite práctico de 72 bytes y en Render se usa
    # ADMIN_PASSWORD desde env (a veces muy largo). Para evitar que init_db
    # rompa el deploy, forzamos pbkdf2_sha256 para generar hashes nuevos.
    # (verify_password sigue soportando bcrypt si ya existían hashes viejos.)
    return pwd_context.hash(password, scheme="pbkdf2_sha256")


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _cookie_domain_from_host(host: str) -> Optional[str]:
    """
    Dominio de cookie *solo* para alerttrail.com (evita setear .onrender.com por error).
    """
    if not host:
        return None

    host = host.split(":")[0].strip().lower()

    # Localhost / IP => host-only
    if host in ("localhost",):
        return None
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return None

    # Solo permitimos compartir cookie entre subdominios de alerttrail.com
    if host == "alerttrail.com" or host.endswith(".alerttrail.com"):
        return ".alerttrail.com"

    return None


def _host_from_request(request: Request) -> str:
    """
    Render/proxies a veces no preservan Host como esperás.
    Para que la cookie quede en el dominio correcto, priorizamos:
      - X-Forwarded-Host (puede traer lista: "www..., ...")
      - X-Original-Host
      - Host
      - request.url.hostname
    """
    xf_host = (request.headers.get("x-forwarded-host") or "").strip()
    if xf_host:
        # puede venir "www.alerttrail.com, internal.onrender.com"
        xf_host = xf_host.split(",")[0].strip()
        if xf_host:
            return xf_host

    x_orig = (request.headers.get("x-original-host") or "").strip()
    if x_orig:
        return x_orig

    host = (request.headers.get("host") or "").strip()
    if host:
        return host

    return (request.url.hostname or "").strip()


def issue_access_cookie(response: Response, token: str, request: Optional[Request] = None):
    # Determinar domain (prioridad: env -> derivado del host real)
    domain = COOKIE_DOMAIN
    if not domain and request is not None:
        domain = _cookie_domain_from_host(_host_from_request(request))

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        domain=domain,
    )


def clear_access_cookie(response: Response, request: Optional[Request] = None):
    # borrar por env (si existe)
    response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN or None)

    # borrar también con domain derivado (por si quedó una cookie vieja)
    if request is not None:
        d = _cookie_domain_from_host(_host_from_request(request))
        if d:
            response.delete_cookie(key=COOKIE_NAME, path="/", domain=d)


def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if "sub" not in payload:
            raise HTTPException(status_code=401, detail="Token inválido")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


def get_current_user_cookie_optional(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if "sub" not in payload:
            return None
        return payload
    except JWTError:
        return None


# Compat: algunos módulos viejos esperan estas funciones
def issue_access_cookie_legacy(response: Response, token: str):
    issue_access_cookie(response, token, request=None)


def clear_access_cookie_legacy(response: Response):
    clear_access_cookie(response, request=None)
