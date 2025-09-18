# app/routers/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, Response, Form, status, Request, Query
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

# ----------------------- Schemas -----------------------
class RegisterIn(BaseModel):
    name: str | None = None
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

# ----------------------- Utils -------------------------
def _hash_from_user(u: models.User) -> str:
    """
    Devuelve el hash de contraseña guardado, soportando nombres de columna
    comunes según distintos esquemas previos.
    """
    return (
        getattr(u, "hashed_password", None)
        or getattr(u, "password_hash", None)
        or getattr(u, "password", None)
        or ""
    )

# utils arriba del archivo
def _hash_from_user(u: models.User) -> str:
    return (
        getattr(u, "hashed_password", None)
        or getattr(u, "password_hash", None)
        or getattr(u, "password", None)
        or ""
    )

# --- helper para elegir el hash correcto del usuario ---
def _hash_from_user(u: models.User) -> str:
    return (
        getattr(u, "hashed_password", None)
        or getattr(u, "password_hash", None)
        or getattr(u, "password", None)
        or ""
    )

# --- POST /auth/login/web SIN Form(...) ---
@router.post("/login/web", include_in_schema=False)
async def login_web(request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        print("[auth] handling /auth/login/web (auth.py, no Form)")

        # Acepta form-url-encoded, multipart o JSON (por si tu template usa fetch)
        ctype = (request.headers.get("content-type") or "").lower()
        email = password = None

        if ctype.startswith("application/json"):
            body = await request.json()
            if isinstance(body, dict):
                email = body.get("email")
                password = body.get("password")
        else:
            form = await request.form()  # para x-www-form-urlencoded y multipart
            email = form.get("email")
            password = form.get("password")

        if not email or not password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Faltan email/password.")

        email_norm = email.strip().lower()
        user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
        if not user or not verify_password(password, _hash_from_user(user)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

        resp = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(resp, {"sub": str(user.id)})
        return resp

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return HTMLResponse(f"<pre>Login error: {e!r}</pre>", status_code=500)

# GET /auth/login/web -> redirigir siempre al form
@router.get("/login/web", include_in_schema=False)
def login_web_get():
    return RedirectResponse(url="/auth/login", status_code=302)


# ----------------------- Páginas -----------------------
# LOGIN HTML: SIEMPRE 200, SIN REDIRECCIÓN
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# ----------------------- Login API ---------------------
# LOGIN JSON: setea cookie con sub = user.id
@router.post("/login", response_model=dict)
def login_json(payload: LoginIn, db: Session = Depends(get_db)):
    email_norm = payload.email.strip().lower()
    user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    if not user or not verify_password(payload.password, _hash_from_user(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    resp = JSONResponse({"ok": True, "redirect": "/dashboard"})
    issue_access_cookie(resp, {"sub": str(user.id)})
    return resp

# LOGIN WEB (form)
@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()
    user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    if not user or not verify_password(password, _hash_from_user(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")
    resp = RedirectResponse(url="/dashboard", status_code=303)
    issue_access_cookie(resp, {"sub": str(user.id)})
    return resp

# ----------------------- Logout / Clear ----------------
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

# ----------------------- Me ----------------------------
@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """
    Lee claims del JWT (cookie) y devuelve datos del usuario real desde la DB.
    """
    claims = get_current_user_cookie(request, db)  # devuelve dict con 'sub' si usas issue_access_cookie
    if not claims:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 'sub' = id del usuario
    try:
        uid = int(claims.get("sub")) if isinstance(claims, dict) else getattr(claims, "id", None)
    except Exception:
        uid = getattr(claims, "id", None)

    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(models.User).get(uid) if hasattr(db.query(models.User), "get") else db.get(models.User, uid)  # compat SA 1.x/2.x
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "name": getattr(user, "name", ""),
        "email": getattr(user, "email", ""),
        "plan": getattr(user, "plan", "FREE"),
        "role": getattr(user, "role", None),
        "is_admin": bool(getattr(user, "is_admin", False)),
    }

# ----------------------- Register ----------------------
@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email_norm = data.email.strip().lower()
    exists = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    user = models.User(
        email=email_norm,
        name=(data.name or ""),
        plan=getattr(models.User, "plan", None) and "FREE" or None,  # setea si existe la columna
    )
    pwd = get_password_hash(data.password)
    if hasattr(user, "hashed_password"):   user.hashed_password = pwd
    if hasattr(user, "password_hash"):     user.password_hash   = pwd
    if hasattr(user, "role") and not getattr(user, "role", None):
        user.role = "user"
    db.add(user); db.commit(); db.refresh(user)
    return {"id": user.id, "email": user.email, "name": user.name, "plan": getattr(user, "plan", "FREE")}

# ----------------- Reset admin por ENV (temporal) -----
@router.post("/_force_admin_reset", include_in_schema=True)
def _force_admin_reset(secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"), db: Session = Depends(get_db)):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    email = os.getenv("ADMIN_EMAIL"); password = os.getenv("ADMIN_PASS"); name = os.getenv("ADMIN_NAME", "Admin")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Faltan ADMIN_EMAIL o ADMIN_PASS")
    email_norm = email.strip().lower()
    pwd_hash = get_password_hash(password)
    user = db.query(models.User).filter(func.lower(models.User.email) == email_norm).first()
    if user:
        if hasattr(user, "hashed_password"): user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):   user.password_hash   = pwd_hash
        if hasattr(user, "is_admin"):        user.is_admin = True
        if hasattr(user, "is_active"):       user.is_active = True
        if not getattr(user, "name", "") and name: user.name = name
        action = "actualizado"
    else:
        user = models.User(email=email_norm, name=name)
        if hasattr(user, "hashed_password"): user.hashed_password = pwd_hash
        if hasattr(user, "password_hash"):   user.password_hash   = pwd_hash
        if hasattr(user, "is_admin"):        user.is_admin = True
        if hasattr(user, "is_active"):       user.is_active = True
        db.add(user); action = "creado"
    db.commit()
    return {"ok": True, "admin": email_norm, "action": action}

# ----------------------- Debug temporal ----------------
@router.get("/_debug_auth", include_in_schema=True)
def _debug_auth(email: EmailStr, password: str, secret: str = Query(..., description="ADMIN_SETUP_SECRET o JWT_SECRET"), db: Session = Depends(get_db)):
    setup_secret = os.getenv("ADMIN_SETUP_SECRET") or os.getenv("JWT_SECRET") or ""
    if not setup_secret or secret != setup_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    email_norm = email.strip().lower()
    users = db.query(models.User).filter(func.lower(models.User.email) == email_norm).all()
    out = []
    for u in users:
        hp = getattr(u, "hashed_password", None)
        ph = getattr(u, "password_hash", None)
        pw = getattr(u, "password", None)
        ok_h = verify_password(password, hp) if hp else None
        ok_p = verify_password(password, ph) if ph else None
        ok_w = verify_password(password, pw) if pw else None
        out.append({
            "id": u.id,
            "email": u.email,
            "hashed_password_len": len(hp or "") if hp else None,
            "password_hash_len": len(ph or "") if ph else None,
            "password_len": len(pw or "") if pw else None,
            "verify_hashed_password": ok_h,
            "verify_password_hash": ok_p,
            "verify_password": ok_w
        })
    return {"count": len(users), "results": out}
