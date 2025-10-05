# app/main.py
import os, re
from datetime import datetime
from pathlib import Path
from importlib import import_module

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
    decode_token,
    COOKIE_NAME,
)
from app.models import User

# =========================
# Instancia de la app
# =========================
app = FastAPI(title="AlertTrail API", version="1.0.0")

DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"))

# -------- Middleware debug auth: log de cookies --------
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

# ========= Forzar www.alerttrail.com =========
@app.middleware("http")
async def force_www(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host == "alerttrail.com":  # apex -> www
        url = request.url.replace(netloc="www.alerttrail.com")
        return RedirectResponse(str(url), status_code=308)
    return await call_next(request)

# ========= Redirigir /auth/register a /register ==========
@app.middleware("http")
async def redirect_auth_register_mw(request: Request, call_next):
    path = request.url.path.rstrip("/")
    if path == "/auth/register":
        ctype = (request.headers.get("content-type") or "").lower()
        if request.method == "GET":
            return RedirectResponse("/register", status_code=302)
        if request.method in ("POST", "PUT", "PATCH") and not ctype.startswith("application/json"):
            return RedirectResponse("/register", status_code=307)
    return await call_next(request)

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

# === Usuario opcional ===
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

# =========================
# Montaje de routers
# =========================
ROUTER_MODULES = [
    "orgs", "stats", "payments", "alerts", "rules", "reports",
    "admin", "admin_metrics", "analysis", "auth", "billing",
    "mail", "profile", "push",
]
for name in ROUTER_MODULES:
    try:
        mod = import_module(f"app.routers.{name}")
        app.include_router(mod.router)
    except Exception as e:
        print(f"[routers] No pude cargar {name}: {e}")
        import traceback
        traceback.print_exc()

# --- router de políticas / términos ---
try:
    from app.routers import legal
    app.include_router(legal.router)
    print("[routers] legal montado OK")
except Exception as e:
    print(f"[routers] No pude cargar legal: {e}")

# --- NUEVOS: mail de prueba y verificación por email ---
try:
    from app.routers import debug_mail
    app.include_router(debug_mail.router)
    print("[routers] debug_mail montado OK")
except Exception as e:
    print(f"[routers] No pude cargar debug_mail: {e}")

try:
    from app.routers import auth_email_verification
    app.include_router(auth_email_verification.router)
    print("[routers] auth_email_verification montado OK")
except Exception as e:
    print(f"[routers] No pude cargar auth_email_verification: {e}")

# --- Fallback si /mail/alerts/unread_count no existe (evita 404 en el dashboard) ---
if not any(isinstance(r, APIRoute) and r.path == "/mail/alerts/unread_count" for r in app.routes):
    @app.get("/mail/alerts/unread_count")
    def _fb_unread_count():
        # Devolvemos ambas claves para compatibilidad con frontends distintos
        return {"unread": 0, "count": 0}

try:
    from app.routers import auth_email_verification_web
    app.include_router(auth_email_verification_web.router)
    print("[routers] auth_email_verification_web montado OK")
except Exception as e:
    print(f"[routers] No pude cargar auth_email_verification_web: {e}")

# --- Montaje explícito de mail (línea de vida si falló en el bucle) ---
try:
    from app.routers import mail
    app.include_router(mail.router)
    print("[routers] mail montado OK (fallback explícito)")
except Exception as e:
    print(f"[routers] ERROR montando mail (explícito): {e}")
    import traceback
    traceback.print_exc()

# ===== Alias mínimo para Suscripciones (arregla /admin/subscriptions 404) =====
@app.get("/admin/subscriptions", include_in_schema=False)
def _alias_admin_subscriptions():
    return RedirectResponse(url="/billing", status_code=302)

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

# Alias clásico
@app.get("/login", include_in_schema=False)
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)

# Compat: POST /login (form antiguo)
@app.post("/login", include_in_schema=False)
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
    if not user or not verify_password(password, hp or ""):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")

    # 👉 Si querés forzar verificación antes del login, descomentá:
    # if hasattr(user, "email_verified") and not bool(getattr(user, "email_verified", False)):
    #     raise HTTPException(status_code=401, detail="Debés verificar tu email antes de ingresar")

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

    user = User()
    safe_fields = [
        ("name", (name or "").strip() or "Usuario"),
        ("email", email_norm),
        ("role", "user"),
        ("plan", "FREE"),
        ("created_at", datetime.utcnow()),
    ]
    for field, value in safe_fields:
        if hasattr(user, field):
            setattr(user, field, value)

    pw_hash = get_password_hash(password)
    if hasattr(user, "hashed_password"):
        setattr(user, "hashed_password", pw_hash)
    elif hasattr(user, "password_hash"):
        setattr(user, "password_hash", pw_hash)
    elif hasattr(user, "password"):
        setattr(user, "password", pw_hash)
    else:
        raise HTTPException(status_code=500, detail="Modelo User no tiene un campo de contraseña válido")

    db.add(user); db.commit(); db.refresh(user)

    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": getattr(user, "email", email_norm)})
    return r

