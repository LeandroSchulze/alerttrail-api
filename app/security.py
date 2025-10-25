# app/security.py
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status
from jose import jwt, JWTError
from passlib.context import CryptContext
from starlette.responses import Response


# =========================
# Configuración de Password Hash
# =========================
# Soporta ambos esquemas para compatibilidad con usuarios antiguos
# y permite migración transparente.
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)

def get_password_hash(password: str) -> str:
    """Genera el hash de la contraseña con el esquema preferido."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password inválido")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verificador clásico: mantiene compatibilidad con código existente.
    (No rehashea automáticamente. Para eso usar verify_and_rehash.)
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def verify_and_rehash(plain_password: str, hashed_password: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica la contraseña y, si el hash está desactualizado, devuelve un nuevo hash.
    Retorna (ok, new_hash or None).
    """
    if not plain_password or not hashed_password:
        return False, None
    try:
        ok = pwd_context.verify(plain_password, hashed_password)
        if not ok:
            return False, None
        # Si el hash no está con el esquema preferido, actualizamos
        if pwd_context.needs_update(hashed_password):
            return True, pwd_context.hash(plain_password)
        return True, None
    except Exception:
        return False, None


# =========================
# Configuración de JWT
# =========================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-please")  # Cambiar en producción
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
# Tiempo por defecto del token (en minutos)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Crea un JWT con expiración. Debe incluir, idealmente, 'sub' (user_id o email).
    """
    to_encode = data.copy()
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": _now_utc()})
    token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def decode_token(token: str) -> Dict[str, Any]:
    """
    Decodifica y valida el token. Lanza 401 si no es válido/expirado.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        ) from e


# =========================
# Configuración de Cookies
# =========================
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

# IMPORTANTE:
# - En desarrollo (HTTP local) conviene SECURE=False.
# - En producción HTTPS, poner SECURE=True.
def _env_bool(var_name: str, default: bool) -> bool:
    v = os.getenv(var_name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y")

COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" | "strict" | "none"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)       # e.g. ".tudominio.com" o None
COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(60 * 60 * 24 * 7)))  # 7 días


def issue_access_cookie(
    response: Response,
    token: str,
    max_age: Optional[int] = None,
) -> None:
    """
    Escribe la cookie HTTPOnly con el JWT.
    """
    # Samesite "none" requiere secure=True por los navegadores modernos.
    samesite = COOKIE_SAMESITE.lower()
    secure = COOKIE_SECURE or (samesite == "none")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age if max_age is not None else COOKIE_MAX_AGE,
        expires=max_age if max_age is not None else COOKIE_MAX_AGE,
        path="/",
        domain=COOKIE_DOMAIN,
        secure=secure,
        httponly=True,
        samesite=samesite,  # "lax"/"strict"/"none"
    )

def clear_access_cookie(response: Response) -> None:
    """
    Elimina la cookie del JWT.
    """
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=COOKIE_DOMAIN,
    )


# =========================
# Utilidades de autenticación en requests
# =========================
def get_token_from_request(request: Request) -> str:
    """
    Obtiene el token desde la cookie.
    Lanza 401 si no existe.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
        )
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    """
    Decodifica el token de la cookie y devuelve el payload.
    - Si necesitás el usuario completo, en tus endpoints hacé el lookup por `sub` en la DB.
    """
    token = get_token_from_request(request)
    payload = decode_token(token)
    # Validación mínima: requerimos 'sub'
    if "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin sujeto (sub)",
        )
    return payload


# =========================
# Helpers opcionales
# =========================
def minutes_from_now(minutes: int) -> datetime:
    return _now_utc() + timedelta(minutes=minutes)

def unix_ts(dt: Optional[datetime] = None) -> int:
    """
    Timestamp Unix (segundos) de ahora o de dt.
    """
    if dt is None:
        dt = _now_utc()
    return int(dt.timestamp())
