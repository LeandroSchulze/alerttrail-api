# app/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.security import get_current_user_cookie
from app.ui import templates  # ✅ templates único, fuera de main (evita circular import)

# i18n (usamos get_lang que sí existe en tu proyecto)
from app.i18n import get_lang

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


def _set_lang_cookie(resp: RedirectResponse, request: Request, lang: str) -> None:
    """
    Wrapper tolerante: si existe set_lang_cookie en tu i18n, lo usa.
    Si no existe, setea cookie 'at_lang' igualmente.
    """
    lang = (lang or "es").lower()

    try:
        from app.i18n import set_lang_cookie  # type: ignore
        set_lang_cookie(resp, request, lang)  # tu implementación si existe
        return
    except Exception:
        # fallback simple
        resp.set_cookie("at_lang", lang, path="/", max_age=60 * 60 * 24 * 365)


class LangHeaderMiddleware(BaseHTTPMiddleware):
    """Agrega Content-Language según cookie/query lang."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            lang = get_lang(request)
            response.headers["Content-Language"] = lang
        except Exception:
            pass
        return response


app = FastAPI(title=APP_NAME)

# Sesiones (si usás flash messages u otros)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.add_middleware(LangHeaderMiddleware)


@app.on_event("startup")
def on_startup():
    """
    DB init (tolerante):
    - Si existe create_db_and_tables(), lo usa.
    - Si no, intenta create_all().
    - Si no hay nada, no rompe el deploy (porque ya corrés alembic + init_db en Start Command).
    """
    try:
        from app.database import create_db_and_tables  # type: ignore
        create_db_and_tables()
        return
    except Exception:
        pass

    try:
        from app.database import create_all  # type: ignore
        create_all()
        return
    except Exception:
        pass


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

    # templates (de app.ui) ya agrega t() y lang por default
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

    # cookie oficial (si existe) + fallback
    _set_lang_cookie(resp, request, lang)

    # compatibilidad si antes usabas "lang"
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
