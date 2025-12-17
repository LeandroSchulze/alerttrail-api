# app/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.i18n import get_lang, t
from app.security import get_current_user_cookie

from app.routers import (
    admin,
    alerts,
    analysis,
    audit,
    auth,
    billing,
    billing_subscriptions,
    billing_ui,
    i18n as i18n_router,
    legal,
    mail,
    payments,
    payments_history,
    payments_mp,
    profile,
    reports,
    stats,
    tools,
)

APP_NAME = os.getenv("APP_NAME", "AlertTrail")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-session-secret")
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")


class TemplatesWithDefaults(Jinja2Templates):
    """TemplateResponse() que siempre agrega lang y expone t() en contexto."""

    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        try:
            request = context.get("request")
            if request and "lang" not in context:
                context["lang"] = get_lang(request)
        except Exception:
            pass

        context.setdefault("t", t)
        return super().TemplateResponse(name, context, *args, **kwargs)


# Templates
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)
templates.env.globals["t"] = t  # para base.html aunque no lo pases en context

app = FastAPI(title=APP_NAME)

# ✅ IMPORTANTE: lo que tu auth.py espera
app.state.templates = templates
app.state.reports_dir = REPORTS_DIR
app.state.app_name = APP_NAME

# Sesiones
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


class LangHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            response.headers["Content-Language"] = get_lang(request)
        except Exception:
            pass
        return response


app.add_middleware(LangHeaderMiddleware)

# Static
STATIC_DIR = Path("app/static") if Path("app/static").exists() else Path("static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Reports folder
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    user = None
    try:
        user = get_current_user_cookie(request)
    except Exception:
        user = None

    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user},
    )


# ✅ Alias /login -> /auth/login
@app.get("/login", include_in_schema=False)
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)


# ✅ Alias /logout -> /auth/logout
@app.get("/logout", include_in_schema=False)
def logout_alias():
    return RedirectResponse(url="/auth/logout", status_code=302)


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/"):
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie("lang", (lang or "es").lower(), path="/", max_age=60 * 60 * 24 * 365)
    return resp


# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(tools.router)
app.include_router(profile.router)

app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(audit.router)
app.include_router(legal.router)

app.include_router(billing.router)
app.include_router(billing_ui.router)
app.include_router(billing_subscriptions.router)

app.include_router(payments.router)
app.include_router(payments_history.router)
app.include_router(payments_mp.router)
app.include_router(stats.router)
app.include_router(i18n_router.router)
