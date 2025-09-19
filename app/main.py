# app/main.py
import os, re
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy import func
from jinja2 import TemplateNotFound

from app.database import SessionLocal
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    get_password_hash,
    verify_password,
    clear_access_cookie,
)
from app.models import User

app = FastAPI(title="AlertTrail API", version="1.0.0")

DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1","true","yes","on"))

# -------- Middleware debug auth: log de cookies en /auth y /dashboard --------
@app.middleware("http")
async def _auth_debug_mw(request: Request, call_next):
    if DEBUG_AUTH and request.url.path in ("/auth/login/web", "/auth/login", "/dashboard", "/_cookie_test_set"):
        ck = request.headers.get("cookie")
        print(
            "[auth][debug][in]",
            f"path={request.url.path}",
            f"host={request.headers.get('host')}",
            f"has_cookie={bool(ck)}",
            f"cookie_len={len(ck or '')}",
        )
    resp = await call_next(request)
    if DEBUG_AUTH and request.url.path in ("/auth/login/web", "/auth/login", "/login", "/register", "/_cookie_test_set"):
        sc = resp.headers.get("set-cookie", "")
        masked = re.sub(r"(access_token=)([^;]+)", r"\1***", sc)
        print("[auth][debug][out]", f"path={request.url.path}", f"set-cookie={masked or '<NONE>'}")
    return resp
# -----------------------------------------------------------------------------


# ---- Debug: ver claims del JWT actual ----
@app.get("/_cookie_decode", include_in_schema=False)
def _cookie_decode(request: Request):
    from app.security import COOKIE_NAME, decode_token
    tok = request.cookies.get(COOKIE_NAME)
    out = {"has_cookie": bool(tok), "len": len(tok or "")}
    try:
        out["claims"] = decode_token(tok) if tok else None
    except Exception as e:
        out["error"] = repr(e)
    return out

# ---- Debug: borrar cookie de acceso ----
@app.get("/_cookie_clear", include_in_schema=False)
def _cookie_clear():
    r = RedirectResponse(url="/auth/login", status_code=303)
    from app.security import clear_access_cookie
    clear_access_cookie(r)
    return r
    

# ========= Middleware: forzar www.alerttrail.com (usa 308 para conservar POST) =========
@app.middleware("http")
async def force_www(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host == "alerttrail.com":  # apex -> www
        url = request.url.replace(netloc="www.alerttrail.com")
        # 308 Permanent Redirect preserva método y body (POST no se convierte en GET)
        return RedirectResponse(str(url), status_code=308)
    return await call_next(request)
# =======================================================================================

# === Static & Templates ===
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
REPORTS_DIR   = "app/reports"   if Path("app/reports").exists()   else "reports"

Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# === DB dep ===
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# === Usuario opcional: NUNCA lanza excepción ===
def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    try:
        return get_current_user_cookie(request, db)
    except Exception:
        return None

# === OpenAPI con cookieAuth ===
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="API de AlertTrail",
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey", "in": "cookie", "name": "access_token"
    }
    for path in schema.get("paths", {}).values():
        for method in path.values():
            if isinstance(method, dict):
                method.setdefault("security", [{"cookieAuth": []}])
    app.openapi_schema = schema
    return schema
app.openapi = custom_openapi

# === Helpers ===
def db_get(db: Session, model, pk):
    try:
        return db.get(model, pk)
    except Exception:
        return db.query(model).get(pk)

def truthy(v):
    if isinstance(v, bool): return v
    if isinstance(v, int):  return v == 1
    if isinstance(v, str):  return v.strip().lower() in {"1","true","yes","y","on"}
    return False

# === Rutas públicas ===
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    try:
        return templates.TemplateResponse("landing.html", {"request": request})
    except TemplateNotFound:
        html = """<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>AlertTrail</h1>
          <p>Bienvenido. <a href="/auth/login">Iniciar sesión</a> · <a href="/register">Crear cuenta</a> · <a href="/docs">API Docs</a></p>
        </div>"""
        return HTMLResponse(html)

