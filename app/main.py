# app/main.py
from __future__ import annotations

import os
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Depends, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy import func

from starlette.middleware.base import BaseHTTPMiddleware

from app.database import get_db
from app.models import User
from app.security import (
    get_current_user_cookie,
    clear_access_cookie,
    normalize_user_plan,
)

# ✅ i18n por keys (JSON) + debug
from app.i18n import get_lang, t, i18n_debug


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="AlertTrail API", version="1.0.0")
app.router.redirect_slashes = False

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"


# -----------------------------------------------------------------------------
# Templates (con defaults + globals)
# -----------------------------------------------------------------------------
class TemplatesWithDefaults(Jinja2Templates):
    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        # Siempre asegurar request + lang en context
        request = context.get("request")
        if request:
            context.setdefault("lang", get_lang(request))
        else:
            context.setdefault("lang", "es")
        return super().TemplateResponse(name, context, *args, **kwargs)


templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)

# ✅ hacer disponibles las helpers globales en Jinja
templates.env.globals["t"] = t

# ✅ opcional: t_key("dashboard.hello") dentro del template sin pasar lang manualmente
def t_key(request: Request, key: str, **fmt):
    return t(get_lang(request), key, **fmt)

templates.env.globals["t_key"] = t_key

# ✅ dejar templates accesible desde routers via request.app.state.templates
app.state.templates = templates


# -----------------------------------------------------------------------------
# Middlewares (lang + Content-Language)
# -----------------------------------------------------------------------------
class AddLangToRequestStateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.lang = get_lang(request)
        return await call_next(request)


app.add_middleware(AddLangToRequestStateMiddleware)


@app.middleware("http")
async def content_language_header(request: Request, call_next):
    response = await call_next(request)
    try:
        response.headers["Content-Language"] = get_lang(request)
    except Exception:
        pass
    return response


# -----------------------------------------------------------------------------
# Static
# -----------------------------------------------------------------------------
STATIC_DIR = BASE_DIR / "app" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

REPORTS_DIR = os.getenv("REPORTS_DIR", str(BASE_DIR / "reports"))
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")


# -----------------------------------------------------------------------------
# Health (con debug i18n para no volver a "volver atrás")
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    # Si i18n counts es/en dan 0 => no están leyendo JSON o JSON roto
    return {"ok": True, "i18n": i18n_debug()}


# -----------------------------------------------------------------------------
# Root / Language
# -----------------------------------------------------------------------------
def _cookie_domain_for_request(_request: Request) -> str | None:
    # Ajustá si querés dominio compartido/subdominios.
    return None


@app.get("/", include_in_schema=False)
def root(request: Request):
    # Si hay sesión => dashboard, si no => login
    try:
        get_current_user_cookie(request)
        return RedirectResponse("/dashboard", status_code=302)
    except Exception:
        return RedirectResponse("/auth/login", status_code=302)


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/dashboard"):
    lang = (lang or "es").lower()[:2]
    if lang not in ("es", "en"):
        lang = "es"

    resp = RedirectResponse(next or "/dashboard", status_code=303)
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        secure=True,
        domain=_cookie_domain_for_request(request),
    )
    return resp


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    normalize_user_plan(db, user)

    ctx = {
        "request": request,
        "current_user": user,
        "user": user,
        "lang": get_lang(request),
    }
    return templates.TemplateResponse("dashboard.html", ctx)


# Aliases legacy
@app.get("/reports_browser", include_in_schema=False)
def reports_browser_alias():
    return RedirectResponse(url="/reports/", status_code=307)


@app.get("/logout", include_in_schema=False)
def logout_alias():
    resp = RedirectResponse("/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp


# -----------------------------------------------------------------------------
# Routers (auto include)
# -----------------------------------------------------------------------------
def _include_router(module_path: str, router_name: str = "router", prefix: str = ""):
    mod = import_module(module_path)
    router = getattr(mod, router_name)
    app.include_router(router, prefix=prefix)


# auth
_include_router("app.routers.auth", "router", prefix="/auth")
print("[routers] auth OK")

# resto
for module, name, prefix in [
    ("app.routers.billing", "router", ""),
    ("app.routers.billing_ui", "router", ""),
    ("app.routers.billing_subscriptions", "router", ""),
    ("app.routers.payments", "router", ""),
    ("app.routers.payments_history", "router", ""),
    ("app.routers.payments_mp", "router", ""),
    ("app.routers.stats", "router", ""),
    ("app.routers.alerts", "router", ""),
    ("app.routers.reports", "router", ""),
    ("app.routers.admin", "router", ""),
    ("app.routers.analysis", "router", ""),
    ("app.routers.mail", "router", ""),
    ("app.routers.profile", "router", ""),
    ("app.routers.tools", "router", ""),
    ("app.routers.audit", "router", ""),
    ("app.routers.legal", "router", ""),
]:
    _include_router(module, name, prefix=prefix)
    print(f"[routers] {module.split('.')[-1]} OK")


# -----------------------------------------------------------------------------
# OpenAPI
# -----------------------------------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="AlertTrail API",
        routes=app.routes,
    )
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


# -----------------------------------------------------------------------------
# (Opcional) Debug rutas si activás env DEBUG_ROUTES=1
# -----------------------------------------------------------------------------
if os.getenv("DEBUG_ROUTES", "").lower() in ("1", "true", "yes", "on"):
    print("\n=== ROUTES ===")
    for route in app.routes:
        if isinstance(route, APIRoute):
            print(route.path)
    print("==============\n")
