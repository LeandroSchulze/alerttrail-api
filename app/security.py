# app/security.py
import os, datetime as dt
import jwt
from passlib.hash import pbkdf2_sha256
from fastapi import Request, HTTPException
from cryptography.fernet import Fernet, InvalidToken

JWT_SECRET = os.getenv('JWT_SECRET', 'change-me')
JWT_ALG = 'HS256'
COOKIE_NAME = 'access_token'
issue_minutes = 60*24  # 24h

def get_password_hash(p: str) -> str:
    return pbkdf2_sha256.hash(p)

def verify_password(p: str, h: str) -> bool:
    return pbkdf2_sha256.verify(p, h)

def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": dt.datetime.utcnow() + dt.timedelta(minutes=issue_minutes)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

def issue_access_cookie(response, user_id: int):
    token = create_token(user_id)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite='lax', secure=False, max_age=60*60*24)

async def get_current_user_id(request: Request) -> int:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    payload = decode_token(token)
    return int(payload.get('sub'))

# --- Fernet helpers (para guardar pass IMAP cifrada si seteas FERNET_SECRET) ---
_FERNET = None
def get_fernet():
    global _FERNET
    if _FERNET is None:
        key = os.getenv('FERNET_SECRET')
        if not key:
            return None
        _FERNET = Fernet(key)
    return _FERNET

def fernet_encrypt(text: str) -> str:
    f = get_fernet()
    return f.encrypt(text.encode()).decode() if f else text

def fernet_decrypt(token: str) -> str:
    f = get_fernet()
    if not f:
        return token
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return ''
