# app/routers/auth.py
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User
from app.i18n import get_lang

from app.security import (
    issue_access_cookie,
    clear_access_cookie,
    create_access_token,
    verify_password,
    get_password_hash,
    get_current_user_cookie,
)

# Si billing_guard existe como archivo, se usa desde ahí (NO desde app.security como "package")
try:
    from app.security.billing_guard import normalize_user_plan  # type: ignore
except Exception:
    # fallback: si tu normalize_user_plan quedó en app.security (viejo), intentamos
    try:
        from app.security import normalize_user_plan  # type: ignore
    except Exception:
        normalize_user_plan = None  # type: ignore


router = APIRouter(prefix="/auth", tags=["auth"])

DEBUG_AUTH = os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on")


def _templates(request: Request):
    """
    Usa SIEMPRE los templates del main.py (app.state.templates),
    que ya tienen templates.env.globals["t"] = t
    """
    tpl = getattr(request.app.state, "templates", None)
    if tpl is None:
        raise RuntimeError("templates no inicializado en app.state (main.py)")
    return tpl


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_get(request: Request):
    tpl = _templates(request)
    lang = get_lang(request)
    return tpl.TemplateResponse("login.html", {"request": request, "lang": lang})


@router.post("/login/web", include_in_schema=False)
def login_web(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = (email or "").strip().lower()

    user = db.query(User).filter(func.lower(User.email) == email).first()

    if not user or not verify_password(password, user.hashed_password):
        tpl = _templates(request)
        lang = get_lang(request)
        return tpl.TemplateResponse(
            "login.html",
            {"request": request, "lang": lang, "error": "Credenciales inválidas"},
            status_code=400,
        )

    # Normalizar plan si existe
    if normalize_user_plan:
        try:
            normalize_user_plan(db, user)
        except Exception:
            pass

    token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": getattr(user, "role", None),
            "plan": getattr(user, "plan", None),
        }
    )

    r = RedirectResponse("/dashboard", status_code=303)

    # ✅ CLAVE: borrar cookies previas (host-only vs domain) para evitar loop
    clear_access_cookie(r, request=request)
    issue_access_cookie(r, token, request=request)

    if DEBUG_AUTH:
        try:
            print(f"[auth][login_web] ok email={user.email} id={user.id}")
        except Exception:
            pass

    return r


@router.post("/login", response_class=JSONResponse)
def login_api(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Login API (si lo usás desde JS o integraciones).
    Devuelve JSON, y también setea la cookie.
    """
    email = (email or "").strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")

    if normalize_user_plan:
        try:
            normalize_user_plan(db, user)
        except Exception:
            pass

    token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": getattr(user, "role", None),
            "plan": getattr(user, "plan", None),
        }
    )

    resp = JSONResponse({"ok": True})

    # ✅ idem: limpiar primero
    clear_access_cookie(resp, request=request)
    issue_access_cookie(resp, token, request=request)
    return resp


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    """
    Logout + redirect a /auth/login (como pediste).
    """
    r = RedirectResponse("/auth/login", status_code=303)
    clear_access_cookie(r, request=request)

    # Si estás usando SessionMiddleware, limpiamos también.
    try:
        request.session.clear()
    except Exception:
        pass

    return r


@router.get("/me", response_class=JSONResponse)
def me(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    if normalize_user_plan:
        try:
            normalize_user_plan(db, user)
        except Exception:
            pass

    return {
        "id": user.id,
        "email": user.email,
        "name": getattr(user, "name", None),
        "plan": getattr(user, "plan", "FREE"),
        "is_pro": bool(getattr(user, "is_pro", False)),
        "pro_expires_at": getattr(user, "pro_expires_at", None).isoformat()
        if getattr(user, "pro_expires_at", None)
        else None,
    }


@router.get("/debug", include_in_schema=False)
def auth_debug(request: Request):
    # Evitamos referenciar COOKIE_NAME si no existe.
    cookie_name = "access_token"
    try:
        cookie_name = os.getenv("COOKIE_NAME") or cookie_name
    except Exception:
        pass

    return {
        "host": request.headers.get("host"),
        "x_forwarded_host": request.headers.get("x-forwarded-host"),
        "x_forwarded_proto": request.headers.get("x-forwarded-proto"),
        "cookies": dict(request.cookies),
        "cookie_name": cookie_name,
    }


@router.post("/register", response_class=JSONResponse)
def register(
    email: str = Form(...),
    password: str = Form(...),
    name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Registro simple (por si lo tenés habilitado).
    Si no lo usás, igual no molesta.
    """
    email = (email or "").strip().lower()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email y password requeridos")

    exists = db.query(User).filter(func.lower(User.email) == email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    u = User(
        email=email,
        hashed_password=get_password_hash(password),
    )
    if hasattr(u, "name") and name:
        u.name = name

    if hasattr(u, "plan"):
        u.plan = "FREE"
    if hasattr(u, "is_pro"):
        u.is_pro = False

    db.add(u)
    db.commit()
    db.refresh(u)

    return {"ok": True, "id": u.id}
