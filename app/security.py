# app/security.py
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status
from starlette.responses import Response
from jose import jwt, JWTError
from passlib.context import CryptContext


# =========================
# Password hashing
# =========================
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],  # compat con hashes viejos y nuevos
    deprecated="auto",
)

def get_password_hash(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password inválido")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def verify_and_rehash(plain_password: str, hashed_password: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica la contraseña y, si el hash está desactualizado, retorna (True, new_hash).
    Si no hay que rehashear, retorna (True, None). Si falla, (False, None).
    """
    if not plain_password or not hashed_password:
        return False, None
    try:
        ok = pwd_context.verify(plain_password, hashed_password)
        if not ok:
            return False, None
        if pwd_context.needs_update(hashed_password):
            return True, pwd_context.hash(plain_password)
        return True, None
    except Exception:
        return False, None


# =========================
# JWT
# =========================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Por defecto 7 días (evita que se cierre sesión al reiniciar el navegador)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": _now_utc()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado") from e


# =========================
# Cookies
# =========================
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")

def _env_bool(var_name: str, default: bool) -> bool:
    v = os.getenv(var_name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")

COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = (os.getenv("COOKIE_SAMESITE", "lax") or "lax").lower()  # "lax" | "strict" | "none"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)  # e.g. ".alerttrail.com" o None

# 7 días por defecto
COOKIE_MAX_AGE = int(os.getenv("COOKIE_MAX_AGE", str(60 * 60 * 24 * 7)))

def issue_access_cookie(response: Response, token: str, max_age: Optional[int] = None) -> None:
    """
    Emite cookie persistente con Max-Age y Expires absoluto para mejor compatibilidad.
    Si SameSite=None, fuerza Secure=True (requisito de los navegadores modernos).
    """
    ma = max_age if max_age is not None else COOKIE_MAX_AGE
    # Fecha absoluta (UTC) para Expires (mejor soporte Safari/Chromium)
    expires_dt = _now_utc() + timedelta(seconds=ma)

    samesite = COOKIE_SAMESITE
    secure = COOKIE_SECURE or (samesite == "none")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=ma,
        expires=expires_dt,   # datetime -> Starlette formatea a RFC 7231
        path="/",
        domain=COOKIE_DOMAIN, # Usa un dominio base (p.ej. ".alerttrail.com") si querés compartir entre subdominios
        secure=secure,
        httponly=True,
        samesite=samesite,
    )

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)


# =========================
# Helpers de request
# =========================
def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    """
    Devuelve el payload del JWT (p.ej. {"sub": "...", "email": "..."}).
    Si necesitás el objeto User real, hacé el lookup en la vista usando 'sub'.
    """
    token = get_token_from_request(request)
    payload = decode_token(token)
    if "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto (sub)")
    return payload
# app/security.py
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status
from starlette.responses import Response
from jose import jwt, JWTError
from passlib.context import CryptContext


# =========================
# Password hashing
# =========================
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],  # compat con hashes viejos y nuevos
    deprecated="auto",
)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


# =========================
# JWT / Cookies
# =========================
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "10080"))  # 7 días

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MIN))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from e

def issue_access_cookie(response: Response, token: str) -> None:
    """
    Setea cookie de sesión. Se endurece luego con middleware en main.py.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=(os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes", "on")),
        path="/",
        max_age=60 * 60 * 24 * 7,  # 7 días
    )

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")

def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    """
    Devuelve el payload del JWT (p.ej. {"sub": "...", "email": "..."}).
    Si necesitás el objeto User real, hacé el lookup en la vista usando 'sub'.
    """
    token = get_token_from_request(request)
    payload = decode_token(token)
    if "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto (sub)")
    return payload


# ============================================================
# CSRF (compatibilidad): algunos routers legacy lo importan
# Por defecto NO bloquea (CSRF opcional). Si querés exigirlo,
# setea CSRF_ENABLED=1 y el frontend debe enviar header X-CSRF.
# ============================================================

import secrets as _secrets

def issue_csrf(response: Response) -> Response:
    """Setea cookie CSRF (no-HttpOnly) para formularios web (opcional)."""
    try:
        if os.getenv("CSRF_ENABLED", "").lower() in ("1","true","yes","on"):
            token = _secrets.token_urlsafe(24)
            response.set_cookie(
                "csrf_token",
                token,
                max_age=60*60*6,  # 6h
                httponly=False,
                samesite="lax",
                secure=(os.getenv("COOKIE_SECURE","").lower() in ("1","true","yes","on")),
                path="/",
            )
    except Exception:
        pass
    return response

async def validate_csrf(request: Request) -> None:
    """Valida CSRF si CSRF_ENABLED=1. Caso contrario, no hace nada."""
    if os.getenv("CSRF_ENABLED", "").lower() not in ("1","true","yes","on"):
        return
    cookie = request.cookies.get("csrf_token") or ""
    header = request.headers.get("x-csrf") or request.headers.get("x-csrf-token") or ""
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF inválido")

# ============================================================
# Billing guard (compatibilidad): centralizado en security.py
# ============================================================

def normalize_user_plan(db, user):
    """Normaliza plan PRO por expiración (si existen campos)."""
    try:
        now = datetime.now(timezone.utc)
        expires = getattr(user, "plan_expires", None) or getattr(user, "pro_expires_at", None)
        if expires:
            # Si es naive, asumimos UTC
            try:
                if getattr(expires, "tzinfo", None) is None:
                    expires = expires.replace(tzinfo=timezone.utc)
            except Exception:
                pass
            if expires < now:
                if hasattr(user, "plan"):
                    user.plan = "FREE"
                if hasattr(user, "is_pro"):
                    user.is_pro = False
                if hasattr(user, "pro_source"):
                    user.pro_source = None
                db.add(user)
                db.commit()
                try:
                    db.refresh(user)
                except Exception:
                    pass
    except Exception:
        pass
    return user

# ===============================
# Compatibility stubs (NO-OP)
# ===============================

def issue_csrf(*args, **kwargs):
    """
    Stub de compatibilidad.
    No se usa CSRF real en AlertTrail (JWT por cookie).
    """
    return None


def verify_csrf(*args, **kwargs):
    return True

