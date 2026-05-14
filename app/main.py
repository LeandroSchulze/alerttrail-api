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
    webhooks, tasks_mail, push, scanner 
)

from apscheduler.schedulers.background import BackgroundScheduler

# Configuración de Logging
logger = logging.getLogger("alerttrail")
mail_logger = logging.getLogger("alerttrail.mail")

APP_NAME = os.getenv("APP_NAME", "AlertTrail")
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "change-me-in-env"))

# --- CONFIGURACIÓN DE RUTAS INTELIGENTE ---
BASE_DIR = Path(__file__).resolve().parent # /app/app
ROOT_DIR = BASE_DIR.parent                  # /app (Raíz de Railway)
STATIC_DIR = BASE_DIR / "static"

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./reports_data"))
try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.warning(f"No se pudo crear REPORTS_DIR: {e}")

app = FastAPI(title=APP_NAME)

@app.on_event("startup")
def on_startup():
    init_db() 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.templates = templates
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --- SERVIR PWA DESDE CUALQUIER UBICACIÓN ---

@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    # Buscamos en: 1. Raíz, 2. Carpeta App, 3. Carpeta Static
    locations = [ROOT_DIR / "sw.js", BASE_DIR / "sw.js", STATIC_DIR / "sw.js"]
    for path in locations:
        if path.exists():
            return FileResponse(path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})
    
    logger.error(f"404 CRÍTICO: sw.js no encontrado. Buscado en: {[str(p) for p in locations]}")
    return HTMLResponse("Service Worker not found", status_code=404)

@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest():
    locations = [ROOT_DIR / "manifest.json", BASE_DIR / "manifest.json", STATIC_DIR / "manifest.json"]
    for path in locations:
        if path.exists():
            return FileResponse(path, media_type="application/json")
    return HTMLResponse("Manifest not found", status_code=404)

@app.get("/icon.svg", include_in_schema=False)
async def serve_icon():
    locations = [ROOT_DIR / "icon.svg", BASE_DIR / "icon.svg", STATIC_DIR / "icon.svg"]
    for path in locations:
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
    return HTMLResponse("Icon not found", status_code=404)

# Montaje de carpetas
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

# Registro de Routers (Sin tocar nada)
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
app.include_router(scanner.router)

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
        request=request, name="dashboard.html",
        context={"lang": lang, "t": t_func, "user": user, "current_user": user}
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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return HTMLResponse("Internal Server Error", status_code=500)
