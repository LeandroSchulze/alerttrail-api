# app/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.ui import templates
from app.i18n import get_lang_from_request

# Routers
from app.routers import auth, analysis, mail, admin, reports, profile, tools, scheduler_status, alerts, i18n, billing
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

# Session cookies (for a few UI flows; JWT auth stays in your security.py)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Static + Reports mounts
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# serve generated PDFs/reports (Render disk)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


# -------------------------
# Routers
# -------------------------
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)

# Billing (this is the one that provides /billing/subscriptions and /billing/payments)
app.include_router(billing.router)

# misc / ui
app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(tools.router)
app.include_router(scheduler_status.router)
app.include_router(alerts.router)
app.include_router(i18n.router)

# cron/task endpoints (Render cron can hit /tasks/mail/poll)
app.include_router(tasks_mail.router)


# -------------------------
# Basic routes
# -------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True, "app": APP_NAME}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
        },
    )


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/dashboard"):
    """
    Used by base.html language selector:
      /set-lang?lang=es&next=/some/path
    Stores cookie "lang" and redirects back.
    """
    lang = (lang or "es").lower()
    resp = RedirectResponse(url=next or "/dashboard", status_code=302)
    # cookie for 1 year
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, httponly=False, samesite="lax")
    return resp


# -------------------------
# Background: Mail auto-scan
# -------------------------
_scheduler: Optional[BackgroundScheduler] = None


def _mail_scan_job():
    """
    Runs a scan of all connected mailboxes.
    This is used for the "auto scan every N minutes" behavior.
    """
    try:
        from app.services.mail_scan import scan_all_connected_mailboxes

        out = scan_all_connected_mailboxes()
        # out is typically a dict summary; log a compact version
        mail_logger.info("AUTO_MAIL_SCAN OK: %s", out)
    except Exception as e:
        mail_logger.exception("AUTO_MAIL_SCAN ERROR: %s", e)


def _heartbeat_job():
    try:
        logger.info("scheduler heartbeat")
    except Exception:
        pass


@app.on_event("startup")
def on_startup():
    """
    Start APScheduler inside the web process (Render web service).
    NOTE: If you scale to multiple instances, each instance will run this job.
    In that case prefer Render Cron calling /tasks/mail/poll (single runner).
    """
    global _scheduler

    enabled = os.getenv("MAIL_AUTO_SCAN_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    interval_min = int(os.getenv("MAIL_SCAN_INTERVAL_MIN", os.getenv("MAIL_POLL_EVERY_MIN", "5")))

    # Safety bounds
    if interval_min < 1:
        interval_min = 1
    if interval_min > 60:
        interval_min = 60

    _scheduler = BackgroundScheduler(timezone="UTC")

    # heartbeat every 10 minutes (helps confirm it’s running in logs)
    _scheduler.add_job(_heartbeat_job, "interval", minutes=10, id="heartbeat", replace_existing=True)

    if enabled:
        _scheduler.add_job(
            _mail_scan_job,
            "interval",
            minutes=interval_min,
            id="mail_auto_scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Auto mail scan enabled каж interval=%s min", interval_min)
    else:
        logger.info("Auto mail scan disabled by MAIL_AUTO_SCAN_ENABLED=0")

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
