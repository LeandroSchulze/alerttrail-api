from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.database import create_db_and_tables
from app.i18n import get_lang, jinja_t, set_lang_cookie
from app.security import get_current_user_cookie

# Routers
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


# -------------------------------------------------------------------
# Templates con defaults globales (lang + t)
# -------------------------------------------------------------------
class TemplatesWithDefaults(Jinja2Templates):
    """
    TemplateResponse que:
    - inyecta lang automáticamente
    - expone t() siempre
    """

    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        try:
            request = context.get("request")
            if request and "lang" not in context:
                context["lang"] = get_lang(request)
        except Exception:
            pass

        context.setdefault("t", jinja_t)
        return super().TemplateResponse(name, context, *args, **kwargs)


TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)

# t global para cualquier template
templates.env.globals["t"] = jinja_t


# -------------------------------------------------------------------
# App
# -------------------------------------------------------------------
app = FastAPI(title=APP_NAME)

# Sesiones
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


# -------------------------------------------------------------------
# Middleware idioma (Content-Language)
# -------------------------------------------------------------------
class LangHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            response.headers["Content-Language"] = get_lang(request)
        except Exception:
            pass
        return response


app.add_middleware(LangHeaderMiddleware)


# -------------------------------------------------------------------
# Startup
# -------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    try:
        create_db_and_tables()
    except Exception:
        pass


# -------------------------------------------------------------------
# Static y reports
# -------------------------------------------------------------------
STATIC_DIR = Path("app/static") if Path("app/static").exists() else Path("static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


# -------------------------------------------------------------------
# Root
# -------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard", status_code=302)


# -------------------------------------------------------------------
# Dashboard
# -------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    try:
        user = get_current_user_cookie(request)
    except Exception:
        user = None

    if not user:
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
        },
    )


# -------------------------------------------------------------------
# Cambiar idioma
# -------------------------------------------------------------------
@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/"):
    """
    Ej:
    /set-lang?lang=en&next=/dashboard
    /set-lang?lang=es&next=/mail
    """
    resp = RedirectResponse(next or "/", status_code=303)
    set_lang_cookie(resp, request, lang)
    return resp


# -------------------------------------------------------------------
# Aliases
# -------------------------------------------------------------------
@app.get("/reports_browser", include_in_schema=False)
def reports_browser_alias():
    return RedirectResponse("/reports", status_code=307)


@app.get("/reports/", include_in_schema=False)
def reports_trailing_slash_alias():
    return RedirectResponse("/reports", status_code=307)


@app.get("/billing/subscriptions", include_in_schema=False)
def billing_subscriptions_alias():
    return RedirectResponse("/billing", status_code=307)


# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------
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
