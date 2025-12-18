# app/main.py
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.security import get_current_user_cookie
from app.i18n import get_lang, t, set_lang_cookie
from app.ui import templates

from app.routers import auth, analysis, mail

# opcionales
try:
    from app.routers import alerts
except Exception:
    alerts = None

try:
    from app.routers import tools
except Exception:
    tools = None

try:
    from app.routers import billing
except Exception:
    billing = None

try:
    from app.routers import reports
except Exception:
    reports = None


app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(Path("/var/data/reports"))))

STATIC_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

# ✅ estado global para routers/templates (evita circular import)
app.state.templates = templates
app.state.t = t
app.state.get_lang = get_lang

# Routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
if alerts:
    app.include_router(alerts.router)
if tools:
    app.include_router(tools.router)
if billing:
    app.include_router(billing.router)
if reports:
    app.include_router(reports.router)


def _safe_next(next_url: Optional[str]) -> str:
    if not next_url:
        return "/dashboard"
    if next_url.startswith("http://") or next_url.startswith("https://"):
        return "/dashboard"
    if not next_url.startswith("/"):
        return "/dashboard"
    return next_url


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/login", include_in_schema=False)
def legacy_login():
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/set-lang", include_in_schema=False)
def set_lang(request: Request):
    lang = (request.query_params.get("lang") or "").lower()[:2]
    nxt = _safe_next(request.query_params.get("next"))
    resp = RedirectResponse(url=nxt, status_code=302)
    return set_lang_cookie(resp, lang)


@app.get("/reports_browser", include_in_schema=False)
def legacy_reports_browser():
    return RedirectResponse(url="/reports", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)

    role = (user or {}).get("role") or ""
    plan = (user or {}).get("plan") or "FREE"
    if str(role).lower() == "admin":
        plan = "PRO"

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "me": user,
            "plan": plan,
        },
    )


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
