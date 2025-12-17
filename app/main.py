from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.i18n import get_lang_from_request, jinja_t, set_lang_cookie
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


class TemplatesWithDefaults(Jinja2Templates):
    """TemplateResponse() que SIEMPRE agrega lang y expone t() en contexto."""

    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        try:
            request = context.get("request")
            if request and "lang" not in context:
                context["lang"] = get_lang_from_request(request)
        except Exception:
            pass

        # t disponible aunque un template no lo pase manualmente
        context.setdefault("t", jinja_t)
        return super().TemplateResponse(name, context, *args, **kwargs)


TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)

# t global para que base.html / cualquier template lo tenga aunque no esté en context
try:
    templates.env.globals["t"] = jinja_t
except Exception:
    pass


app = FastAPI(title=APP_NAME)

# Sesiones (si usás flash messages u otros)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


class LangHeaderMiddleware(BaseHTTPMiddleware):
    """Agrega Content-Language según cookie/query lang."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            lang = get_lang_from_request(request)
            response.headers["Content-Language"] = lang
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

    # Si tu dashboard.html usa t(lang, "dashboard.xxx"), ya queda resuelto.
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user},
    )


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/"):
    """
    Cambia idioma con:
      /set-lang?lang=en&next=/dashboard
      /set-lang?lang=es&next=/mail/
    """
    resp = RedirectResponse(next or "/", status_code=303)

    # cookie oficial + compatibilidad si antes usabas "lang"
    set_lang_cookie(resp, request, lang)
    resp.set_cookie("lang", (lang or "es").lower(), path="/", max_age=60 * 60 * 24 * 365)

    return resp


# Alias: /reports_browser -> /reports (SIN slash final)
@app.get("/reports_browser", include_in_schema=False)
def reports_browser_alias():
    return RedirectResponse(url="/reports", status_code=307)


# Alias: /reports/ -> /reports
@app.get("/reports/", include_in_schema=False)
def reports_trailing_slash_alias():
    return RedirectResponse(url="/reports", status_code=307)


# Alias: /billing/subscriptions -> /billing
@app.get("/billing/subscriptions", include_in_schema=False)
def billing_subscriptions_alias():
    return RedirectResponse(url="/billing", status_code=307)


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
