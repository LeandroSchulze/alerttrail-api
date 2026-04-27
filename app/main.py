from __future__ import annotations
import os
import logging
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# Importación corregida para evitar loops
from app.i18n.utils import get_lang_and_translator
from app.ui import templates
from app.security import get_current_user_cookie_optional

# Routers
from app.routers import (
    auth, analysis, mail, admin, reports, profile, tools,
    scheduler_status, alerts, i18n, billing, payments,
    webhooks, tasks_mail, push,
)

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("alerttrail")
mail_logger = logging.getLogger("alerttrail.mail")

APP_NAME = os.getenv("APP_NAME", "AlertTrail")
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "change-me-in-env"))

# Configuración de rutas de archivos
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
# Cambiado a una ruta relativa por defecto para evitar errores de permisos en Railway
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))

try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.warning(f"No se pudo crear REPORTS_DIR: {e}")

app = FastAPI(title=APP_NAME)
app.state.templates = templates
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    sw_path = STATIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(sw_path)
    return HTMLResponse("Service Worker not found", status_code=404)

# Montaje de estáticos seguro
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

# Routers opcionales
_try_include_router("app.routers.billing_ui")
_try_include_router("app.routers.payments_ui")
_try_include_router("app.routers.audit")
_try_include_router("app.routers.admin_dashboard_ui")

@app.get("/health", include_in_schema=False)
@app.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok", "app": APP_NAME}

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/set-lang", include_in_schema=False)
def set_lang(lang: str = Query("es"), next: str = Query("/dashboard")):
    lang = (lang or "es").lower().strip()
    if lang not in ("es", "en"): lang = "es"
    resp = RedirectResponse(url=next or "/dashboard", status_code=302)
    resp.set_cookie("alerttrail_lang", lang, max_age=60*60*24*365, path="/", samesite="lax")
    resp.set_cookie("lang", lang, max_age=60*60*24*365, path="/", samesite="lax")
    return resp

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang, t_func = get_lang_and_translator(request, user=user)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "t": t_func,
            "current_user": user,
            "user": user,
        },
    )

# Scheduler con inicio seguro
scheduler = BackgroundScheduler()
def _safe_run_mail_poll():
    try:
        from app.tasks.mail_poll import poll_all_accounts
        poll_all_accounts()
    except Exception:
        mail_logger.exception("Mail poll failed")

if (os.getenv("MAIL_POLL_ENABLED") or "true").lower() == "true":
    scheduler.add_job(_safe_run_mail_poll, "interval", minutes=int(os.getenv("MAIL_POLL_INTERVAL_MIN", "10")))
    try:
        if not scheduler.running:
            scheduler.start()
    except Exception:
        mail_logger.exception("Failed starting scheduler")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return HTMLResponse("Internal Server Error", status_code=500)
