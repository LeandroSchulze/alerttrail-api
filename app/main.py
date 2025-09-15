# app/main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

# DB base y engine (OJO: importamos engine, NO get_engine)
from app.database import Base, engine, get_db

# Seguridad (JWT en cookie)
from app.security import get_current_user_cookie

app = FastAPI(title="AlertTrail")

# ----- Crear tablas si hiciera falta -----
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[main] Warning al crear tablas: {e}")

# ----- Static & Reports -----
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")

os.makedirs(REPORTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# ----- Templates -----
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ----- Routers opcionales (no romper si faltan) -----
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

# ----- Rutas base -----
@app.get("/", response_class=HTMLResponse)
def root():
    # Redirige al dashboard (si no hay cookie válida, el dashboard reenvía a /auth/login)
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db=Depends(get_db)):
    """
    Requiere cookie JWT válida. Si no hay, redirige a /auth/login (desde el helper).
    """
    user = get_current_user_cookie(request, db=db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Campos seguros para la vista
    name = getattr(user, "name", "Usuario")
    email = getattr(user, "email", "")
    plan = getattr(user, "plan", "FREE")
    role = getattr(user, "role", None)
    is_admin = getattr(user, "is_admin", False)

    # Badge especial si es admin
    badge = "PRO"
    if role == "admin" or is_admin:
        badge = "ADMIN (PRO)"

    ctx = {
        "request": request,
        "user_name": name,
        "user_email": email,
        "user_plan": plan,
        "user_badge": badge,
    }
    return templates.TemplateResponse("dashboard.html", ctx)

# ----- 404 amigable -----
@app.exception_handler(404)
def not_found(request: Request, exc):
    return RedirectResponse(url="/", status_code=302)
