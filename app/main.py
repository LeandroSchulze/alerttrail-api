# app/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional
from importlib import import_module

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.ui import templates
from app.i18n import get_lang_from_request

from app.routers import auth, analysis, mail, admin, reports, profile, tools, scheduler_status, alerts, i18n, billing, payments, webhooks
from app.routers import tasks_mail  # cron / task endpoints

logger = logging.getLogger("alerttrail")

APP_NAME = "AlertTrail"
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title=APP_NAME)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    https_only=bool(os.getenv("SESSION_HTTPS_ONLY", "1") != "0"),
    same_site=os.getenv("SESSION_SAMESITE", "lax"),
)

# Static
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)
app.include_router(billing.router)

# payments module (subscription endpoints: /payments/subscribe, etc.)
app.include_router(payments.router)
app.include_router(webhooks.router)

# misc / ui
app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(tools.router)
app.include_router(scheduler_status.router)
app.include_router(alerts.router)
app.include_router(i18n.router)

# cron / task endpoints
app.include_router(tasks_mail.router)

# Optional routers (UI pages and others) - loaded dynamically if present
def include_optional_router(module_path: str):
    try:
        mod = import_module(module_path)
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)
            logger.info("Included optional router: %s", module_path)
    except Exception:
        # silently ignore missing optional modules
        pass

include_optional_router("app.routers.billing_ui")
include_optional_router("app.routers.payments_ui")
include_optional_router("app.routers.stats_ui")
include_optional_router("app.routers.admin_payments")
include_optional_router("app.routers.audit")
include_optional_router("app.routers.darkweb")
include_optional_router("app.routers.legal")

# Root
@app.get("/", include_in_schema=False)
def root(request: Request):
    # redirect to dashboard if logged in else landing
    try:
        # if session exists, go dashboard
        return RedirectResponse(url="/dashboard", status_code=302)
    except Exception:
        return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}

# Error pages
@app.exception_handler(404)
async def not_found(request: Request, exc):
    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        "404.html",
        {"request": request, "lang": lang},
        status_code=404,
    )

# Scheduler hooks (kept as-is)
_scheduler = None

@app.on_event("startup")
def on_startup():
    global _scheduler
    try:
        from app.scheduler import build_scheduler
        _scheduler = build_scheduler()
    except Exception as e:
        logger.warning("Scheduler not started: %s", e)
        _scheduler = None
        return

    try:
        mail_auto_scan_enabled = os.getenv("MAIL_AUTO_SCAN_ENABLED", "1")
        if str(mail_auto_scan_enabled).strip() == "0":
            logger.info("Auto mail scan disabled by MAIL_AUTO_SCAN_ENABLED=0")
    except Exception:
        pass

    _scheduler.start()

@app.on_event("shutdown")
def on_shutdown():
    global _scheduler
    try:
        if _scheduler:
            _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None
