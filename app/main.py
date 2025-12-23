# app/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.ui import templates
from app.i18n import get_lang_from_request

# DB + models
from app.database import get_db
from app.models import User

# Security
from app.security import get_current_user_cookie

# Routers
from app.routers import (
    auth,
    analysis,
    mail,
    admin,
    reports,
    profile,
    tools,
    scheduler_status,
    alerts,
    i18n,
    billing,
)
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

# Needed for routers that expect request.app.state.templates
app.state.templates = templates

# Session cookies (JWT sigue siendo el auth principal)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Static + Reports mounts
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

# -------------------------
# Routers
# -------------------------
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)
app.include_router(billing.router)

app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(tools.router)
app.include_router(scheduler_status.router)
app.include_router(alerts.router)
app.include_router(i18n.router)

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


@app.head("/", include_in_schema=False)
def root_head():
    return Response(status_code=200)


def _build_current_user(request: Request) -> dict:
    """
    JWT -> DB -> View-model consistente para templates
    ADMIN => PRO siempre
    """
    empty = {
        "id": None,
        "name": None,
        "email": None,
        "role": None,
        "plan": "FREE",
        "is_pro": False,
        "is_admin": False,
    }

    try:
        payload = get_current_user_cookie(request)
    except Exception:
        return empty

    user_id = payload.get("sub")
    db_user: Optional[User] = None

    try:
        if user_id:
            with next(get_db()) as db:
                try:
                    uid_int = int(str(user_id))
                except Exception:
                    uid_int = None

                if uid_int is not None:
                    db_user = db.get(User, uid_int)
    except Exception:
        db_user = None

    role = (
        (getattr(db_user, "role", None) or payload.get("role") or "")
        .lower()
    )

    email = getattr(db_user, "email", None) or payload.get("email")
    name = (
        getattr(db_user, "name", None)
        or payload.get("name")
        or payload.get("email")
        or "Usuario"
    )

    plan_db = (getattr(db_user, "plan", None) or payload.get("plan") or "FREE").upper()

    is_admin = role == "admin"

    # 🔒 ADMIN => PRO forzado
    plan = "PRO" if is_admin else plan_db
    is_pro = is_admin or plan == "PRO"

    return {
        "id": getattr(db_user, "id", None)
        or (int(user_id) if str(user_id).isdigit() else None),
        "name": name,
        "email": email,
        "role": role.upper() if role else None,
        "plan": plan,
        "is_pro": bool(is_pro),
        "is_admin": bool(is_admin),
    }


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    lang = get_lang_from_request(request)
    current_user = _build_current_user(request)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "user": current_user,
            "current_user": current_user,
            "is_admin": current_user.get("is_admin", False),
        },
    )


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/dashboard"):
    lang = (lang or "es").lower()
    resp = RedirectResponse(url=next or "/dashboard", status_code=302)
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
    )
    return resp


# -------------------------
# Background: Mail auto-scan
# -------------------------
_scheduler: Optional[BackgroundScheduler] = None


def _mail_scan_job():
    try:
        from app.services.mail_scan import scan_all_connected_mailboxes

        out = scan_all_connected_mailboxes()
        mail_logger.info("AUTO_MAIL_SCAN OK: %s", out)
    except Exception as e:
        mail_logger.exception("AUTO_MAIL_SCAN ERROR: %s", e)


def _heartbeat_job():
    logger.info("scheduler heartbeat")


@app.on_event("startup")
def on_startup():
    global _scheduler

    enabled = os.getenv("MAIL_AUTO_SCAN_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    interval_min = int(os.getenv("MAIL_SCAN_INTERVAL_MIN", "5"))
    interval_min = max(1, min(interval_min, 60))

    _scheduler = BackgroundScheduler(timezone="UTC")
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
        logger.info("Auto mail scan enabled interval=%s min", interval_min)
    else:
        logger.info("Auto mail scan disabled")

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
