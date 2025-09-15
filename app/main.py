# app/main.py
import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound

from app.database import Base, engine, get_db
from app.security import get_current_user_cookie

app = FastAPI(title="AlertTrail")

# Tablas (no rompe si ya existen)
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[main] Aviso al crear tablas: {e}")

# Static/Templates/Reports robusto
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(APP_DIR)

STATIC_DIR = next((p for p in (
    os.path.join(APP_DIR, "static"),
    os.path.join(ROOT_DIR, "static"),
) if os.path.isdir(p)), os.path.join(APP_DIR, "static"))
TEMPLATES_DIR = next((p for p in (
    os.path.join(APP_DIR, "templates"),
    os.path.join(ROOT_DIR, "templates"),
) if os.path.isdir(p)), os.path.join(APP_DIR, "templates"))

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Incluir routers (sin romper si falta alguno)
def _try_include(module_path: str, attr: str = "router"):
    try:
        module = __import__(module_path, fromlist=[attr])
        app.include_router(getattr(module, attr))
        print(f"[main] Router incluido: {module_path}")
    except Exception as e:
        print(f"[main] (aviso) No se pudo incluir {module_path}: {e}")

_try_include("app.routers.auth")       # /auth/*
_try_include("app.routers.billing")    # /billing/*
_try_include("app.routers.admin")
_try_include("app.routers.analysis")
_try_include("app.routers.mail")
_try_include("app.routers.tasks_mail")


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db=Depends(get_db)):
    user = get_current_user_cookie(request, db=db)
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=302)

    name = getattr(user, "name", "Usuario")
    email = getattr(user, "email", "")
    plan = getattr(user, "plan", "FREE")
    role = getattr(user, "role", None)
    is_admin = getattr(user, "is_admin", False)
    badge = "PRO" if plan.upper() == "PRO" else "FREE"
    if role == "admin" or is_admin:
        badge = "ADMIN (PRO)"

    ctx = {"request": request, "user_name": name, "user_email": email, "user_plan": plan, "user_badge": badge}
    try:
        return templates.TemplateResponse("dashboard.html", ctx)
    except TemplateNotFound:
        html = f"""
        <html><body style="font-family:system-ui">
          <h1>Bienvenido, {name}</h1>
          <p>Plan: <b>{plan}</b> — Badge: <b>{badge}</b></p>
          <p>Email: {email}</p>
          <p><a href="/billing/checkout?plan=pro-monthly">Cambiar a PRO mensual</a> |
             <a href="/billing/checkout?plan=pro-annual">PRO anual</a> |
             <a href="/auth/logout">Salir</a></p>
          <p>Subí <code>app/templates/dashboard.html</code> para el dashboard completo.</p>
        </body></html>"""
        return HTMLResponse(html)

# 404 simple (evita bucles)
@app.exception_handler(404)
def not_found(request: Request, exc):
    return HTMLResponse("<h1>404 - Not Found</h1>", status_code=404)
