# ============================================
# AlertTrail API - Main (UPDATED)
# ============================================

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
)

# ✅ normalize_user_plan: SIEMPRE desde billing_guard (tu archivo)
try:
    from app.security.billing_guard import normalize_user_plan  # type: ignore
except Exception:
    # fallback por si quedó exportado desde app.security
    try:
        from app.security import normalize_user_plan  # type: ignore
    except Exception:
        normalize_user_plan = None  # type: ignore

from app.i18n import get_lang, t, translate_html

# ============================================================
# App
# ============================================================

app = FastAPI(title="AlertTrail API", version="1.0.0")
app.router.redirect_slashes = False

DEBUG_AUTH = os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on")

# ============================================================
# Security Headers Middleware
# ============================================================

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
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        return resp

app.add_middleware(SecurityHeadersMiddleware)

# ============================================================
# Paths / Static / Templates
# ============================================================

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
REPORTS_DIR   = "app/reports"   if Path("app/reports").exists()   else "reports"

Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.state.templates = templates

# Exponer traducción global (por si algún template usa t("key"))
templates.env.globals["t"] = t

# ============================================================
# i18n: traducir HTML final (modo rápido sin romper templates)
# ============================================================

@app.middleware("http")
async def i18n_html_middleware(request: Request, call_next):
    response = await call_next(request)

    try:
        lang = get_lang(request)
        response.headers["Content-Language"] = lang

        # Solo traducimos HTML cuando el idioma sea EN
        if lang != "en":
            return response

        ctype = (response.headers.get("content-type") or "").lower()
        if "text/html" not in ctype:
            return response

        # Consumimos el body y lo re-escribimos traducido
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        html = body.decode("utf-8", errors="ignore")
        html2 = translate_html(lang, html)  # se espera que convierta ES->EN

        # Fallback mínimo: si no cambió nada, hacemos reemplazos básicos
        if html2 == html:
            replacements = {
                "Hola,": "Hi,",
                "Estado de tu cuenta": "Your account status",
                "Herramientas nuevas": "New tools",
                "Planes y facturación": "Plans & billing",
                "Ver mi suscripción": "View my subscription",
                "Panel de organización": "Organization panel",
                "Ir al Log Scanner": "Go to Log Scanner",
                "Scanner de correos": "Mail scanner",
                "Reportes guardados": "Saved reports",
                "Activar prueba PRO": "Activate PRO trial",
                "Últimos pagos": "Latest payments",
                "Salud de tu seguridad": "Your security health",
                "Funciones PRO / Empresas": "PRO / Business features",
                "Ver planes": "View plans",
                "Ver alertas": "View alerts",
                "Reglas personalizadas": "Custom rules",
                "Reportes": "Reports",
            }
            for a, b in replacements.items():
                html2 = html2.replace(a, b)

        new_resp = Response(
            content=html2.encode("utf-8"),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type="text/html",
        )
        new_resp.headers["content-length"] = str(len(new_resp.body or b""))
        return new_resp

    except Exception:
        # Si algo falla, no rompemos producción
        return response

# ============================================================
# DB
# ============================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================
# Idioma
# ============================================================

@app.get("/set-lang", include_in_schema=False)
def set_lang(
    request: Request,
    lang: str = "es",
    next: str = "/",
):
    lang = (lang or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"

    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        path="/",
    )
    return resp

# ============================================================
# Cookie hardener (solo para COOKIE_NAME)
# ============================================================

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

# ============================================================
# Home
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Si hay cookie válida, redirigimos al dashboard
    try:
        _ = get_current_user_cookie(request)
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass

    try:
        return templates.TemplateResponse("landing.html", {"request": request, "lang": get_lang(request)})
    except TemplateNotFound:
        return HTMLResponse("<h1>AlertTrail</h1>")

# ============================================================
# Fallback Login (si el router auth se rompe)
# ============================================================

@app.get("/auth/login", include_in_schema=False)
def auth_login_fallback(request: Request):
    """
    Si el router app.routers.auth explota, al menos esto devuelve un login funcional.
    No toca tu dashboard actual.
    """
    try:
        # Si ya está logueado, afuera
        _ = get_current_user_cookie(request)
        return RedirectResponse("/dashboard", status_code=302)
    except Exception:
        pass

    lang = get_lang(request)

    # Si existe template de login, lo usamos
    try:
        return templates.TemplateResponse("login.html", {"request": request, "lang": lang})
    except Exception:
        # HTML mínimo (POST a /login que ya existe acá)
        return HTMLResponse(
            f"""
            <!doctype html>
            <html lang="{lang}">
            <head><meta charset="utf-8"><title>Login - AlertTrail</title></head>
            <body style="font-family:system-ui;padding:24px;">
              <h2>AlertTrail - Login</h2>
              <form method="POST" action="/login">
                <div style="margin:8px 0;">
                  <label>Email</label><br/>
                  <input name="email" type="email" required style="padding:8px;width:320px;"/>
                </div>
                <div style="margin:8px 0;">
                  <label>Password</label><br/>
                  <input name="password" type="password" required style="padding:8px;width:320px;"/>
                </div>
                <button type="submit" style="padding:10px 14px;">Entrar</button>
              </form>
            </body>
            </html>
            """,
            status_code=200,
        )

# ============================================================
# Dashboard (NO SE TOCA EL TEMPLATE)
# ============================================================

from app.models import User

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    if normalize_user_plan:
        try:
            normalize_user_plan(db, user)
        except Exception:
            pass

    lang = get_lang(request)

    ctx = {
        "request": request,
        "current_user": user,
        "user": user,
        "lang": lang,
    }

    return templates.TemplateResponse("dashboard.html", ctx)

# ============================================================
# Login / Logout (form simple)
# ============================================================

@app.post("/login", include_in_schema=False)
def login_action(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(400, "Credenciales inválidas")

    if normalize_user_plan:
        try:
            normalize_user_plan(db, user)
        except Exception:
            pass

    token = create_access_token({"sub": str(user.id), "email": user.email})
    r = RedirectResponse("/dashboard", status_code=303)
    issue_access_cookie(r, token)
    return r

@app.get("/logout", include_in_schema=False)
def logout():
    r = RedirectResponse("/", status_code=303)
    clear_access_cookie(r)
    return r

# ============================================================
# Routers (carga segura)
# ============================================================

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
    "rules",
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

# ============================================================
# OpenAPI cookie auth
# ============================================================

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

# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():
    return {"ok": True}

@app.head("/")
def head_root():
    return Response(status_code=200)

# ============================================================
# Startup log
# ============================================================

@app.on_event("startup")
def log_routes():
    print("\n=== ROUTES ===")
    for r in app.routes:
        if isinstance(r, APIRoute):
            print(r.path)
    print("==============\n")
