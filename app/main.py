# app/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

from app.i18n import get_lang_from_request, jinja_t, set_lang_cookie
from app.security import get_current_user_cookie

# Routers
from app.routers import auth, analysis, mail, admin  # ajustá si tenés otros


APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/var/data/reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AlertTrail", version="1.0.0")

# CORS (si lo necesitás)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates + globals Jinja
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = jinja_t  # en Jinja: {{ t(lang, "key") }}

# Guardamos templates en app.state para routers (evita circular imports)
app.state.templates = templates

# Static y Reports
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

# Include routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard", status_code=302)


# Alias /login -> /auth/login (porque el browser estaba yendo a /login)
@app.get("/login")
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/set-lang/{lang}")
def set_lang(lang: str):
    resp = RedirectResponse(url="/dashboard", status_code=302)
    set_lang_cookie(resp, lang)
    return resp


@app.get("/dashboard")
def dashboard(request: Request):
    # si no está logueado => redirect a login
    try:
        user = get_current_user_cookie(request)
    except Exception:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    # Si el lang vino por query, seteamos cookie para persistir
    qlang = (request.query_params.get("lang") or "").strip().lower()[:2]
    resp = templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "user": user,
            "current_user": user,
        },
    )
    if qlang in ("es", "en"):
        set_lang_cookie(resp, qlang)
    return resp


# Debug rápido para ver si cargan traducciones
@app.get("/_debug/i18n")
def debug_i18n():
    from app.i18n import i18n_debug
    return JSONResponse(i18n_debug())
