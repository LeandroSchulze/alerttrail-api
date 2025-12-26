from fastapi import Request, HTTPException, status
from jose import jwt, JWTError
import os

JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SESSION_SECRET"))
JWT_ALGORITHM = os.getenv("JWT_ALG", "HS256")
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")


def get_token_from_request_or_header(request: Request) -> str:
    # 1️⃣ Authorization header
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]

    # 2️⃣ Cookie (web)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
    )


def get_current_user_payload(request: Request) -> dict:
    token = get_token_from_request_or_header(request)
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )
