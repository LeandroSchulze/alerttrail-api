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
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    verify_password,
    clear_access_cookie,
    COOKIE_NAME,
    create_access_token,
    normalize_user_plan,
)

# 👇 ahora app.i18n es un PAQUETE (app/i18n/__init__.py)
from app.i18n import get_lang, t, translate_html

app = FastAPI(title="AlertTrail API", version="1.0.0")
app.router.redirect_slashes = False

DEBUG_AUTH = os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on")

from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; font-src 'self' data:"
        )
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return resp

app.add_middleware(SecurityHeadersMiddleware)

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
REPORTS_DIR   = "app/reports"   if Path("app/reports").exists()   else "reports"

REPORTS_STATIC_URL = "/reports-files"

Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(REPORTS_STATIC_URL, StaticFiles(directory=REPORTS_DIR), name="reports_files")


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

# (para futuro uso por keys) t(lang, "Key")
templates.env.globals["t"] = t


@app.middleware("http")
async def i18n_html_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        lang = get_lang(request)
        response.headers["Content-Language"] = lang

        ctype = (response.headers.get("content-type") or "").lower()
        if "text/html" not in ctype:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        html = body.decode("utf-8", errors="ignore")
        html2 = translate_html(lang, html)

        new_resp = Response(
            content=html2.encode("utf-8"),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type="text/html",
        )
        new_resp.headers["content-length"] = str(len(new_resp.body or b""))
        return new_resp
    except Exception:
        return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _cookie_domain_for_request(request: Request):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if not host:
        return None
    parts = host.split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return None


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str = "/"):
    lang = (lang or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"

    resp = RedirectResponse(next or "/", status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
        domain=_cookie_domain_for_request(request),
    )
    return resp


@app.middleware("http")
async def cookie_hardener(request: Request, call_next):
    resp = await call_next(request)
    sc = resp.headers.get("set-cookie")
    if not sc:
        return resp

    def patch(c: str) -> str:
        if COOKIE_NAME not in c:
            return c
        if "samesite" not in c.lower():
            c += "; SameSite=Lax"
        if "httponly" not in c.lower():
            c += "; HttpOnly"
        if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https") and "secure" not in c.lower():
            c += "; Secure"
        return c

    parts = [p.strip() for p in sc.split(",")]
    resp.headers["set-cookie"] = ", ".join(patch(p) for p in parts)
    return resp


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        _ = get_current_user_cookie(request)
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass

    try:
        return templates.TemplateResponse("landing.html", {"request": request})
    except TemplateNotFound:
        return HTMLResponse("<h1>AlertTrail</h1>")


from app.models import User

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
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(400, "Credenciales inválidas")

    normalize_user_plan(db, user)

    token = create_access_token({"sub": str(user.id), "email": user.email})
    r = RedirectResponse("/dashboard", status_code=303)
    issue_access_cookie(r, token)
    return r


@app.get("/logout", include_in_schema=False)
def logout():
    r = RedirectResponse("/", status_code=303)
    clear_access_cookie(r)
    return r


ROUTER_MODULES = [
    "auth",
    "billing",
    "billing_ui",
    "billing_subscriptions",
    "payments",
    "payments_history",
    "payments_mp",
    "stats",
    "alerts",
    # "rules",  # deshabilitado temporalmente
    "reports",
    "admin",
    "analysis",
    "mail",
    "profile",
    "tools",
    "audit",
]

for name in ROUTER_MODULES:
    try:
        mod = import_module(f"app.routers.{name}")
        app.include_router(mod.router)
        print(f"[routers] {name} OK")
    except Exception as e:
        print(f"[routers] {name} SKIPPED:", e)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="AlertTrail API",
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": COOKIE_NAME,
    }
    for p in schema.get("paths", {}).values():
        for m in p.values():
            if isinstance(m, dict):
                m.setdefault("security", [{"cookieAuth": []}])
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi


@app.get("/health")
def health():
    return {"ok": True}

@app.head("/")
def head_root():
    return Response(status_code=200)


@app.on_event("startup")
def log_routes():
    print("\n=== ROUTES ===")
    for r in app.routes:
        if isinstance(r, APIRoute):
            print(r.path)
    print("==============\n")