@app.get("/logout")
def logout(_response: Response):
    r = RedirectResponse(url="/")
    clear_access_cookie(r)
    return r

# === Dashboard (versión robusta con fallback si falta el template) ===
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    # 1) Autenticación robusta (redirige si no hay cookie válida)
    try:
        user = get_current_user_cookie(request, db)
    except HTTPException as e:
        if e.status_code in (401, 403):
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        raise

    role = (getattr(user, "role", "") or "").lower()
    is_admin = (role == "admin") or truthy(getattr(user, "is_admin", False)) or truthy(getattr(user, "is_superuser", False))
    is_org_admin = truthy(getattr(user, "is_org_admin", False))

    user_ctx = {
        "name": (getattr(user, "name", None) or getattr(user, "email", "Usuario")),
        "email": getattr(user, "email", ""),
        "plan": (getattr(user, "plan", None) or "FREE").upper(),
        "is_org_admin": is_org_admin,
        "org_id": getattr(user, "org_id", None),
    }

    try:
        resp = templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "current_user": user, "user": user_ctx, "is_admin": is_admin}
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except TemplateNotFound:
        html = f"""<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>Dashboard</h1>
          <p>Hola, {user_ctx['name']}.</p>
          <p>No encontré <code>dashboard.html</code>. Mostrando vista mínima.</p>
          <ul>
            <li>Email: {user_ctx['email']}</li>
            <li>Plan: {user_ctx['plan']}</li>
          </ul>
          <p><a href="/logout">Cerrar sesión</a></p>
        </div>"""
        return HTMLResponse(html)

# === Fallbacks de login si faltan ===
def _route_exists(path: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == path for r in app.routes)

def _route_has_method(path: str, method: str) -> bool:
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path:
            if r.methods and method.upper() in r.methods:
                return True
    return False

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

if not _route_has_method("/auth/login", "POST"):
    @app.post("/auth/login", include_in_schema=False)
    def _fb_auth_login_post(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")

        # 👉 Para forzar verificación previa al login, descomentá:
        # if hasattr(user, "email_verified") and not bool(getattr(user, "email_verified", False)):
        #     raise HTTPException(status_code=401, detail="Debés verificar tu email antes de ingresar")

        r = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        return r

if not _route_exists("/auth/login/web"):
    @app.post("/auth/login/web", include_in_schema=False)
    def _fb_auth_login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")

        # 👉 Para forzar verificación previa al login, descomentá:
        # if hasattr(user, "email_verified") and not bool(getattr(user, "email_verified", False)):
        #     raise HTTPException(status_code=401, detail="Debés verificar tu email antes de ingresar")

        r = RedirectResponse(url="/dashboard", status_code=303)
        issue_access_cookie(r, {"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        return r

# === Handlers globales ===
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    """
    Solo los 401 (no autenticado) redirigen al login.
    Los 403 (no autorizado) muestran una página HTML para evitar loops de login.
    """
    accept = (request.headers.get("accept") or "")
    wants_html = "text/html" in accept

    # 401 → login
    if exc.status_code == 401 and wants_html:
        path = request.url.path or ""
        if not path.startswith("/auth"):
            return RedirectResponse(url="/auth/login", status_code=302)

    # 403 → página simple (sin redirigir)
    if exc.status_code == 403 and wants_html:
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<div style='font-family:system-ui;padding:24px'>"
            "<h2>Acceso denegado</h2>"
            f"<p style='color:#475569'>{exc.detail or 'No autorizado'}</p>"
            "<p><a href='/dashboard' style='color:#2563eb;text-decoration:none'>&larr; Volver</a></p>"
            "</div>"
        )
        return HTMLResponse(body, status_code=403)

    # Resto → JSON
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

# === Scheduler opcional ===
try:
    from app.services.scheduler import start_background_scheduler
    start_background_scheduler()
except Exception:
    pass


# Fallback opcional para /mail/scanner → /mail
from fastapi.responses import RedirectResponse
@app.get("/mail/scanner", include_in_schema=False)
def _scanner_fallback():
  return RedirectResponse(url="/mail", status_code=302)

