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

# --- Middleware para exponer lang en templates (desde cookie "lang") ---
class LangContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        try:
            ctx = getattr(resp, "context", None) or getattr(resp, "template_context", None)
            if ctx is not None and "lang" not in ctx:
                ctx["lang"] = (request.cookies.get("lang") or "es").lower()[:2]
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
    PATHS_GUARD = ("/dashboard", "/auth/me", "/billing", "/alerts", "/rules", "/reports", "/mail")
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
    "tools",  # Router con QR Scan + Receipt Analyzer (se incluye UNA sola vez)
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
    ctx = {"request": request, "user": user, "page_title": "Facturación | AlertTrail"}
    ctx.update(__pricing_ctx_from_env())
    return app.state.templates.TemplateResponse("billing.html", ctx)

# ---- Fallback MAIL si el router no cargó ----
def _route_exists(path: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == path for r in app.routes)

if not _route_exists("/mail/"):
    print("[routers] WARN: /mail/ no registrado — activando fallback con settings/connect/scan")

    from fastapi import APIRouter
    import imaplib, socket, email
    from email.header import decode_header
    from typing import List, Optional
    from pydantic import BaseModel

    mail_router = APIRouter(prefix="/mail", tags=["mail"])

    DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LINK_FILE = DATA_DIR / "mail_link.json"

    def _env_bool(v: str, default=False) -> bool:
        if v is None: return default
        return str(v).strip().lower() in {"1","true","yes","y","on"}

    def _load_linked():
        if LINK_FILE.exists():
            try:
                return json.loads(LINK_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_linked(data: dict):
        LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _defaults_from_env():
        return dict(
            host=os.getenv("MAIL_HOST", "imap.gmail.com"),
            port=int(os.getenv("MAIL_PORT", "993") or 993),
            use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
            username=os.getenv("MAIL_USERNAME", ""),
            folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
            mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
        )

    class MailItem(BaseModel):
        uid: str
        from_email: Optional[str] = None
        subject: Optional[str] = None
        snippet: Optional[str] = None
        date: Optional[str] = None
        flags: Optional[List[str]] = None
        suspicious: bool = False
        score: float = 0.0
        reason: Optional[str] = None
        link: Optional[str] = None

    class ScanResult(BaseModel):
        ok: bool
        login: bool
        folder: str
        unread: int
        total: int
        marked_seen: bool
        message: Optional[str] = None
        items: List[MailItem] = []

    def _decode_hdr(v):
        if not v:
            return ""
        if isinstance(v, bytes):
            try:
                v = v.decode("utf-8", "ignore")
            except Exception:
                v = v.decode("latin-1", "ignore")
        parts = decode_header(v)
        out = []
        for txt, enc in parts:
            if isinstance(txt, bytes):
                try:
                    out.append(txt.decode(enc or "utf-8", "ignore"))
                except Exception:
                    out.append(txt.decode("latin-1", "ignore"))
            else:
                out.append(txt)
        return "".join(out).strip()

    def _score_suspicious(subj: str, snip: str):
        text = f"{subj} {snip}".lower()
        kws = ["verify", "verificar", "password", "contraseña", "urgent", "urgente",
               "invoice", "factura", "payment", "pago", "bank", "banco", "reset"]
        hits = [k for k in kws if k in text]
        score = min(1.0, len(hits) * 0.2)
        return score, ", ".join(hits)

    def _fetch_items(imap, folder, limit=50):
        typ, data = imap.uid("search", None, "ALL")
        uids = (data[0] or b"").split() if typ == "OK" else []
        uids = uids[-limit:]
        items = []
        for uid in reversed(uids):
            try:
                typ, data = imap.uid("fetch", uid, b"(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.512>)")
                if typ != "OK" or not data:
                    continue
                hdr_raw = b""
                snippet_raw = b""
                for part in data:
                    if not isinstance(part, tuple):
                        continue
                    block = part[1] or b""
                    if b"HEADER.FIELDS" in part[0]:
                        hdr_raw += block
                    elif b"TEXT" in part[0]:
                        snippet_raw += block
                msg = email.message_from_bytes(hdr_raw or b"")
                from_email = _decode_hdr(msg.get("From"))
                subject = _decode_hdr(msg.get("Subject"))
                date = _decode_hdr(msg.get("Date"))
                snippet = (snippet_raw or b"").decode("utf-8", "ignore")[:250]
                score, reason = _score_suspicious(subject, snippet)
                items.append(MailItem(
                    uid=uid.decode(),
                    from_email=from_email,
                    subject=subject,
                    date=date,
                    snippet=snippet,
                    suspicious=score >= 0.5,
                    score=score,
                    reason=reason,
                    link=f"/mail/scanner?id={uid.decode()}",
                ))
            except Exception:
                continue
        return items

    import socket, imaplib, email  # ensure in scope
    from email.header import decode_header

    def _scan_impl():
        host = os.getenv("MAIL_HOST", "imap.gmail.com")
        port = int(os.getenv("MAIL_PORT", "993") or 993)
        use_ssl = _env_bool(os.getenv("MAIL_USE_SSL", "true"), True)
        username = os.getenv("MAIL_USERNAME", "")
        password = os.getenv("MAIL_PASSWORD", "")
        folder = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
        mark_seen = _env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False)

        if not username or not password:
            raise HTTPException(status_code=400, detail="Faltan MAIL_USERNAME o MAIL_PASSWORD")

        try:
            imap = imaplib.IMAP4_SSL(host, port, timeout=30) if use_ssl else imaplib.IMAP4(host, port, timeout=30)
            typ, _ = imap.login(username, password)
            if typ != "OK":
                return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message="Login IMAP falló", items=[])
            typ, _ = imap.select(folder, readonly=not mark_seen)
            if typ != "OK":
                return ScanResult(ok=False, login=True, folder=folder, unread=0, total=0, marked_seen=False, message=f"No se pudo abrir {folder}", items=[])
            typ, data = imap.search(None, "ALL")
            total = len((data[0] or b"").split()) if typ == "OK" else 0
            typ, data = imap.search(None, "UNSEEN")
            unseen_ids = (data[0] or b"").split() if typ == "OK" else []
            unread = len(unseen_ids)
            items = _fetch_items(imap, folder)
            try:
                imap.close(); imap.logout()
            except Exception:
                pass
            return ScanResult(ok=True, login=True, folder=folder, unread=unread, total=total, marked_seen=False, message=None, items=items)
        except (imaplib.IMAP4.error, socket.timeout) as e:
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=str(e), items=[])
        except Exception as e:
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=f"Error: {e}", items=[])

    @mail_router.get("/", response_class=HTMLResponse)
    def mail_index(request: Request, user=Depends(get_current_user_cookie)):
        linked = _load_linked().get(str(user["sub"]))
        ctx = {"request": request, "page_title": "Casillas de correo", "current_user": user,
               "defaults": _defaults_from_env(), "linked": linked}
        try:
            return app.state.templates.TemplateResponse("mail.html", ctx)
        except TemplateNotFound:
            html = """<!doctype html><meta charset='utf-8'>
            <div style="font-family:system-ui;padding:24px">
              <h1>Mail</h1>
              <p>Cuenta guardada: <b>{}</b></p>
              <p><a href="/mail/scanner">Ir al scanner</a></p>
            </div>""".format((linked or {}).get("address","-"))
            return HTMLResponse(html)

    @mail_router.post("/settings")
    def mail_settings(address: str = Form(...), user=Depends(get_current_user_cookie)):
        address = (address or "").strip().lower()
        if not address or "@" not in address:
            raise HTTPException(status_code=400, detail="Dirección inválida")
        data = _load_linked()
        data[str(user["sub"])] = {"address": address}
        _save_linked(data)
        return RedirectResponse(url="/mail/", status_code=303)

    @mail_router.post("/connect")
    def mail_connect(address: str = Form(...), user=Depends(get_current_user_cookie)):
        address = (address or "").strip().lower()
        if not address or "@" not in address:
            raise HTTPException(status_code=400, detail="Dirección inválida")
        data = _load_linked()
        data[str(user["sub"])] = {"address": address}
        _save_linked(data)
        return RedirectResponse(url="/mail/", status_code=303)

    @mail_router.get("/scanner", response_class=HTMLResponse)
    def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
        ctx = {"request": request, "page_title": "Mail Scanner", "current_user": user, "defaults": _defaults_from_env(),
               "linked": _load_linked().get(str(user["sub"]))}
        try:
            return app.state.templates.TemplateResponse("mail_scanner.html", ctx)
        except TemplateNotFound:
            return HTMLResponse("<h1>Mail Scanner</h1>")

    @mail_router.get("/scan", response_model=ScanResult)
    @mail_router.post("/scan", response_model=ScanResult)
    def mail_scan(user=Depends(get_current_user_cookie)):
        return _scan_impl()

    app.include_router(mail_router)

