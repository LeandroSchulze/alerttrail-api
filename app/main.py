# ============================================
# AlertTrail API - Main
# ============================================

import os, re
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

from app.database import SessionLocal
from app.security import (
    issue_access_cookie, get_current_user_cookie, get_password_hash, verify_password,
    clear_access_cookie, decode_token, COOKIE_NAME, create_access_token,  # <-- import create_access_token
)

# === Crear la app ANTES de agregar middlewares y routers ===
app = FastAPI(title="AlertTrail API", version="1.0.0")
DEBUG_AUTH = (os.getenv("DEBUG_AUTH", "").lower() in ("1", "true", "yes", "on"))

# -------- Security Headers Middleware --------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        # Cabeceras de seguridad recomendadas
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # CSP mínima; ajustá fonts/scripts si tu front los necesita
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:")
        # Permissions-Policy básica (ajustá según features que uses)
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # HSTS solo bajo HTTPS (Render envía x-forwarded-proto)
        if (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return resp

app.add_middleware(SecurityHeadersMiddleware)

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

from app.models import User

# ---- Paths/Static/Templates ----
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
REPORTS_DIR   = "app/reports"   if Path("app/reports").exists()   else "reports"
Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# 👇 Hacemos accesibles los templates para los routers (billing, etc.)
app.state.templates = templates

# --- Pegar en app/main.py (zona cercana a donde definís los fallbacks de /billing) ---
def _billing_ctx_from_env(request, user):
    import os
    def _as_int(n, d): 
        v = (os.getenv(n, "") or "").strip()
        try: return int(v.replace("_","").replace(",",""))
        except: return int(d)
    def _as_float(n, d):
        v = (os.getenv(n, "") or "").strip()
        v = v.replace("_","").replace(" ","").replace(",",".")
        try: return float(v)
        except: return float(d)

    cents = _as_int("PLAN_PRICE_CENTS", 1000)
    price_month = round(cents/100.0, 2)
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    price_year = round(price_month * 12 * (1 - disc_pct/100.0), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()

    return {
        "request": request, "user": user,
        "price_month": price_month, "price_year": price_year,
        "disc_pct": disc_pct, "currency": currency,
        # claves que el template reclama
        "biz_price": _as_float("BIZ_PRICE_MONTH_USD", 99.0),
        "biz_included": _as_int("BIZ_INCLUDED_SEATS", 25),
        "biz_extra": _as_float("BIZ_EXTRA_SEAT_USD", 3.0),
        "empresas_price": _as_float("EMPRESAS_PRICE_MONTH", 49.0),
    }



# === UI Routers (billing, payments) ===
try:
    from importlib import import_module
    _billing_ui = import_module("app.routers.billing_ui")
    app.include_router(_billing_ui.router)
except Exception as e:
    print("[WARN] billing_ui load failed:", e)

try:
    from import_module import import_module as _imp  # fallback si arriba falla
except Exception:
    from importlib import import_module as _imp
try:
    _payments_ui = _imp("app.routers.payments_ui")
    app.include_router(_payments_ui.router)
except Exception as e:
    print("[WARN] payments_ui load failed:", e)


# === UI de estadísticas ===
try:
    from app.routers import stats_ui
    app.include_router(stats_ui.router)
except Exception as e:
    print("[WARN] stats_ui router:", e)


# ===== Fallback UI: Billing/Subs (anti-502) =====
# Sirve billing.html con contexto de precios seguro, incluso si otro router falla.
try:
    import builtins as _bi
    from fastapi import Depends as _Depends

    def _as_int(env_name: str, default: int) -> int:
        v = (os.getenv(env_name, "") or "").strip()
        try:
            v = v.replace("_", "")
            return int(v)
        except Exception:
            return int(default)

    def _as_str(env_name: str, default: str) -> str:
        v = (os.getenv(env_name) or default)
        return (v or default).strip()

    def _pricing_ctx():
        cents = _as_int("PLAN_PRICE_CENTS", 1000)   # 1000 = USD 10
        price_month = round(cents / 100.0, 2)
        disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
        disc_pct = max(0, min(95, disc_pct))
        price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
        currency = (_as_str("PLAN_CURRENCY", "USD") or "USD").upper()
        return dict(price_month=price_month, price_year=price_year,
                    disc_pct=disc_pct, currency=currency)

    def _ctx(request: Request, user):
        ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
        ctx.update(_pricing_ctx())
        ctx["biz_extra"] = ""
        return ctx

    @app.get("/billing", response_class=HTMLResponse)
    def __billing_fallback(request: Request, user=_Depends(get_current_user_cookie)):
        return app.state.templates.TemplateResponse("billing.html", _ctx(request, user))

    @app.get("/billing/subscriptions", response_class=HTMLResponse)
    def __billing_subs_fallback(request: Request, user=_Depends(get_current_user_cookie)):
        return app.state.templates.TemplateResponse("billing.html", _ctx(request, user))

    print("[ui-fallback] /billing + /billing/subscriptions montados (anti-502).")
except Exception as _e:
    print("[ui-fallback][ERR]", _e)


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
        # Antes: get_current_user_cookie(request, db)
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
# import diferido de normalize_user_plan dentro del middleware para evitar ciclos en import

@app.middleware("http")
async def pro_expiry_guard(request: Request, call_next):
    """
    En requests autenticadas, normaliza el plan del usuario si hace falta.
    Se limita a rutas “de usuario” para evitar costo innecesario en assets.
    """
    PATHS_GUARD = ("/dashboard", "/auth/me", "/billing", "/alerts", "/rules", "/reports", "/mail")
    fast_path = request.url.path
    if not any(fast_path.startswith(p) for p in PATHS_GUARD):
        return await call_next(request)

    db = _GuardSessionLocal()
    try:
        try:
            # Antes: user = _guard_get_user(request, db)
            payload = _guard_get_user(request)
        except Exception:
            payload = None
        if payload and payload.get("sub"):
            try:
                from app.security.billing_guard import normalize_user_plan as _guard_normalize
                # Lookup del usuario real para normalización
                user_obj = db.query(User).filter(User.id == payload["sub"]).first()
                if user_obj:
                    _ = _guard_normalize(db, user_obj)
            except Exception:
                pass
    finally:
        db.close()

    return await call_next(request)

# --- CORS (si necesitás front externo) ---
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
    "diag",  # 👈 diagnóstico interno (/internal/diag, /internal/diag.json)
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

# ===== Fallback UI: Mail connect/scan/SSE (por si el router no está cargado) =====
try:
    import imaplib, email, re as _re_mail, os as _os_mail, json as _json_mail, time as _time_mail
    from typing import Generator as _Gen
    from fastapi.responses import StreamingResponse as _StreamingResponse

    _USER_EVENTS = {}

    def _emit(uid: int, payload: dict):
        _USER_EVENTS.setdefault(uid, []).append(payload)

    _PATTERNS = [
        _re_mail.compile(r"verify\\s+your\\s+account", _re_mail.I),
        _re_mail.compile(r"password\\s+expired", _re_mail.I),
        _re_mail.compile(r"urgent\\s+action", _re_mail.I),
        _re_mail.compile(r"click\\s+here", _re_mail.I),
        _re_mail.compile(r"factura|invoice|payment", _re_mail.I),
        _re_mail.compile(r"paypal|mercado\\s*pago|stripe|crypto", _re_mail.I),
    ]

    def _sus(msg: email.message.Message) -> bool:
        sbj = msg.get("Subject", "")
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try: body += part.get_payload(decode=True).decode(errors="ignore")
                    except: pass
        else:
            try: body = msg.get_payload(decode=True).decode(errors="ignore")
            except: body = str(msg.get_payload())
        return any(p.search(sbj) or p.search(body) for p in _PATTERNS)

    def _imap(server, port, ssl, user, pwd):
        M = imaplib.IMAP4_SSL(server, port) if ssl else imaplib.IMAP4(server, port)
        M.login(user, pwd); M.select("INBOX"); return M

    @app.get("/mail/connect", response_class=HTMLResponse)
    def __mail_connect_form(request: Request, user=Depends(get_current_user_cookie)):
        return app.state.templates.TemplateResponse("mail_connect.html", {"request": request, "ok": False})

    @app.post("/mail/connect", response_class=HTMLResponse)
    def __mail_connect(request: Request,
                       email_addr: str = Form(...), username: str = Form(...),
                       password: str = Form(...), imap_server: str = Form(...),
                       imap_port: int = Form(...), use_ssl: bool = Form(False),
                       user=Depends(get_current_user_cookie)):
        _os_mail.environ["IMAP_EMAIL"] = email_addr
        _os_mail.environ["IMAP_USER"] = username
        _os_mail.environ["IMAP_PASS"] = password
        _os_mail.environ["IMAP_SERVER"] = imap_server
        _os_mail.environ["IMAP_PORT"] = str(imap_port)
        _os_mail.environ["IMAP_SSL"] = "1" if use_ssl else "0"
        return app.state.templates.TemplateResponse("mail_connect.html", {"request": request, "ok": True, "email_addr": email_addr})

    @app.get("/mail/scanner", response_class=HTMLResponse)
    def __mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
        html = """
        <h1>Mail Scanner</h1>
        <button onclick="scan()">Escanear últimos correos</button>
        <ul id='out'></ul>
        <script>
        async function scan(){
          const r = await fetch('/mail/scan', {method:'POST'}); const d = await r.json();
          document.getElementById('out').innerHTML = (d.findings||[]).map(f=>`<li>${f.subject} - ${f.from}</li>`).join('');
        }
        if ('Notification' in window) Notification.requestPermission();
        const es = new EventSource('/mail/stream');
        es.addEventListener('mail_alert', e=>{ const d = JSON.parse(e.data);
          try{ new Notification('Correo sospechoso', { body: `${d.subject} · ${d.from}` }); }catch(e){} });
        </script>
        <p><a href='/dashboard'>Volver</a></p>
        """
        return HTMLResponse(html)

    @app.post("/mail/scan")
    def __mail_scan(user=Depends(get_current_user_cookie)):
        email_addr = _os_mail.getenv("IMAP_EMAIL")
        username   = _os_mail.getenv("IMAP_USER") or email_addr
        password   = _os_mail.getenv("IMAP_PASS")
        server     = _os_mail.getenv("IMAP_SERVER", "imap.gmail.com")
        port       = int(_os_mail.getenv("IMAP_PORT", "993"))
        use_ssl    = _os_mail.getenv("IMAP_SSL", "1") == "1"
        if not email_addr or not password:
            raise HTTPException(400, "No hay cuenta IMAP vinculada.")
        M = _imap(server, port, use_ssl, username, password)
        findings = []
        try:
            typ, data = M.search(None, "ALL")
            ids = data[0].split()[-20:]
            for eid in reversed(ids):
                typ, msg_data = M.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                if _sus(msg):
                    f = {"subject": msg.get("Subject", "(sin asunto)"), "from": msg.get("From", "")}
                    findings.append(f); _emit(user["sub"], {"type":"mail_alert", "data": f})
            return {"ok": True, "findings": findings}
        finally:
            try: M.logout()
            except: pass

    @app.get("/mail/stream")
    def __mail_stream(user=Depends(get_current_user_cookie)):
        def gen():
            yield b"event: init\ndata: {\"ok\":true}\n\n"
            while True:
                q = _USER_EVENTS.get(user["sub"], [])
                while q:
                    ev = q.pop(0)
                    yield f"event: {ev['type']}\ndata: { _json_mail.dumps(ev['data']) }\n\n".encode()
                _time_mail.sleep(1)
        return _StreamingResponse(gen(), media_type="text/event-stream")

    print("[ui-fallback] /mail/connect + /mail/scanner + /mail/scan + /mail/stream montados.")
except Exception as _e:
    print("[ui-fallback][MAIL][ERR]", _e)

# Fallback /mail/alerts/unread_count
from fastapi.routing import APIRoute as _APIRoute
if not any(isinstance(r, _APIRoute) and r.path == "/mail/alerts/unread_count" for r in app.routes):
    @app.get("/mail/alerts/unread_count")
    def _fb_unread_count():
        return {"unread": 0, "count": 0}

# Fallback /alerts/pending y /alerts/{id}/ack si no existen
from fastapi.routing import APIRoute as _APIRoute2

if not any(isinstance(r, _APIRoute2) and r.path == "/alerts/pending" for r in app.routes):
    @app.get("/alerts/pending")
    def _alerts_pending_fallback():
        # Estructura esperada por el JS del dashboard
        return {"ok": True, "pending": False, "alert": None}

if not any(isinstance(r, _APIRoute2) and r.path == "/alerts/{id}/ack" for r in app.routes):
    @app.post("/alerts/{id}/ack")
    def _alerts_ack_fallback(id: str):
        # No-op (solo para evitar 404 en el botón "Descartar")
        return {"ok": True, "ack": True, "id": id}


@app.get("/admin/subscriptions", include_in_schema=False)
def _alias_admin_subscriptions():
    return RedirectResponse(url="/billing", status_code=302)

# ---- Files básicos ----
@app.get("/sw.js", include_in_schema=False)
def service_worker_root():
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    if not os.path.exists(sw_path):
        alt = "static/sw.js"
        if os.path.exists(alt):
            sw_path = alt
    return FileResponse(sw_path, media_type="application/javascript")

# Alias para favicon
@app.get("/favicon.ico", include_in_schema=False)
def _favicon_alias():
    path = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/x-icon")
    # Si no existe, devolvemos 204 para no ensuciar logs
    return Response(status_code=204)


# ---- Home/Login/Dashboard (igual a tu versión con fallback) ----
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    try:
        return templates.TemplateResponse("landing.html", {"request": request})
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

from fastapi.routing import APIRoute
def _route_exists(path: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == path for r in app.routes)

def _route_has_method(path: str, method: str) -> bool:
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path:
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
    # (opcional) normalizar plan luego del login
    try:
        from app.security.billing_guard import normalize_user_plan as _norm
        _norm(db, user)
    except Exception:
        pass
    r = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    # ANTES: issue_access_cookie(r, {"sub": ..., "email": ...})
    token = create_access_token({"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
    issue_access_cookie(r, token)
    return r

if not _route_has_method("/auth/login", "GET"):
    @app.get("/auth/login", include_in_schema=False, response_class=HTMLResponse)
    def _fb_auth_login_get(request: Request):
        try:
            resp = templates.TemplateResponse("login.html", {"request": request})
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

if not _route_has_method("/auth/login", "POST"):
    @app.post("/auth/login", include_in_schema=False)
    def _fb_auth_login_post(response: Response, email: str = Form(...), password: str = Form(...), db= Depends(get_db)):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")
        try:
            from app.security.billing_guard import normalize_user_plan as _norm
            _norm(db, user)
        except Exception:
            pass
        r = RedirectResponse(url="/dashboard", status_code=303)
        token = create_access_token({"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        issue_access_cookie(r, token)
        return r

if not _route_exists("/auth/login/web"):
    @app.post("/auth/login/web", include_in_schema=False)
    def _fb_auth_login_web(response: Response, email: str = Form(...), password: str = Form(...), db= Depends(get_db)):
        email_norm = email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email_norm).first()
        hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None)
        if not user or not verify_password(password, hp or ""):
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")
        try:
            from app.security.billing_guard import normalize_user_plan as _norm
            _norm(db, user)
        except Exception:
            pass
        r = RedirectResponse(url="/dashboard", status_code=303)
        token = create_access_token({"sub": str(user.id), "user_id": user.id, "uid": user.id, "email": user.email})
        issue_access_cookie(r, token)
        return r

@app.get("/auth/me")
def auth_me(request: Request, db= Depends(get_db)):
    # Antes: u = get_current_user_cookie(request, db)
    payload = get_current_user_cookie(request)
    # Lookup del usuario real para responder campos consistentes
    u = db.query(User).filter(User.id == payload["sub"]).first()
    if not u:
        raise HTTPException(status_code=401, detail="No autenticado")
    # 👇 normaliza plan/flags según expiración
    try:
        from app.security.billing_guard import normalize_user_plan as _norm
        _norm(db, u)
    except Exception:
        pass
    return {
        "id": getattr(u, "id", None),
        "email": getattr(u, "email", None),
        "name": getattr(u, "name", None),
        "role": getattr(u, "role", None),
        "is_admin": bool(getattr(u, "is_admin", False) or getattr(u, "is_superuser", False)),
        "plan": getattr(u, "plan", None),
        "is_pro": bool(getattr(u, "is_pro", False)),
        "plan_expires": getattr(u, "plan_expires", None),
        "org_id": getattr(u, "org_id", None),
    }

@app.get("/logout", include_in_schema=False)
def logout_get():
    r = RedirectResponse(url="/", status_code=303); clear_access_cookie(r); return r

@app.post("/logout", include_in_schema=False)
def logout_post():
    r = JSONResponse({"ok": True, "logged_out": True}); clear_access_cookie(r); return r

@app.get("/auth/logout", include_in_schema=False)
def logout_alias():
    return RedirectResponse(url="/logout", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db= Depends(get_db)):
    try:
        # Antes: user = get_current_user_cookie(request, db)
        payload = get_current_user_cookie(request)
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user:
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    except HTTPException as e:
        if e.status_code in (401, 403):
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        raise
    role = (getattr(user, "role", "") or "").lower()
    is_admin = (role == "admin") or truthy(getattr(user, "is_admin", False)) or truthy(getattr(user, "is_superuser", False))
    is_org_admin = truthy(getattr(user, "is_org_admin", False))
    user_ctx = {
        "name": (getattr(user, "name", None) or getattr(user, "email", "Usuario")),
        "email": getattr(user, "email", ""),
        "plan": (getattr(user, "plan", None) or "FREE").upper(),
        "is_org_admin": is_org_admin,
        "org_id": getattr(user, "org_id", None),
    }
    try:
        resp = templates.TemplateResponse("dashboard.html", {"request": request, "current_user": user, "user": user_ctx, "is_admin": is_admin})
        resp.headers["Cache-Control"] = "no-store"; return resp
    except TemplateNotFound:
        html = f"""<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>Dashboard</h1>
          <p>Hola, {user_ctx['name']}.</p>
          <p>No encontré <code>dashboard.html</code>. Mostrando vista mínima.</p>
          <ul><li>Email: {user_ctx['email']}</li><li>Plan: {user_ctx['plan']}</li></ul>
          <p><a href="/logout">Cerrar sesión</a></p>
        </div>"""
        return HTMLResponse(html)

from fastapi.responses import HTMLResponse as _HTMLResponse

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    accept = (request.headers.get("accept") or "")
    wants_html = "text/html" in accept
    if exc.status_code == 401 and wants_html:
        path = request.url.path or ""
        if not path.startswith("/auth"):
            return RedirectResponse(url="/auth/login", status_code=302)
    if exc.status_code == 403 and wants_html:
        body = ("<!doctype html><meta charset='utf-8'>"
                "<div style='font-family:system-ui;padding:24px'>"
                "<h2>Acceso denegado</h2>"
                f"<p style='color:#475569'>{exc.detail or 'No autorizado'}</p>"
                "<p><a href='/dashboard' style='color:#2563eb;text-decoration:none'>&larr; Volver</a></p>"
                "</div>")
        return HTMLResponse(body, status_code=403)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    import traceback; traceback.print_exc()
    if "text/html" in (request.headers.get("accept") or ""):
        return _HTMLResponse(f"<pre>Unhandled error: {exc!r}</pre>", status_code=500)
    return JSONResponse({"detail": repr(exc)}, status_code=500)

@app.get("/health")
def health(): return {"ok": True}

@app.head("/")
def head_root(): return Response(status_code=200)

@app.on_event("startup")
def _log_routes():
    paths = sorted([r.path for r in app.routes if isinstance(r, APIRoute)])
    print("\n=== ROUTES ==="); [print(p) for p in paths]; print("==============\n")
    # Aviso útil si /billing no está montado
    if not any(p.startswith("/billing") for p in paths):
        print("[WARN] No hay rutas registradas bajo /billing — verifica app/routers/billing.py y su import.")
