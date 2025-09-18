# app/security.py
import os
import hmac
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Cookie, HTTPException, status, Request
from fastapi.responses import Response

# ================== Config ==================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALG = "HS256"

# Cookies de sesión (expiran al cerrar el navegador)
SESSION_ONLY_COOKIES = True
ACCESS_TOKEN_TTL_MIN = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "60"))  # usado si SESSION_ONLY_COOKIES=False

COOKIE_NAME = "access_token"
COOKIE_PATH = "/"
COOKIE_SECURE = True           # En HTTPS True. En localhost podés poner False.
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"

# ================== Password Hash (PBKDF2) ==================
# Formato: pbkdf2$<iterations>$<salt_b64>$<hash_b64>
PBKDF2_ITER = int(os.getenv("PBKDF2_ITER", "260000"))
PBKDF2_ALG = "sha256"
PBKDF2_SALT_BYTES = 16

def _pbkdf2_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(PBKDF2_ALG, password.encode("utf-8"), salt, iterations)

def get_password_hash(password: str) -> str:
    """API usada por scripts/init_db.py"""
    salt = os.urandom(PBKDF2_SALT_BYTES)
    dk = _pbkdf2_hash(password, salt, PBKDF2_ITER)
    return "pbkdf2${}${}${}".format(
        PBKDF2_ITER,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(dk).decode().rstrip("="),
    )

# app/security.py  (solo esta función)
import base64, hmac, hashlib

def verify_password(password: str, stored: str) -> bool:
    """
    Soporta:
    - PBKDF2:  pbkdf2$<iters>$<salt_b64>$<hash_b64>
    - bcrypt ($2a$ / $2b$) si el paquete está instalado; si no, devuelve False.
    """
    try:
        if not stored:
            return False

        # bcrypt (opcional)
        if stored.startswith("$2b$") or stored.startswith("$2a$"):
            try:
                import bcrypt
                return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
            except Exception:
                return False

        # PBKDF2
        parts = stored.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2":
            _, iters_s, salt_b64, dk_b64 = parts
            def _unb64(s: str) -> bytes:
                pad = "=" * (-len(s) % 4)
                return base64.urlsafe_b64decode(s + pad)
            iters = int(iters_s)
            salt = _unb64(salt_b64)
            expected = _unb64(dk_b64)
            test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
            return hmac.compare_digest(expected, test)

        return False
    except Exception:
        return False

# ================== JWT helpers ==================
def create_access_token(data: Dict[str, Any], expires_minutes: Optional[int] = None) -> str:
    to_encode = data.copy()
    if expires_minutes is not None:
        expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

# ================== Cookie helpers ==================
def issue_access_cookie(response: Response, user_claims: Dict[str, Any]) -> str:
    if SESSION_ONLY_COOKIES:
        token = create_access_token(user_claims, expires_minutes=None)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTPONLY,
            samesite=COOKIE_SAMESITE,
        )
    else:
        token = create_access_token(user_claims, expires_minutes=ACCESS_TOKEN_TTL_MIN)
        max_age = ACCESS_TOKEN_TTL_MIN * 60
        expire_dt = datetime.now(timezone.utc) + timedelta(seconds=max_age)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTPONLY,
            samesite=COOKIE_SAMESITE,
            max_age=max_age,
            expires=int(expire_dt.timestamp()),
        )
    return token

def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        httponly=COOKIE_HTTPONLY,
    )

# ================== Auth dependency (compatible) ==================
def get_current_user_cookie(
    request: Optional[Request] = None,
    db=None,  # compat con firmas previas; no se usa aquí
    access_token: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
) -> Dict[str, Any]:
    """
    Compatibilidad:
    - Puede ser llamada como get_current_user_cookie(request, db)
    - O como dependencia con Cookie('access_token')
    """
    token = access_token
    if (not token) and request is not None:
        # fallback por si alguien la llama pasándole request manualmente
        token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return decode_token(token)

def issue_access_cookie_for_user(response: Response, user_id: int, email: str, is_admin: bool, plan: str = "FREE") -> str:
    claims = {"sub": str(user_id), "email": email, "admin": is_admin, "plan": plan}
    return issue_access_cookie(response, claims)