# ---- Fallback /mail/alerts/unread_count
from fastapi.routing import APIRoute as _APIRoute_1
if not any(isinstance(r, _APIRoute_1) and r.path == "/mail/alerts/unread_count" for r in app.routes):
    @app.get("/mail/alerts/unread_count")
    def _fb_unread_count():
        return {"unread": 0, "count": 0}

# Fallback /alerts/pending y /alerts/{id}/ack
from fastapi.routing import APIRoute as _APIRoute_2

if not any(isinstance(r, _APIRoute_2) and r.path == "/alerts/pending" for r in app.routes):
    @app.get("/alerts/pending")
    def _alerts_pending_fallback():
        return {"ok": True, "pending": False, "alert": None}

if not any(isinstance(r, _APIRoute_2) and r.path == "/alerts/{id}/ack" for r in app.routes):
    @app.post("/alerts/{id}/ack")
    def _alerts_ack_fallback(id: str):
        return {"ok": True, "ack": True, "id": id}

# ---- Fallback UI para /alerts y /rules si no hay router dedicado ----
from fastapi.routing import APIRoute as _APIRoute_ui

def _route_exists_ui(path: str) -> bool:
    return any(isinstance(r, _APIRoute_ui) and r.path == path for r in app.routes)

# /alerts (UI)
if not _route_exists_ui("/alerts"):
    @app.get("/alerts", response_class=HTMLResponse)
    def _alerts_ui(request: Request, user=Depends(get_current_user_cookie)):
        try:
            return templates.TemplateResponse("alerts.html", {
                "request": request,
                "page_title": "Alertas",
                "current_user": user
            })
        except TemplateNotFound:
            return HTMLResponse("<h1>Alertas</h1><p>Acá iría el listado de alertas.</p>")