# Alias clásico: /login -> /auth/login
@app.get("/login", include_in_schema=False)
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)

# Compatibilidad: POST /login (formulario antiguo)  **cookie en el mismo redirect**
@app.post("/login", include_in_schema=False)
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
    if not user or not verify_password(password, hp or ""):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    return r

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    try:
        return templates.TemplateResponse("register.html", {"request": request})
    except TemplateNotFound:
        html = """<!doctype html><meta charset='utf-8'>
        <form method="post" action="/register" style="font-family:system-ui;padding:24px;display:grid;gap:8px;max-width:320px">
          <h2>Crear cuenta</h2>
          <input name="name" placeholder="Nombre" required>
          <input name="email" type="email" placeholder="Email" required>
          <input name="password" type="password" placeholder="Contraseña" required>
          <button>Registrarme</button>
        </form>"""
        return HTMLResponse(html)

# **cookie en el mismo redirect**
@app.post("/register")
def register_action(
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    if db.query(User).filter(func.lower(User.email) == email_norm).first():
        raise HTTPException(status_code=400, detail="Ese email ya está registrado")
    user = User(
        name=(name or "").strip() or "Usuario",
        email=email_norm,
        hashed_password=get_password_hash(password),
        role="user",
        plan="FREE",
        created_at=datetime.utcnow(),
    )
    db.add(user); db.commit(); db.refresh(user)
    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    return r

# Logout con borrado correcto de cookie
@app.get("/logout")
def logout(_response: Response):
    r = RedirectResponse(url="/")
    clear_access_cookie(r)
    return r

# === Dashboard protegido ===
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user_cookie(request, db)
    role = (getattr(user, "role", "") or "").lower()
    is_admin = (role == "admin") or truthy(getattr(user, "is_admin", False)) or truthy(getattr(user, "is_superuser", False))
    resp = templates.TemplateResponse("dashboard.html", {"request": request, "current_user": user, "is_admin": is_admin})
    resp.headers["Cache-Control"] = "no-store"
    return resp

# === Endpoints de diagnóstico de cookie ===
@app.get("/_cookie_test_set", include_in_schema=False)
def _cookie_test_set():
    r = RedirectResponse(url="/_cookie_test_get", status_code=303)
    # setea una cookie simple de prueba (sin JWT)
    from app.security import COOKIE_NAME
    r.set_cookie(
        key=COOKIE_NAME,
        value="test-cookie",
        path="/",
        secure=True,          # Render usa HTTPS
        httponly=True,
        samesite="lax",
        domain=(os.getenv("COOKIE_DOMAIN") or None),  # host-only si no hay env
    )
    return r

@app.get("/_cookie_test_get", include_in_schema=False)
def _cookie_test_get(request: Request):
    return {
        "host": request.headers.get("host"),
        "has_cookie_header": bool(request.headers.get("cookie")),
        "cookies": list(request.cookies.keys()),
        "cookie_value_sample": (request.cookies.get("access_token") or "")[:16]
    }

# === Montar routers ===
try:
    from app.routers import auth as auth_router_mod
    app.include_router(auth_router_mod.router)          # /auth/*
except Exception as e:
    print("No pude cargar app.routers.auth:", e)

try:
    from app.routers import analysis as analysis_router_mod
    app.include_router(analysis_router_mod.router)      # /analysis/*
except Exception as e:
    print("No pude cargar app.routers.analysis:", e)

try:
    from app.routers import mail as mail_router_mod
    app.include_router(mail_router_mod.router)          # /mail/*
except Exception as e:
    print("No pude cargar app.routers.mail:", e)

try:
    from app.routers import admin as admin_router_mod
    app.include_router(admin_router_mod.router)         # /stats, etc.
except Exception as e:
    print("No pude cargar app.routers.admin:", e)

# === Fallbacks por si /auth/* no quedó montado ===
def _route_exists(path: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == path for r in app.routes)

def _route_has_method(path: str, method: str) -> bool:
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path:
            if r.methods and method.upper() in r.methods:
                return True
    return False

# Fallback GET /auth/login
if not _route_has_method("/auth/login", "GET"):
    @app.get("/auth/login", include_in_schema=False, response_class=HTMLResponse)
    def _fb_auth_login_get(request: Request):
        try:
            resp = templates.TemplateResponse("login.html", {"request": request})
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except TemplateNotFound:
            html = """<!doctype html><meta charset='utf-8'>
            <title>Login — AlertTrail</title>
            <form method="post" action="/auth/login/web"
                  style="font-family:system-ui;padding:24px;display:grid;gap:8px;max-width:320px">
              <h2>Iniciar sesión</h2>
              <input name="email" type="email" placeholder="Email" required>
              <input name="password" type="password" placeholder="Contraseña" required>
              <button>Entrar</button>
            </form>"""
            return HTMLResponse(html)

# Fallbacks mínimos para login POST  **cookie en el mismo redirect**
if not _route_has_method("/auth/login", "POST"):
    @app.post("/auth/login", include_in_schema=False)
    def _fb_auth_login_post(
        response: Response,
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db),
    ):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")
        r = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        return r

