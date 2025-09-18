# app/security.py
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Cookie, HTTPException, status, Request
from fastapi.responses import Response

# === Config ===
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALG = "HS256"

# Si quisieras volver a una cookie persistente, podés setear esto en False y usar ACCESS_TOKEN_TTL_MIN.
SESSION_ONLY_COOKIES = True
ACCESS_TOKEN_TTL_MIN = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "60"))  # usado solo si SESSION_ONLY_COOKIES=False

COOKIE_NAME = "access_token"
COOKIE_PATH = "/"
COOKIE_SECURE = True            # En HTTPS debe ser True. En localhost podés poner False.
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"         # "lax" suele ir bien para apps normales


# === JWT helpers ===
def create_access_token(data: Dict[str, Any], expires_minutes: Optional[int] = None) -> str:
    to_encode = data.copy()
    if expires_minutes is not None:
        expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        to_encode.update({"exp": expire})
    # Si expires_minutes es None: no seteamos "exp" y validamos por cookie de sesión
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload  # dict con claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


# === Cookie helpers ===
def issue_access_cookie(response: Response, user_claims: Dict[str, Any]) -> str:
    """
    Emite el token y setea la cookie.
    - Modo por defecto: cookie de sesión (sin Max-Age ni Expires) -> se borra al cerrar el navegador.
    - Si SESSION_ONLY_COOKIES = False, crea cookie persistente con expiración.
    """
    if SESSION_ONLY_COOKIES:
        # Sin 'exp' en el JWT y sin Max-Age/Expires en cookie -> sesión pura
        token = create_access_token(user_claims, expires_minutes=None)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTPONLY,
            samesite=COOKIE_SAMESITE,
            # Ojo: NO ponemos max_age ni expires para que sea de sesión
        )
    else:
        # Cookie persistente (opcional)
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


# === Dependency para rutas protegidas (lectura desde cookie) ===
def get_current_user_cookie(access_token: Optional[str] = Cookie(default=None, alias=COOKIE_NAME)) -> Dict[str, Any]:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return decode_token(access_token)


# === Helpers de conveniencia ===
def issue_access_cookie_for_user(response: Response, user_id: int, email: str, is_admin: bool, plan: str = "FREE") -> str:
    claims = {"sub": str(user_id), "email": email, "admin": is_admin, "plan": plan}
    return issue_access_cookie(response, claims)
