# app/main.py
from __future__ import annotations
import os
import logging
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# Utilidades y Seguridad
from app.i18n.utils import get_lang_and_translator
from app.ui import templates
from app.security import get_current_user_cookie_optional
from app.database import init_db 

# Routers
from app.routers import (
    auth, analysis, mail, admin, reports, profile, tools,
    scheduler_status, alerts, i18n, billing, payments,
    webhooks, tasks_mail, push,
    scanner  # <--- AGREGADO: Importamos el nuevo router
)

from apscheduler.schedulers.background import BackgroundScheduler

# Configuración de Logging
logger = logging.getLogger("alerttrail")
mail_logger = logging.getLogger("alerttrail.mail")

APP_NAME = os.getenv("APP_NAME", "AlertTrail")
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "change-me-in-env"))

# Directorios
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./reports_data"))

try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.warning(f"No se pudo crear REPORTS_DIR: {e}")

app = FastAPI(title=APP_NAME)

# --- SINCRONIZACIÓN DE BASE DE DATOS ---
@app.on_event("startup")
def on_startup():
    """Ejecuta la creación de tablas al arrancar la app."""
    init_db() 

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.templates = templates
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --- CONFIGURACIÓN PWA / SERVICE WORKER ---
@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    sw_path = STATIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(
            sw_path, 
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"}
        )
    return HTMLResponse("Service Worker not found", status_code=404)

# Montaje de archivos estáticos
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

def _try_include_router(module_path: str) -> None:
    try:
        mod = import_module(module_path)
        router = getattr(mod, "router", None)
        if router:
            app.include_router(router)
    except Exception:
        logger.exception("Failed including optional router: %s", module_path)

# Registro de Routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(payments.router)
app.include_router(webhooks.router)
app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(tools.router)
app.include_router(scheduler_status.router)
app.include_router(alerts.router)
app.include_router(i18n.router)
app.include_router(tasks_mail.router)
app.include_router(push.router)
app.include_router(scanner.router)  # <--- AGREGADO: Registramos la ruta /scanner

# Routers Opcionales
_try_include_router("app.routers.billing_ui")
_try_include_router("app.routers.payments_ui")
_try_include_router("app.routers.audit")
_try_include_router("app.routers.admin_dashboard_ui")

# Endpoints de salud
@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "app": APP_NAME}

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang, t_func = get_lang_and_translator(request, user=user)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "lang": lang,
            "t": t_func,
            "user": user,
            "current_user": user,
        },
    )

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
def _safe_run_mail_poll():
    try:
        from app.tasks.mail_poll import poll_all_accounts
        poll_all_accounts()
    except Exception:
        mail_logger.exception("Mail poll failed")

if (os.getenv("MAIL_POLL_ENABLED") or "true").lower() == "true":
    interval = int(os.getenv("MAIL_POLL_INTERVAL_MIN", "10"))
    scheduler.add_job(_safe_run_mail_poll, "interval", minutes=interval)
    if not scheduler.running:
        scheduler.start()

# Manejo Global de Errores
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return HTMLResponse("Internal Server Error", status_code=500)
