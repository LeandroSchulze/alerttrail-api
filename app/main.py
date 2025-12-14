# ============================================
# AlertTrail API - Main
# ============================================

import os, re, json
from pathlib import Path
from importlib import import_module

from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy import func
from jinja2 import TemplateNotFound
from app.routers.mail import start_mail_scheduler  # NEW

from app.database import SessionLocal
from app.security import (
    issue_access_cookie, get_current_user_cookie, get_password_hash, verify_password,
    clear_access_cookie, decode_token, COOKIE_NAME, create_access_token,
)
from app.i18n import get_lang, t  # 👈 traducción para Jinja

# === Crear la app ANTES de agregar middlewares y routers ===
app = FastAPI(title="AlertTrail API", version="1.0.0")
# Evita bucles /mail <-> /mail/
app.router.redirect_slashes = False

DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"))

# -------- Security Headers Middleware --------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return resp

app.add_middleware(SecurityHeadersMiddleware)

# --- Middleware para exponer lang en templates (usa get_lang) ---
class LangContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        try:
            ctx = getattr(resp, "context", None) or getattr(resp, "template_context", None)
            if ctx is not None and "lang" not in ctx:
                ctx["lang"] = get_lang(request)
        except Exception:
            pass
        return resp

app.add_middleware(LangContextMiddleware)

# ---- DB hotfix temprano ----
try:
    from app.db_hotfix import ensure_user_pro_columns  # type: ignore
except Exception:
    ensure_user_pro_columns = None  # type: ignore

if ensure_user_pro_columns:
    try:
        info = ensure_user_pro_columns(); print("[db_hotfix] run at import:", info)
    except Exception as e:
        print("[db_hotfix] WARNING at import-time:", e)

@app.on_event("startup")
def _startup_hotfix_columns():
    if ensure_user_pro_columns:
        try:
            info = ensure_user_pro_columns(); print("[db_hotfix] run at startup:", info)
        except Exception as e:
            print("[db_hotfix] WARNING at startup:", e)

# --- Scheduler de mail (respeta SCHEDULER_ENABLED=1) ---
@app.on_event("startup")
def _start_mail_sched():
    try:
        start_mail_scheduler(app)
    except Exception as e:
        print("[startup] mail scheduler error:", e)

from app.models import User

# ---- Paths/Static/Templates ----
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
REPORTS_DIR   = "app/reports"   if Path("app/reports").exists()   else "reports"
Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
# Montado estático para descargas (no requiere index.html)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR, html=True), name="reports")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.state.templates = templates
# 👇 exponer t() para usar {{ t(lang, "clave") }} en cualquier template
templates.env.globals["t"] = t

# --- Endurecedor de cookies de sesión ---
@app.middleware("http")
async def _cookie_hardener(request: Request, call_next):
    resp = await call_next(request)

    sc = resp.headers.get("set-cookie")
    if not sc:
        return resp

    import re as _re
    def _patch_cookie(header: str) -> str:
        if "access_token=" not in header:
            return header
        domain = os.getenv("ACCESS_COOKIE_DOMAIN", ".alerttrail.com")
        if " domain=" not in header.lower():
            header += f"; Domain={domain}"
        if " path=" not in header.lower():
            header += "; Path=/"
        if " samesite=" not in header.lower():
            header += "; SameSite=Lax"
        if " httponly" not in header.lower():
            header += "; HttpOnly"
        if " max-age=" not in header.lower() and " expires=" not in header.lower():
            header += "; Max-Age=604800"
        xfproto = request.headers.get("x-forwarded-proto", "")
        if (request.url.scheme == "https" or xfproto == "https") and " secure" not in header.lower():
            header += "; Secure"
        return header

    parts = [p.strip() for p in sc.split(",")]

    rebuilt, buf = [], []
    for p in parts:
        buf.append(p)
        if re.search(r"(?i)(expires=.*gmt)", " ".join(buf)):
            rebuilt.append(", ".join(buf)); buf = []
        elif "=" in p.split(";")[0] and ("Max-Age=" in p or "Expires=" in p or "Path=" in p):
            rebuilt.append(", ".join(buf)); buf = []
    if buf: rebuilt.append(", ".join(buf))

    patched = [_patch_cookie(c) for c in rebuilt]
    resp.headers["set-cookie"] = ", ".join(patched)
    return resp


# === UI Routers (billing, payments) ===
try:
    _billing_ui = import_module("app.routers.billing_ui")
    app.include_router(_billing_ui.router)
except Exception as e:
    print("[WARN] billing_ui load failed:", e)

try:
    _payments_ui = import_module("app.routers.payments_ui")
    app.include_router(_payments_ui.router)
except Exception as e:
    print("[WARN] payments_ui load failed:", e)

# billing_subscriptions (nuevo)
try:
    from app.routers import billing_subscriptions
    app.include_router(billing_subscriptions.router)
    print("[routers] billing_subscriptions montado OK")
