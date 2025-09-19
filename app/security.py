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
JWT_SECRET = (os.getenv("JWT_SECRET") or "change-me")
JWT_ALG = "HS256"

# Activa logs de diagnóstico si DEBUG_AUTH=1/true/on
DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"))

# Cookies de sesión (expiran al cerrar el navegador si True)
SESSION_ONLY_COOKIES = True
ACCESS_TOKEN_TTL_MIN = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "60"))  # usado si SESSION_ONLY_COOKIES=False

# Debe coincidir con lo que use tu app
COOKIE_NAME   = os.getenv("COOKIE_NAME", "access_token")
COOKIE_PATH   = "/"
COOKIE_SECURE = True            # En HTTPS True (Render va con HTTPS)
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
# Si usás SIEMPRE www, conviene dejarlo vacío (host-only). Si querés compartir entre apex y www: ".alerttrail.com"
COOKIE_DOMAIN = (os.getenv("COOKIE_DOMAIN", "") or "").strip()

# ================== Password Hash (PBKDF2) ==================
# Formato: pbkdf2$<iterations>$<salt_b64>$<hash_b64>
PBKDF2_ITER = int(os.getenv("PBKDF2_ITER", "260000"))
PBKDF2_ALG = "sha256"
PBKDF2_SALT_BYTES = 16

def _pbkdf2_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(PBKDF2_ALG, password.encode("utf-8"), salt, iterations)

def get_password_hash(password: str) -> str:
    salt = os.urandom(PBKDF2_SALT_BYTES)
    dk = _pbkdf2_hash(password, salt, PBKDF2_ITER)
    return "pbkdf2${}${}${}".format(
        PBKDF2_ITER,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(dk).decode().rstrip("="),
    )

def verify_password(password: str, stored: str) -> bool:
    try:
        if not stored:
            return False
        # bcrypt (si tu DB tuviera hashes viejos)
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
    except jwt.ExpiredSignatureError as e:
        if DEBUG_AUTH: print("[auth][debug] decode: expired:", repr(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError as e:
        if DEBUG_AUTH: print("[auth][debug] decode: invalid:", repr(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

# Alias por si algún módulo llama decode_access_token
decode_access_token = decode_token

# ================== Cookie helpers ==================
def issue_access_cookie(response: Response, user_claims: Dict[str, Any]) -> str:
    """
    Genera un JWT y lo setea en la MISMA response.
    """
    if SESSION_ONLY_COOKIES:
        token = create_access_token(user_claims, expires_minutes=None)
        cookie_kwargs = dict(
            key=COOKIE_NAME,
            value=token,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTPONLY,
            samesite=COOKIE_SAMESITE,
        )
        if COOKIE_DOMAIN:
            cookie_kwargs["domain"] = COOKIE_DOMAIN
        response.set_cookie(**cookie_kwargs)
    else:
        token = create_access_token(user_claims, expires_minutes=ACCESS_TOKEN_TTL_MIN)
        max_age = ACCESS_TOKEN_TTL_MIN * 60
        expire_dt = datetime.now(timezone.utc) + timedelta(seconds=max_age)
        cookie_kwargs = dict(
            key=COOKIE_NAME,
            value=token,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTPONLY,
            samesite=COOKIE_SAMESITE,
            max_age=max_age,
            expires=int(expire_dt.timestamp()),
        )
        if COOKIE_DOMAIN:
            cookie_kwargs["domain"] = COOKIE_DOMAIN
        response.set_cookie(**cookie_kwargs)

    if DEBUG_AUTH:
        print("[auth][debug] issue_cookie: domain=", COOKIE_DOMAIN or "<host-only>")

    return token

def clear_access_cookie(response: Response) -> None:
    kwargs = dict(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        httponly=COOKIE_HTTPONLY,
    )
    if COOKIE_DOMAIN:
        kwargs["domain"] = COOKIE_DOMAIN
    response.delete_cookie(**kwargs)

# ================== Auth dependency ==================
def get_current_user_cookie(
    request: Optional[Request] = None,
    db=None,  # si viene, devolvemos el objeto User
    access_token: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """
    Si se pasa 'db', devuelve el objeto User.
    Si no, devuelve el dict de claims.
    Acepta claims 'sub' | 'user_id' | 'uid'.
    """
    token = access_token or (request.cookies.get(COOKIE_NAME) if request is not None else None)
    if not token:
        if DEBUG_AUTH: print("[auth][debug] no-cookie")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    if DEBUG_AUTH:
        print("[auth][debug] token-len:", len(token))

    claims = decode_token(token)

    if DEBUG_AUTH:
        print("[auth][debug] claims:", {k: claims.get(k) for k in ("sub", "user_id", "uid", "email")})

    # sin DB: devolvemos claims
    if db is None:
        return claims

    # con DB: devolvemos el usuario
    uid = claims.get("sub") or claims.get("user_id") or claims.get("uid")
    try:
        uid_int = int(uid)
    except Exception:
        if DEBUG_AUTH: print("[auth][debug] invalid uid:", repr(uid))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    try:
        from app import models
        user = db.get(models.User, uid_int)  # SQLAlchemy 2.x
    except Exception:
        user = db.query(models.User).get(uid_int)  # SQLAlchemy 1.x fallback

    if not user:
        if DEBUG_AUTH: print("[auth][debug] user-not-found:", uid_int)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    if DEBUG_AUTH:
        print("[auth][debug] user-ok:", user.id, getattr(user, "email", None))

    return user

def issue_access_cookie_for_user(response: Response, user_id: int, email: str, is_admin: bool, plan: str = "FREE") -> str:
    claims = {
        "sub": str(user_id),
        "user_id": user_id,
        "uid": user_id,
        "email": email,
        "admin": is_admin,
        "plan": plan,
    }
    return issue_access_cookie(response, claims)
