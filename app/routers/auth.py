# app/routers/auth.py
import os
from fastapi import (
    APIRouter, Depends, HTTPException, Response, status, Request, Query
)
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app import models
from app.security import (
    get_password_hash,
    verify_password,
    issue_access_cookie,        # >>> debe setear la cookie en ESTA response
    get_current_user_cookie,    # >>> tu dependencia que lee cookie y devuelve User
)

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Config cookies (debe coincidir con app.security) ---
COOKIE_NAME   = os.getenv("COOKIE_NAME", "access_token")
COOKIE_DOMAIN = (os.getenv("COOKIE_DOMAIN", "") or "").strip()  # ej: ".alerttrail.com" o vacío
COOKIE_PATH   = "/"

# --- Templates ---
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ====== Schemas ======
class RegisterIn(BaseModel):
    name: str | None = None
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str


# ====== Helpers ======
def _pwd_hash_from_user(u) -> str:
    """Devuelve el hash de contraseña desde el modelo sin tocar .password."""
    if not u:
        return ""
    for attr in ("hashed_password", "password_hash"):
        try:
            v = getattr(u, attr, None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    return ""


# ====== Rutas ======

# LOGIN HTML (200 y sin redirecciones). Evita caché para no “pegarse” en el form.
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    resp = templates.TemplateResponse("login.html", {"request": request, "error": None})
    resp.headers["Cache-Control"] = "no-store"
    return resp


# LOGIN JSON (API). Setea cookie en la MISMA respuesta.
@router.post("/login", response_model=dict)
def login_json(payload: LoginIn, db: Session = Depends(get_db)):
    email_norm = payload.email.strip().lower()
    user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    hp = _pwd_hash_from_user(user)
    if not user or not verify_password(payload.password, hp):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    resp = JSONResponse({"ok": True})
    # payload mínimo estándar JWT: sub + email
    issue_access_cookie(resp, {"sub": str(user.id), "email": user.email})
    return resp


# GET /auth/login/web -> manda al form (comodín para GET)
@router.get("/login/web", include_in_schema=False)
def login_web_get():
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)


# POST /auth/login/web (form o JSON). **El redirect que vuelve al dashboard ya lleva la cookie.**
@router.post("/login/web", include_in_schema=False)
async def login_web(request: Request, db: Session = Depends(get_db)):
    try:
        print("[auth] handling /auth/login/web (auth.py)")
        ctype = (request.headers.get("content-type") or "").lower()
        email = password = None

        if ctype.startswith("application/json"):
            body = await request.json()
            if isinstance(body, dict):
                email = body.get("email")
                password = body.get("password")
        else:
            form = await request.form()  # x-www-form-urlencoded o multipart/form-data
            email = form.get("email")
            password = form.get("password")

        if not email or not password:
            raise HTTPException(status_code=400, detail="Faltan email/password.")

        email_norm = email.strip().lower()
        user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
        hp = _pwd_hash_from_user(user)
        if not user or not verify_password(password, hp):
            # Volver al login con querystring de error (opcional)
            return RedirectResponse(url="/auth/login?err=cred", status_code=status.HTTP_303_SEE_OTHER)

        # Redirige al dashboard y **setea la cookie en ESTA response**
        resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        issue_access_cookie(resp, {"sub": str(user.id), "email": user.email})
        # Evita que el navegador guarde cache de la respuesta del login
        resp.headers["Cache-Control"] = "no-store"
        return resp

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return HTMLResponse(f"<pre>Login error: {e!r}</pre>", status_code=500)

import re

# ... ya creaste resp = RedirectResponse(...); y llamaste a issue_access_cookie(resp, claims)
if os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"):
    sc = resp.headers.get("set-cookie", "")
    masked = re.sub(r"(access_token=)([^;]+)", r"\1***", sc)
    print(
        "[auth][debug] POST /auth/login/web:",
        f"host={request.headers.get('host')}",
        f"cookie-domain={os.getenv('COOKIE_DOMAIN','') or '(host-only)'}",
        f"set-cookie={masked}",
    )


# LOGOUT (GET/POST) -> borra cookie con el MISMO nombre/dominio/path
@router.get("/logout")
def logout_get():
    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if COOKIE_DOMAIN:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, domain=COOKIE_DOMAIN)
    else:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@router.post("/logout")
def logout_post():
    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if COOKIE_DOMAIN:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, domain=COOKIE_DOMAIN)
    else:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# Limpieza manual (debug)
@router.get("/clear", include_in_schema=False)
def clear_cookie():
    resp = PlainTextResponse("ok")
    if COOKIE_DOMAIN:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, domain=COOKIE_DOMAIN)
    else:
        resp.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return resp


# ME (devuelve datos del usuario autenticado)
@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = get_current_user_cookie(request, db)  # debe devolver objeto User
    return {
        "name": getattr(current, "name", ""),
        "email": getattr(current, "email", ""),
        "plan": getattr(current, "plan", "FREE"),
    }


# REGISTER JSON
@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email_norm = data.email.strip().lower()
    exists = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    user = models.User(email=email_norm, name=(data.name or ""), plan="FREE")
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):
        user.password_hash = pwd
    if hasattr(user, "hashed_password"):
        user.hashed_password = pwd
    db.add(user); db.commit(); db.refresh(user)
    return {"id": user.id, "email": user.email, "name": user.name, "plan": getattr(user, "plan", "FREE")}


# Reset admin por ENV (temporal, borralo cuando ya no lo necesites)
@router.post("/_force_admin_reset", include_in_schema=True)
def _force_admin_reset(
    secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"),
    db: Session = Depends(get_db)
):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")

    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD")
    name = os.getenv("ADMIN_NAME", "Admin")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Faltan ADMIN_EMAIL o ADMIN_PASS")

    pwd_hash = get_password_hash(password)
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        if hasattr(user, "hashed_password"): user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):   user.password_hash = pwd_hash
        if hasattr(user, "is_admin"):        user.is_admin = True
        if hasattr(user, "is_active"):       user.is_active = True
        if not getattr(user, "name", "") and name: user.name = name
        action = "actualizado"
    else:
        user = models.User(email=email, name=name)
        if hasattr(user, "hashed_password"): user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):   user.password_hash = pwd_hash
        if hasattr(user, "is_admin"):        user.is_admin = True
        if hasattr(user, "is_active"):       user.is_active = True
        db.add(user); action = "creado"
    db.commit()
    return {"ok": True, "admin": email, "action": action}


# Debug temporal (verifica hash vs password)
@router.get("/_debug_auth", include_in_schema=True)
def _debug_auth(
    email: EmailStr,
    password: str,
    secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"),
    db: Session = Depends(get_db)
):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    users = db.query(models.User).filter(func.lower(models.User.email) == email.lower()).all()
    out = []
    for u in users:
        hp = getattr(u, "hashed_password", None)
        ph = getattr(u, "password_hash", None)
        ok_h = verify_password(password, hp) if hp else None
        ok_p = verify_password(password, ph) if ph else None
        out.append({
            "id": u.id, "email": u.email,
            "hashed_password_len": len(hp or "") if hp else None,
            "password_hash_len": len(ph or "") if ph else None,
            "verify_hashed_password": ok_h,
            "verify_password_hash": ok_p
        })
    return {"count": len(users), "results": out}
