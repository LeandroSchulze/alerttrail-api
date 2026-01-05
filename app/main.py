# app/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Response, Depends, Query  # ✅ incluye Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi import HTTPException  # si ya lo tenés importado, no lo dupliques

from app.ui import templates
from app.i18n import get_lang_from_request

# DB + models
from app.database import get_db
from app.models import User

# Security
from app.security import get_current_user_cookie_optional

# Routers
from app.routers import auth, analysis, mail, admin, reports, profile, tools, scheduler_status, alerts, i18n, billing, payments, webhooks
from app.routers import tasks_mail  # cron / task endpoints

# Background scheduler (auto mail scan)
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("alerttrail")
mail_logger = logging.getLogger("alerttrail.mail")

APP_NAME = os.getenv("APP_NAME", "AlertTrail")
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "change-me-in-env"))

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/var/data/reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME)

# ✅ Needed for routers that expect request.app.state.templates
app.state.templates = templates

# Session cookies (for a few UI flows; JWT auth stays in your security.py)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Static + Reports mounts
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# serve generated PDFs/reports (Render disk)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


def _try_include_router(module_path: str) -> None:
    """
    Includes router from a module if it exists.
    Expected: module has attribute 'router'.
    This is safe for deploys where some UI routers may not exist.
    """
    try:
        mod = import_module(module_path)
        router = getattr(mod, "router", None)
        if router is None:
            logger.warning("Optional router module %s has no attribute 'router'", module_path)
            return
        app.include_router(router)
        logger.info("Included optional router: %s", module_path)
    except ModuleNotFoundError:
        # module not present in this build — ok
        logger.warning("Optional router not found: %s", module_path)
    except Exception as e:
        # any other error should be visible but not kill app startup
        logger.exception("Failed including optional router %s: %s", module_path, e)


# -------------------------
# Routers
# -------------------------
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)

# Billing
app.include_router(billing.router)

# Payments
app.include_router(payments.router)

# ✅ Webhooks (MercadoPago notifications)
app.include_router(webhooks.router)

# misc / ui
app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(tools.router)
app.include_router(scheduler_status.router)
app.include_router(alerts.router)
app.include_router(i18n.router)

# cron/task endpoints
app.include_router(tasks_mail.router)

# Optional UI routers
_try_include_router("app.routers.billing_ui")
_try_include_router("app.routers.payments_ui")
_try_include_router("app.routers.stats_ui")
_try_include_router("app.routers.admin_payments")
_try_include_router("app.routers.audit")
_try_include_router("app.routers.darkweb")
_try_include_router("app.routers.legal")


# -------------------------
# Basic routes
# -------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True, "app": APP_NAME}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)


# -------------------------
# ✅ Alias retrocompatible para idioma
# -------------------------
@app.get("/set-lang", include_in_schema=False)
def set_lang(lang: str = Query("es"), next: str = Query("/dashboard")):
    """
    FIX definitivo:
    - No depende de /i18n/set-lang.
    - Setea idioma en cookie + session.
    - Redirige a `next`.
    """
    lang = (lang or "es").lower().strip()
    if lang not in ("es", "en"):
        lang = "es"

    resp = RedirectResponse(url=next or "/dashboard", status_code=302)

    # Cookie (muchas implementaciones de i18n leen esto)
    resp.set_cookie(
        key="lang",
        value=lang,
        max_age=60 * 60 * 24 * 365,  # 1 año
        path="/",
        samesite="lax",
    )

    # Session (por si get_lang_from_request usa request.session)
    try:
        # SessionMiddleware ya está agregado arriba
        resp.set_cookie(
            key="session_lang",
            value=lang,
            max_age=60 * 60 * 24 * 365,
            path="/",
            samesite="lax",
        )
    except Exception:
        pass

    return resp


# -------------------------
# Dashboard
# -------------------------
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, user=Depends(get_current_user_cookie_optional)):
    # Si no hay user, redirige a login (como estaba antes)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "current_user": user,
            "user": user,
        },
    )


# -------------------------
# Background Scheduler (Mail polling)
# -------------------------
scheduler = BackgroundScheduler()

def _safe_run_mail_poll():
    try:
        from app.tasks.mail_poll import poll_all_accounts
        poll_all_accounts()
    except Exception:
        mail_logger.exception("Mail poll failed")

MAIL_POLL_ENABLED = (os.getenv("MAIL_POLL_ENABLED") or "true").lower() == "true"
MAIL_POLL_INTERVAL_MIN = int(os.getenv("MAIL_POLL_INTERVAL_MIN", "10") or "10")

if MAIL_POLL_ENABLED:
    scheduler.add_job(_safe_run_mail_poll, "interval", minutes=MAIL_POLL_INTERVAL_MIN)
    try:
        scheduler.start()
        mail_logger.info("Mail poll scheduler started (%s min)", MAIL_POLL_INTERVAL_MIN)
    except Exception:
        mail_logger.exception("Failed starting scheduler")


# -------------------------
# Error handlers
# -------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return HTMLResponse("Internal Server Error", status_code=500)
