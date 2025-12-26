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
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)

def verify_or_upgrade_password(plain_password: str, hashed_password: str) -> Tuple[bool, Optional[str]]:
    """
    Devuelve (ok, new_hash). new_hash se devuelve si se puede mejorar el hash.
    """
    try:
        ok, new_hash = pwd_context.verify_and_update(plain_password, hashed_password)
        return bool(ok), new_hash
    except Exception:
        try:
            return pwd_context.verify(plain_password, hashed_password), None
        except Exception:
            return False, None

# =========================
# JWT settings
# =========================
JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SESSION_SECRET", "change-me-in-env"))
JWT_ALG = os.getenv("JWT_ALG", "HS256")
ACCESS_TOKEN_EXPIRE_MIN = int(os.getenv("ACCESS_TOKEN_EXPIRE_MIN", "43200"))  # 30 días

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1").lower() in ("1", "true", "yes", "on")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" o "none"

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MIN))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

def set_access_cookie(response: Response, token: str) -> None:
    """
    Cookie httpOnly con el JWT.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path="/",
        max_age=60 * 60 * 24 * 30,
    )

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

# =========================
# Request helpers
# =========================
def get_token_from_request(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return token

def get_current_user_cookie(request: Request) -> Dict[str, Any]:
    """
    Lee el JWT desde cookie y devuelve el payload.
    """
    token = get_token_from_request(request)
    return decode_token(token)

# =========================
# CSRF (simple, UI forms)
# =========================
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrf_token")

def ensure_csrf_cookie(response: Response) -> str:
    """
    Crea un token CSRF simple y lo guarda en cookie NO httpOnly (para forms).
    """
    import secrets
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path="/",
        max_age=60 * 60 * 24 * 7,
    )
    return token

def validate_csrf(request: Request) -> None:
    """
    Valida CSRF comparando header/form con cookie.
    Espera X-CSRF-Token o form field csrf_token.
    """
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF faltante")

    header = request.headers.get("X-CSRF-Token")
    if header and header == cookie:
        return

    # fallback: por si se manda como query param (no recomendado)
    qp = request.query_params.get("csrf_token")
    if qp and qp == cookie:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF inválido")

# -----------------------------
# Compat helpers (UI routers)
# -----------------------------

def get_current_user_id(request: Request) -> int:
    """
    Helper usado por app/guards.py y routers admin.
    Lee el JWT cookie y devuelve el user id (int).
    """
    payload = get_current_user_cookie(request)
    sub = payload.get("sub") if isinstance(payload, dict) else None

    try:
        return int(str(sub))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


def normalize_user_plan(db, user):
    """
    Wrapper para mantener compatibilidad con routers UI que importan
    normalize_user_plan desde app.security.

    La implementación real vive en app.security.billing_guard.py
    (import lazy para evitar circular imports).
    """
    try:
        from app.security.billing_guard import normalize_user_plan as _normalize
        return _normalize(db, user)
    except Exception:
        # fallback ultra seguro: no romper el renderizado
        try:
            plan = (getattr(user, "plan", None) or "FREE").upper()
            setattr(user, "plan", plan)
        except Exception:
            pass
        return user

# -----------------------------
# Backwards-compat for init_db
# -----------------------------
def get_password_hash(plain_password: str) -> str:
    """
    Compat: scripts/init_db.py importa get_password_hash.
    Internamente usamos hash_password.
    """
    return hash_password(plain_password)

# -----------------------------
# Backwards-compat aliases
# -----------------------------
def issue_access_cookie(response, token: str) -> None:
    """
    Compat: routers/auth.py importa issue_access_cookie.
    Internamente usamos set_access_cookie().
    """
    return set_access_cookie(response, token)
