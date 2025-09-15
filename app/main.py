# app/main.py
import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound

# SQLAlchemy base/engine y dependencia de DB
from app.database import Base, engine, get_db
# Helper: obtiene el usuario desde la cookie JWT
from app.security import get_current_user_cookie

app = FastAPI(title="AlertTrail")

# -------------------------------------------------------------------
# Crear tablas si hiciera falta (no rompe si ya existen)
# -------------------------------------------------------------------
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[main] Aviso al crear tablas: {e}")

# -------------------------------------------------------------------
# Static, Templates y Reports (robusto ante carpetas faltantes)
# -------------------------------------------------------------------
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(APP_DIR)

STATIC_CANDIDATES = [
    os.path.join(APP_DIR, "static"),
    os.path.join(ROOT_DIR, "static"),
]
TEMPLATE_CANDIDATES = [
    os.path.join(APP_DIR, "templates"),
    os.path.join(ROOT_DIR, "templates"),
]

STATIC_DIR = next((p for p in STATIC_CANDIDATES if os.path.isdir(p)), os.path.join(APP_DIR, "static"))
TEMPLATES_DIR = next((p for p in TEMPLATE_CANDIDATES if os.path.isdir(p)), os.path.join(APP_DIR, "templates"))

os.makedirs(STATIC_DIR, exist_ok=True)      # evita RuntimeError si la carpeta no existe
os.makedirs(TEMPLATES_DIR, exist_ok=True)   # idem para templates

REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# -------------------------------------------------------------------
# Inclusión de routers (no explota si alguno no está)
# -------------------------------------------------------------------
def _try_include(module_path: str, attr: str = "router"):
    try:
        module = __import__(module_path, fromlist=[attr])
        r = getattr(module, attr)
        app.include_router(r)
        print(f"[main] Router incluido: {module_path}")
    except Exception as e:
        print(f"[main] (aviso) No se pudo incluir {module_path}: {e}")

_try_include("app.routers.auth")       # /auth/*
_try_include("app.routers.admin")      # /admin/*
_try_include("app.routers.analysis")   # /analysis/*
_try_include("app.routers.mail")       # /mail/*

# -------------------------------------------------------------------
# Rutas base
# -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root():
    # Redirige al dashboard (el dashboard valida cookie y, si falta, envía a /auth/login)
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db=Depends(get_db)):
    """
    Protegido por cookie JWT. Si no hay cookie válida, redirige a /auth/login.
    """
    user = get_current_user_cookie(request, db=db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=302)

    name = getattr(user, "name", "Usuario")
    email = getattr(user, "email", "")
    plan = getattr(user, "plan", "FREE")
    role = getattr(user, "role", None)
    is_admin = getattr(user, "is_admin", False)

    badge = "PRO" if plan == "PRO" else "FREE"
    if role == "admin" or is_admin:
        badge = "ADMIN (PRO)"

    ctx = {
        "request": request,
        "user_name": name,
        "user_email": email,
        "user_plan": plan,
        "user_badge": badge,
    }

    try:
        return templates.TemplateResponse("dashboard.html", ctx)
    except TemplateNotFound:
        # Fallback mínimo por si aún no subiste la plantilla
        html = f"""
        <html><body style="font-family:system-ui">
        <h1>Bienvenido, {name}</h1>
        <p>Plan: <b>{plan}</b> — Badge: <b>{badge}</b></p>
        <p>Email: {email}</p>
        <p>Subí <code>app/templates/dashboard.html</code> para ver el dashboard completo.</p>
        </body></html>
        """
        return HTMLResponse(html)

# 404 simple (evita bucles de redirección)
@app.exception_handler(404)
def not_found(request: Request, exc):
    return HTMLResponse("<h1>404 - Not Found</h1>", status_code=404)