# ✅ /alerts/list (API) — placeholder compatible con alerts.html
if not _route_exists_ui("/alerts/list"):
    @app.get("/alerts/list")
    def _alerts_list(q: str = "", sev: str = "", status: str = "", days: str = "7",
                     user=Depends(get_current_user_cookie)):
        return {"ok": True, "items": [], "total": 0}

# /rules (UI)
if not _route_exists_ui("/rules"):
    @app.get("/rules", response_class=HTMLResponse)
    def _rules_ui(request: Request, user=Depends(get_current_user_cookie)):
        try:
            return templates.TemplateResponse("rules.html", {
                "request": request,
                "page_title": "Reglas personalizadas",
                "current_user": user
            })
        except TemplateNotFound:
            return HTMLResponse("<h1>Reglas</h1><p>Configura tus reglas personalizadas acá.</p>")

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

@app.get("/favicon.ico", include_in_schema=False)
def _favicon_alias():
    path = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/x-icon")
    return Response(status_code=204)

# ---------- UI dinámica para reportes ----------
if not _route_exists_ui("/reports_browser"):
    @app.get("/reports_browser", response_class=HTMLResponse)
    def reports_browser(request: Request, user=Depends(get_current_user_cookie)):
        rows = []
        try:
            for p in sorted(Path(REPORTS_DIR).glob("*")):
                if p.is_file():
                    size = p.stat().st_size
                    mtime = p.stat().st_mtime
                    rows.append(
                        f"<tr>"
                        f"<td><a href='/reports/{p.name}' download>{p.name}</a></td>"
                        f"<td>{size} bytes</td>"
                        f"<td>{__import__('datetime').datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')}</td>"
                        f"</tr>"
                    )
        except Exception as e:
            rows = [f"<tr><td colspan='3' class='muted'>Error listando reportes: {e}</td></tr>"]

        if not rows:
            rows = ["<tr><td colspan='3' class='muted'>No hay archivos todavía.</td></tr>"]

        html = f"""<!doctype html>
<meta charset="utf-8">
<title>Reportes — AlertTrail</title>
<link rel="stylesheet" href="/static/style.css">
<style>
  body{{font-family:system-ui;padding:24px;color:#0f172a}}
  table{{border-collapse:collapse;width:100%;max-width:900px}}
  th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}}
  .muted{{color:#64748b}}
</style>
<h1>Reportes</h1>
<p class="muted">Descargá tus archivos generados.</p>
<table>
  <thead><tr><th>Archivo</th><th>Tamaño</th><th>Fecha</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""
        return HTMLResponse(html)

# ---- Home/Login/Dashboard ----
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
    payload = get_current_user_cookie(request)
    u = db.query(User).filter(User.id == payload["sub"]).first()
    if not u:
        raise HTTPException(status_code=401, detail="No autenticado")
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
        lang = (request.cookies.get("lang") or "es").lower()[:2]
        resp = templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "current_user": user, "user": user_ctx, "is_admin": is_admin, "lang": lang}
        )
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
    if not any(p.startswith("/billing") for p in paths):
        print("[WARN] No hay rutas registradas bajo /billing — verifica app/routers/billing.py y su import.")

@app.get("/api/reports/list")
def api_reports_list():
    files = []
    try:
        for p in sorted(Path(REPORTS_DIR).glob("*")):
            if p.is_file():
                files.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": int(p.stat().st_mtime)
                })
    except Exception as e:
        return {"ok": False, "error": str(e), "files": []}
    return {"ok": True, "files": files}

# ============================================================
# Fallback robusto para /billing/subscriptions
# ============================================================
from decimal import Decimal

def __as_int(v, d):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return d

def __as_money(v, d):
    try:
        return float(Decimal(str(v).replace(",", ".")))
    except Exception:
        return float(d)

def __pricing_ctx_from_env_full():
    if os.getenv("PLAN_PRICE_CENTS"):
        try:
            cents = int(os.getenv("PLAN_PRICE_CENTS", "1000"))
        except Exception:
            cents = 1000
        price_month = round(cents / 100.0, 2)
    else:
        price_month = round(__as_money(os.getenv("PLAN_PRICE", "10"), 10.0), 2)

    disc_pct = __as_int(os.getenv("PLAN_ANNUAL_DISCOUNT_PCT", "20"), 20)
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()

    biz_price = round(__as_money(os.getenv("BIZ_PRICE_MONTH_USD", "99"), 99.0), 2)
    biz_included = __as_int(os.getenv("BIZ_INCLUDED_SEATS", "25"), 25)
    biz_extra = round(__as_money(os.getenv("BIZ_EXTRA_SEAT_USD", "3"), 3.0), 2)

    return dict(
        price_month=price_month,
        price_year=price_year,
        disc_pct=disc_pct,
        currency=currency,
        biz_price=biz_price,
        biz_included=biz_included,
        biz_extra=biz_extra,
    )

from fastapi.responses import HTMLResponse as _HTML
@app.get("/billing/subscriptions", include_in_schema=False, response_class=_HTML)
def __billing_subs_fallback(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(__pricing_ctx_from_env_full())
    return app.state.templates.TemplateResponse("billing.html", ctx)