if not _route_exists("/auth/login/web"):
    @app.post("/auth/login/web", include_in_schema=False)
    def _fb_auth_login_web(
        response: Response,
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db),
    ):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")
        r = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        return r

# === Alias útiles ===
def _exists(p: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == p for r in app.routes)

if _exists("/analysis/generate-pdf") and not _exists("/analysis/generate_pdf"):
    @app.get("/analysis/generate_pdf")
    def _alias_gen_pdf():
        return RedirectResponse(url="/analysis/generate-pdf", status_code=307)

if _exists("/stats") and not _exists("/admin/stats"):
    @app.get("/admin/stats")
    def _alias_admin_stats():
        return RedirectResponse(url="/stats", status_code=307)

if _exists("/mail/scanner") and not _exists("/mail/scan"):
    @app.get("/mail/scan")
    def _alias_mail_scan():
        return RedirectResponse(url="/mail/scanner", status_code=307)
if _exists("/mail/scan") and not _exists("/mail/scanner"):
    @app.get("/mail/scanner")
    def _alias_mail_scanner():
        return RedirectResponse(url="/mail/scan", status_code=307)

# Alias compat: /tasks/mail/poll -> /mail/poll (para cron viejo)
from sqlalchemy.orm import Session as _AliasSession
from fastapi import Depends as _AliasDepends

@app.get("/tasks/mail/poll", include_in_schema=False)
@app.post("/tasks/mail/poll", include_in_schema=False)
def _alias_tasks_mail_poll(secret: str, db: _AliasSession = _AliasDepends(get_db)):
    from app.routers.mail import mail_poll as _mail_poll
    return _mail_poll(secret, db)

# === Handler global: 401/403 HTML -> login (evita loops) ===
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if exc.status_code in (401, 403) and "text/html" in (request.headers.get("accept") or ""):
        path = request.url.path or ""
        if not path.startswith("/auth"):
            return RedirectResponse(url="/auth/login", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

from fastapi.responses import HTMLResponse as _HTMLResponse

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    import traceback; traceback.print_exc()
    if "text/html" in (request.headers.get("accept") or ""):
        return _HTMLResponse(f"<pre>Unhandled error: {exc!r}</pre>", status_code=500)
    return JSONResponse({"detail": repr(exc)}, status_code=500)

# === Health & HEAD ===
@app.get("/health")
def health():
    return {"ok": True}

@app.head("/")
def head_root():
    return Response(status_code=200)

# === Log de rutas al iniciar ===
@app.on_event("startup")
def _log_routes():
    paths = sorted([r.path for r in app.routes if isinstance(r, APIRoute)])
    print("\n=== ROUTES ===")
    for p in paths:
        print(p)
    print("==============\n")