except Exception as e:
    print(f"[routers] No pude cargar billing_subscriptions: {e}")

# === UI de estadísticas ===
try:
    from app.routers import stats_ui
    app.include_router(stats_ui.router)
except Exception as e:
    print("[WARN] stats_ui router:", e)

# === i18n (router de cambio de idioma) ===
# ✅ Importante: dejamos SOLO el router. No duplicamos /set-lang en este main.py
try:
    from app.routers import i18n
    app.include_router(i18n.router)
    print("[routers] i18n montado OK")
except Exception as e:
    print(f"[routers] No pude cargar i18n: {e}")

# ---- DB helpers ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def truthy(v):
    if isinstance(v, bool): return v
    if isinstance(v, int):  return v == 1
    if isinstance(v, str):  return v.strip().lower() in {"1","true","yes","y","on"}
    return False

def get_current_user_optional(request: Request, db= Depends(get_db)):
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None

# ---- OpenAPI cookieAuth por defecto ----
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description="API de AlertTrail", routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey", "in": "cookie", "name": "access_token"
    }
    for path in schema.get("paths", {}).values():
        for method in path.values():
            if isinstance(method, dict):
                method.setdefault("security", [{"cookieAuth": []}])
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

# ---- Middlewares útiles ----
@app.middleware("http")
async def _auth_debug_mw(request: Request, call_next):
    if DEBUG_AUTH and request.url.path in ("/auth/login/web", "/auth/login", "/dashboard", "/_cookie_test_set"):
        ck = request.headers.get("cookie")
        print("[auth][debug][in]", f"path={request.url.path}", f"host={request.headers.get('host')}",
              f"has_cookie={bool(ck)}", f"cookie_len={len(ck or '')}")
    resp = await call_next(request)
    if DEBUG_AUTH and request.url.path in ("/auth/login/web", "/auth/login", "/login", "/register", "/_cookie_test_set"):
        sc = resp.headers.get("set-cookie", "")
        import re as _re; masked = _re.sub(r"(access_token=)([^;]+)", r"\1***", sc)
        print("[auth][debug][out]", f"path={request.url.path}", f"set-cookie={masked or '<NONE>'}")
    return resp

@app.middleware("http")
async def force_www(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host == "alerttrail.com":
        url = request.url.replace(netloc="www.alerttrail.com")
        return RedirectResponse(str(url), status_code=308)
    return await call_next(request)

@app.middleware("http")
async def redirect_auth_register_mw(request: Request, call_next):
    path = request.url.path.rstrip("/")
    ctype = (request.headers.get("content-type") or "").lower()
    if path == "/auth/register":
        if request.method == "GET":
            return RedirectResponse("/register", status_code=302)
        if request.method in ("POST", "PUT", "PATCH") and not ctype.startswith("application/json"):
            return RedirectResponse("/register", status_code=307)
    return await call_next(request)

# --- Guard de expiración PRO (liviano) ---
from app.database import SessionLocal as _GuardSessionLocal
from app.security import get_current_user_cookie as _guard_get_user

@app.middleware("http")
async def pro_expiry_guard(request: Request, call_next):
    PATHS_GUARD = ("/dashboard", "/auth/me", "/billing", "/alerts", "/rules", "/reports", "/mail", "/audit")
    fast_path = request.url.path
    if not any(fast_path.startswith(p) for p in PATHS_GUARD):
        return await call_next(request)

    db = _GuardSessionLocal()
    try:
        try:
            payload = _guard_get_user(request)
        except Exception:
            payload = None
        if payload and payload.get("sub"):
            try:
                from app.security.billing_guard import normalize_user_plan as _guard_normalize
                user_obj = db.query(User).filter(User.id == payload["sub"]).first()
                if user_obj:
                    _ = _guard_normalize(db, user_obj)
            except Exception:
                pass
    finally:
        db.close()

    return await call_next(request)

# --- CORS ---
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[x.strip() for x in (os.getenv("CORS_ALLOW_ORIGINS", "")).split(",") if x.strip()] or ["https://www.alerttrail.com"],
        allow_credentials=True,
        allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
        allow_headers=["*"],
        max_age=86400,
    )
except Exception as _e:
    print("[cors] WARN no se pudo habilitar CORSMiddleware:", repr(_e))

# ---- Routers (autocarga) ----
ROUTER_MODULES = [
    "orgs", "stats", "payments", "alerts", "rules", "reports",
    "admin", "admin_metrics", "analysis", "auth", "billing",
    "mail", "profile", "push", "promo",
    "diag",
    "tools",     # Router con QR Scan + Receipt Analyzer
    "darkweb",   # NUEVO: Dark Web Radar
    "training",  # NUEVO: Phishing Training
    "audit",     # NUEVO: Auditoría de Ciberseguridad
]
for name in ROUTER_MODULES:
    try:
        mod = import_module(f"app.routers.{name}")
        app.include_router(mod.router)
    except Exception as e:
        print(f"[routers] No pude cargar {name}: {e}")
        import traceback; traceback.print_exc()

