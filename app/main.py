# app/main.py
import os
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy import func
from jinja2 import TemplateNotFound

from app.database import SessionLocal
from app.database import get_db
from app.models import User
from app.security import (
    get_current_user_cookie,
    issue_access_cookie,
    clear_access_cookie,
    COOKIE_NAME,
    create_access_token,
    normalize_user_plan,
)

# 👇 i18n por keys (JSON)
from app.i18n import get_lang, t

app = FastAPI(title="AlertTrail API", version="1.0.0")
app.router.redirect_slashes = False

DEBUG_AUTH = os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on")

from starlette.middleware.base import BaseHTTPMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"


class TemplatesWithDefaults(Jinja2Templates):
    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        try:
            request = context.get("request")
            if request and "lang" not in context:
                context["lang"] = get_lang(request)
        except Exception:
            context.setdefault("lang", "es")
        return super().TemplateResponse(name, context, *args, **kwargs)


templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)
app.state.templates = templates

# t(lang, "key")
templates.env.globals["t"] = t


def _cookie_domain_for_request(request: Request) -> str | None:
    # podés ajustar esto si usás dominio custom y subdominios
    return None


class AddRequestToStateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.lang = get_lang(request)
        resp = await call_next(request)
        return resp


app.add_middleware(AddRequestToStateMiddleware)


@app.middleware("http")
async def content_language_header(request: Request, call_next):
    response = await call_next(request)
    try:
        response.headers["Content-Language"] = get_lang(request)
    except Exception:
        pass
    return response


@app.middleware("http")
async def cookie_hardener(request: Request, call_next):
    resp = await call_next(request)
    try:
        # Refuerza cookies existentes si aplica (opcional)
        pass
    except Exception:
        pass
    return resp


# Static
STATIC_DIR = BASE_DIR / "app" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

REPORTS_DIR = os.getenv("REPORTS_DIR", str(BASE_DIR / "reports"))
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root(request: Request):
    # si hay sesión => dashboard, si no => login
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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    normalize_user_plan(db, user)

    ctx = {"request": request, "current_user": user, "user": user}
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/reports_browser", include_in_schema=False)
def reports_browser_alias():
    return RedirectResponse(url="/reports/", status_code=307)


@app.get("/rules", include_in_schema=False)
def rules_disabled_no_slash():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/rules/", include_in_schema=False)
def rules_disabled_slash():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.post("/login", include_in_schema=False)
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # login real está en /auth/login/web (esto es alias legacy)
    return RedirectResponse("/auth/login", status_code=302)


@app.get("/logout", include_in_schema=False)
def logout_alias(request: Request):
    resp = RedirectResponse("/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp


# Routers
def _include_router(path: str, router_name: str, prefix: str = ""):
    mod = import_module(path)
    router = getattr(mod, router_name)
    app.include_router(router, prefix=prefix)


_include_router("app.routers.auth", "router", prefix="/auth")
print("[routers] auth OK")

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


# Debug rutas (opcional)
if os.getenv("DEBUG_ROUTES", "").lower() in ("1", "true", "yes", "on"):
    print("\n=== ROUTES ===")
    for route in app.routes:
        if isinstance(route, APIRoute):
            print(route.path)
    print("==============\n")
