# app/security.py
import os
import hmac
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import HTTPException, status, Request
from fastapi.responses import Response

# ================== Config ==================
JWT_SECRET = (os.getenv("JWT_SECRET") or "change-me")
JWT_ALG = "HS256"

# Logs de diagnóstico si DEBUG_AUTH=1/true/on
DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"))

# Cookies
SESSION_ONLY_COOKIES = True
ACCESS_TOKEN_TTL_MIN = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "60"))  # si SESSION_ONLY_COOKIES=False

COOKIE_NAME     = os.getenv("COOKIE_NAME", "access_token")
COOKIE_PATH     = "/"
COOKIE_SECURE   = True            # HTTPS en Render
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
# Si usás SIEMPRE www, podés dejarlo vacío (host-only). Para compartir apex/www: ".alerttrail.com"
COOKIE_DOMAIN   = (os.getenv("COOKIE_DOMAIN", "") or "").strip()

# ================== Trial / Promo ==================
# Duración del trial PRO (solo particulares)
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "5"))

# Nota: en modelos se usa DateTime naive (UTC). Para consistencia, usamos datetime.utcnow() sin tz.
def now_utc_naive() -> datetime:
    return datetime.utcnow()

def is_trial_active(user) -> bool:
    """Devuelve True si el usuario tiene trial vigente."""
    try:
        return bool(user.trial_expires_at and user.trial_expires_at > now_utc_naive())
    except Exception:
        return False

def is_paid_pro(user) -> bool:
    """
    PRO por suscripción. Dado que el modelo no siempre tiene plan_expires,
    nos apoyamos en user.plan == 'PRO'. Si existiera plan_expires en tu modelo,
    también lo validamos a favor.
    """
    try:
        # Compat opcional si tu modelo tuviera plan_expires
        plan_expires = getattr(user, "plan_expires", None)
        if plan_expires:
            # soporta tanto naive como aware (preferimos naive UTC)
            if isinstance(plan_expires, datetime):
                # si viene aware, lo volvemos naive comparando contra now naive en UTC
                if plan_expires.tzinfo is not None:
                    # convertir a naive UTC
                    plan_expires = plan_expires.astimezone(timezone.utc).replace(tzinfo=None)
            return plan_expires > now_utc_naive()
        # Si no existe plan_expires, tomamos plan == 'PRO' como pagado
        return str(getattr(user, "plan", "")).upper() == "PRO"
    except Exception:
        return False

def is_pro_effective(user) -> bool:
    """
    El usuario es efectivamente PRO si:
      - tiene suscripción activa (is_paid_pro), o
      - está en trial vigente (is_trial_active).
    """
    return bool(is_paid_pro(user) or is_trial_active(user))

def ensure_trial_state(user, db) -> None:
    """
    Si el trial venció y no hay PRO pago, limpiamos campos de trial.
    Idempotente. Llamar al inicio de endpoints PRO.
    """
    try:
        if not user:
            return
        expired = bool(user.trial_expires_at and user.trial_expires_at <= now_utc_naive())
        if expired and not is_paid_pro(user):
            user.trial_started_at = None
            user.trial_expires_at = None
            # si el trial terminó y no hay PRO pago, limpiamos pro_source si venía de trial
            if getattr(user, "pro_source", None) == "trial":
                user.pro_source = None
            if db:
                db.commit()
    except Exception as e:
        if DEBUG_AUTH:
            print("[auth][debug] ensure_trial_state error:", repr(e))

def require_pro_effective(user, db=None) -> None:
    """
    Enforcer de acceso PRO (trial o suscripción). Lanza 402 si no corresponde.
    Llama ensure_trial_state para caducar trial vencido.
    """
    ensure_trial_state(user, db)
    if not is_pro_effective(user):
        raise HTTPException(status_code=402, detail="Necesitas PRO activo (trial o suscripción)")

def require_individual_for_trial(user) -> None:
    """
    Asegura que el usuario sea particular (sin org) para acceder al trial.
    """
    if getattr(user, "org_id", None):
        raise HTTPException(status_code=403, detail="La promo es solo para cuentas individuales")

# ================== Password Hash (PBKDF2) ==================
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
    """Verifica contraseña contra PBKDF2 (formato propio) o bcrypt (legado)."""
    try:
        if not stored:
            return False
        # bcrypt (por si hay hashes viejos)
        if stored.startswith("$2b$") or stored.startswith("$2a$"):
            try:
                import bcrypt
                return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
            except Exception:
                return False
        # PBKDF2 (formato: pbkdf2$<iters>$<salt_b64>$<hash_b64>)
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
        # Para tokens con expiración explícita usamos aware UTC
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

# Alias común usado en algunas partes del código
decode_access_token = decode_token

# ================== Cookie helpers ==================
def issue_access_cookie(response: Response, user_claims: Dict[str, Any]) -> str:
    """Genera un JWT y lo setea en la MISMA response."""
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

# ================== Auth dependencies ==================
def get_current_user_cookie(
    request: Request,
    db=None,                     # si viene, devolvemos el objeto User
):
    """
    Lee el JWT desde la cookie y devuelve:
      - el objeto User si se pasa 'db'
      - o los claims si no se pasa 'db'
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        if DEBUG_AUTH: print("[auth][debug] no-cookie")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    if DEBUG_AUTH:
        try:
            print("[auth][debug] token-len:", len(token))
        except Exception:
            print("[auth][debug] token present (non-str)")

    claims = decode_token(token)

    if DEBUG_AUTH:
        print("[auth][debug] claims:", {k: claims.get(k) for k in ("sub", "user_id", "uid", "email")})

    if db is None:
        return claims

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
        user = db.query(models.User).get(uid_int)  # SQLAlchemy 1.x

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

# --- Compatibilidad con routers antiguos ---
def get_current_user(request: Request, db=None):
    """
    Alias para mantener compatibilidad con routers que aún importan
    'get_current_user' desde app.security.
    """
    return get_current_user_cookie(request, db)