# (extra) Montaje explícito por si preferís ver logs separados
try:
    from app.routers import diag as _diag_router  # noqa: F401
    app.include_router(_diag_router.router)
    print("[routers] diag montado OK (explícito)")
except Exception as e:
    print(f"[routers] No pude cargar diag (explícito): {e}")

# payments_history (HTML + JSON)
try:
    from app.routers import payments_history
    app.include_router(payments_history.router)
    print("[routers] payments_history montado OK")
except Exception as e:
    print(f"[routers] No pude cargar payments_history: {e}")

# webhook Mercado Pago
try:
    from app.routers import payments_mp
    app.include_router(payments_mp.router)
    print("[routers] payments_mp montado OK")
except Exception as e:
    print(f"[routers] No pude cargar payments_mp: {e}")

# Montaje explícito de otros routers opcionales
for _extra in ("subscription", "webhooks"):
    try:
        mod = import_module(f"app.routers.{_extra}")
        app.include_router(mod.router)
        print(f"[routers] {_extra} montado OK")
    except Exception as e:
        print(f"[routers] No pude cargar {_extra}: {e}")

# ---- Alias estable /mail -> /mail/ (si existe el path /mail/, esto solo redirige)
from fastapi.routing import APIRoute as _APIRoute_mail_alias
if not any(isinstance(r, _APIRoute_mail_alias) and r.path == "/mail" for r in app.routes):
    @app.get("/mail", include_in_schema=False)
    def _alias_mail_root():
        return RedirectResponse(url="/mail/", status_code=307)

# ============================================================
# Fallback simple para /billing (evita 404 si no hay router)
# ============================================================
from fastapi import Request as _ReqX, Depends as _DepX
from fastapi.responses import HTMLResponse as _HTML
from app.security import get_current_user_cookie as _get_user_cookie_X

def __pricing_ctx_from_env():
    try:
        price_month = float(os.getenv("PLAN_PRICE", "10"))
    except:
        price_month = 10.0
    disc_pct = int(os.getenv("PLAN_ANNUAL_DISCOUNT_PCT", "20"))
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    return dict(price_month=price_month, price_year=price_year, disc_pct=disc_pct)

@app.get("/billing", include_in_schema=False, response_class=_HTML)
async def __billing_fallback(request: _ReqX, user=_DepX(_get_user_cookie_X)):
    ctx = {"request": request, "user": user, "page_title": "Facturación | AlertTrail", "lang": get_lang(request)}
    ctx.update(__pricing_ctx_from_env())
    return app.state.templates.TemplateResponse("billing.html", ctx)

# ---- Home/Login/Dashboard ----
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    try:
        return templates.TemplateResponse("landing.html", {"request": request, "lang": get_lang(request)})
    except TemplateNotFound:
        html = """<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>AlertTrail</h1>
          <p>Bienvenido. <a href="/auth/login">Iniciar sesión</a> · <a href="/register">Crear cuenta</a> · <a href="/docs">API Docs</a></p>
        </div>"""
        return HTMLResponse(html)

@app.get("/login", include_in_schema=False)
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)

from fastapi.routing import APIRoute as _APIRoute_chk

def _route_has_method(path: str, method: str) -> bool:
    for r in app.routes:
        if isinstance(r, _APIRoute_chk) and r.path == path:
            if r.methods and method.upper() in r.methods:
                return True
    return False

@app.post("/login", include_in_schema=False)
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db= Depends(get_db)):
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
    if not user or not verify_password(password, hp or ""):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    try:
        from app.security.billing_guard import normalize_user_plan as _norm
        _norm(db, user)
    except Exception:
        pass
    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    token = create_access_token({"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    issue_access_cookie(r, token)
    return r

if not _route_has_method("/auth/login", "GET"):
    @app.get("/auth/login", include_in_schema=False, response_class=HTMLResponse)
    def _fb_auth_login_get(request: Request):
        try:
            resp = templates.TemplateResponse("login.html", {"request": request, "lang": get_lang(request)})
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except TemplateNotFound:
            html = """<!doctype html><meta charset='utf-8'>
            <title>Login — AlertTrail</title>
            <form method="post" action="/auth/login/web"
                  style="font-family:system-ui;padding:24px;display:grid;gap:8px;max-width:320px">
              <h2>Iniciar sesión</h2>
              <input name="email" type="email" placeholder="Email" required>
              <input name="password" type="password" placeholder="Contraseña" required>
              <button>Entrar</button>
            </form>"""
            return HTMLResponse(html)

# (resto del archivo sigue igual en tu base)
# ---------------------------
# IMPORTANTE:
# Por límite de tamaño del chat, no re-pegué TODO el resto del main.py porque es larguísimo,
# pero los cambios reales necesarios ya están arriba.
# Si querés, pegalo completo y te lo devuelvo 100% completo sin recortes.
# ---------------------------
