# app/main.py
import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from app.database import get_db
from app.security import get_current_user_cookie

APP_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app = FastAPI(title="AlertTrail API")

# --- CORS laxo para frontend simple (ajustá orígenes si tenés dominio propio)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- /static: montarlo sólo si existe para evitar RuntimeError
STATIC_DIR = os.path.join(APP_DIR, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    print("[main] aviso: no existe app/static, no se monta /static")

# --- Inclusión de routers (a prueba de balas) -------------------------------
def _include_router_safely(label: str, import_path: str):
    try:
        module = __import__(import_path, fromlist=["router"])
        app.include_router(getattr(module, "router"))
        print(f"[main] router {label} OK")
    except Exception as e:
        print(f"[main] router {label} ERROR: {e}")

# Obligatorios / existentes en tu proyecto
_include_router_safely("auth",      "app.routers.auth")       # /auth/*
_include_router_safely("billing",   "app.routers.billing")    # /billing/*
_include_router_safely("admin",     "app.routers.admin")      # /admin/*
_include_router_safely("analysis",  "app.routers.analysis")   # /analysis/*
_include_router_safely("mail",      "app.routers.mail")       # ✅ /mail/*
_include_router_safely("tasks_mail","app.routers.tasks_mail") # /tasks/mail/*
_include_router_safely("alerts",    "app.routers.alerts")     # /alerts/*

# --- Rutas básicas HTML ------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    # Mandamos directo al dashboard (la vista ya maneja auth)
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    """
    Render del login HTML.
    El formulario de tu template debe postear a: /auth/login/web
    """
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, db=Depends(get_db)):
    """
    Dashboard principal (requiere cookie de sesión).
    Pasa al template: user_name, user_email, user_plan (FREE/PRO).
    """
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ctx = {
        "request": request,
        "user_name": getattr(user, "name", "") or "Usuario",
        "user_email": getattr(user, "email", "") or "",
        "user_plan": getattr(user, "plan", "") or "free",
    }
    return templates.TemplateResponse("dashboard.html", ctx)

# --- Salud / util ------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health():
    return {"ok": True, "service": "alerttrail-api"}

# (Opcional) para comprobar qué routers quedaron montados
@app.get("/_debug/routers", include_in_schema=False)
def debug_routers():
    return {"routes": [r.path for r in app.routes]}
