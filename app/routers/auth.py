# app/routers/auth.py
import os
from fastapi import (
    APIRouter, Depends, HTTPException, Response, status,
    Request, Query
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
    issue_access_cookie,
    get_current_user_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

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

# LOGIN HTML (siempre 200, sin redirecciones raras)
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# LOGIN JSON (setea cookie con sub=user.id)
@router.post("/login", response_model=dict)
def login_json(payload: LoginIn, db: Session = Depends(get_db)):
    email_norm = payload.email.strip().lower()
    user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    hp = _pwd_hash_from_user(user)
    if not user or not verify_password(payload.password, hp):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    resp = JSONResponse({"ok": True})
    issue_access_cookie(resp, {"sub": str(user.id)})
    return resp

# GET /auth/login/web -> redirige al form (evita 500 en GET)
@router.get("/login/web", include_in_schema=False)
def login_web_get():
    return RedirectResponse(url="/auth/login", status_code=302)

# POST /auth/login/web (form o JSON) robusto y con logs
@router.post("/login/web", include_in_schema=False)
async def login_web(request: Request, response: Response, db: Session = Depends(get_db)):
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
            # soporta application/x-www-form-urlencoded y multipart/form-data
            form = await request.form()
            email = form.get("email")
            password = form.get("password")

        if not email or not password:
            raise HTTPException(status_code=400, detail="Faltan email/password.")

        email_norm = email.strip().lower()
        user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
        hp = _pwd_hash_from_user(user)
        if not user or not verify_password(password, hp):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas.")

        resp = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(resp, {"sub": str(user.id)})
        return resp

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return HTMLResponse(f"<pre>Login error: {e!r}</pre>", status_code=500)

# LOGOUT + CLEAR
@router.get("/logout")
def logout_get():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    return resp

@router.post("/logout")
def logout_post():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    return resp

@router.get("/clear", include_in_schema=False)
def clear_cookie():
    resp = PlainTextResponse("ok")
    resp.delete_cookie("access_token", path="/")
    return resp

# ME
@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "name": getattr(current, "name", ""),
        "email": getattr(current, "email", ""),
        "plan": getattr(current, "plan", "FREE"),
    }

# REGISTER JSON (opcional si usás /register en main)
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

# Reset admin por ENV (temporal)
@router.post("/_force_admin_reset", include_in_schema=True)
def _force_admin_reset(secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"), db: Session = Depends(get_db)):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    email = os.getenv("ADMIN_EMAIL"); password = os.getenv("ADMIN_PASS"); name = os.getenv("ADMIN_NAME", "Admin")
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

# Debug temporal
@router.get("/_debug_auth", include_in_schema=True)
def _debug_auth(email: EmailStr, password: str, secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"), db: Session = Depends(get_db)):
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
