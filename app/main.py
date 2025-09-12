import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
from jinja2 import TemplateNotFound

from app.database import SessionLocal
from app.models import User
from app.security import decode_token, COOKIE_NAME

# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlertTrail",
    version="1.0.0",
    description="AlertTrail API: Dashboard, Log Scanner (PDF) y Mail Scanner",
)

# CORS (amplio para pruebas)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# Directorios y montajes
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))     # .../app
ROOT_DIR = os.path.dirname(BASE_DIR)                      # repo root

REPORTS_DIR = os.getenv("REPORTS_DIR", os.path.join(ROOT_DIR, "reports"))
STATIC_DIR   = os.path.join(ROOT_DIR, "static")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _current_user_from_cookie(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == payload.get("sub")).first()
    finally:
        db.close()

def _try_include_router(import_path: str, attr: str = "router", prefix: str | None = None, tags: list[str] | None = None):
    try:
        module = __import__(import_path, fromlist=[attr])
        router = getattr(module, attr, None)
        if router is not None:
            app.include_router(router, prefix=prefix or "", tags=tags or [])
    except Exception:
        # Silencioso: si el router no existe, no rompe el deploy
        pass

# ──────────────────────────────────────────────────────────────────────────────
# Rutas UI
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root(request: Request):
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        return templates.TemplateResponse("index.html", {"request": request})
    # Fallback si no hay template
    html = """
    <!doctype html><html><head><meta charset="utf-8"><title>AlertTrail</title>
    <link rel="stylesheet" href="/static/style.css"></head><body class="app">
    <main class="shell">
      <h1>AlertTrail</h1>
      <ul>
        <li><a href="/dashboard">Ir al Dashboard</a></li>
        <li><a href="/docs">API Docs (Swagger)</a></li>
        <li><a href="/health">Health</a></li>
      </ul>
    </main></body></html>
    """
    return HTMLResponse(html)

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    # Render login.html si existe; si no, fallback mínimo
    try:
        return templates.TemplateResponse("login.html", {"request": request})
    except TemplateNotFound:
        html = """
        <!doctype html><html><head><meta charset="utf-8"><title>Login</title>
        <link rel="stylesheet" href="/static/style.css"></head><body class="app">
        <main class="shell">
          <h1>Iniciar sesión</h1>
          <form class="card" method="post" action="/auth/login/web">
            <label>Email<br><input name="email" type="email" required></label><br/>
            <label>Contraseña<br><input name="password" type="password" required></label><br/>
            <button class="btn primary" type="submit">Entrar</button>
          </form>
        </main></body></html>
        """
        return HTMLResponse(html)

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    # Usuario (si hay cookie); si no, Invitado
    user = _current_user_from_cookie(request)
    ctx_user = {"name": getattr(user, "name", "Invitado")}
    try:
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": ctx_user})
    except TemplateNotFound:
        # Fallback si falta templates/dashboard.html — evita 500
        html = f"""
        <!doctype html><html><head><meta charset="utf-8">
        <title>Dashboard - AlertTrail</title>
        <link rel="stylesheet" href="/static/style.css"></head>
        <body class="app"><main class="shell">
          <h1>Dashboard</h1>
          <p class="muted">Usuario: {ctx_user['name']}</p>
          <section class="grid">
            <article class="card">
              <h2>Log Scanner</h2>
              <a class="btn" href="/analysis/generate_pdf" target="_blank">Generar PDF</a>
              <a class="btn ghost" href="/reports" target="_blank">Ver reportes</a>
            </article>
            <article class="card">
              <h2>Mail Scanner</h2>
              <a class="btn" href="/mail/scan" target="_blank">Escanear Mail</a>
            </article>
          </section>
        </main></body></html>
        """
        return HTMLResponse(html, status_code=200)

@app.get("/api", include_in_schema=False)
def api_root():
    return RedirectResponse("/docs")

@app.get("/health", tags=["health"])
def health():
    return JSONResponse({"status": "ok"})

# ──────────────────────────────────────────────────────────────────────────────
# Inclusión de routers
# ──────────────────────────────────────────────────────────────────────────────
_try_include_router("app.routers.auth",     prefix="/auth",     tags=["auth"])
_try_include_router("app.routers.analysis", prefix="/analysis", tags=["analysis"])
_try_include_router("app.routers.mail",     prefix="/mail",     tags=["mail"])
_try_include_router("app.routers.admin",    prefix="/admin",    tags=["admin"])
# (opcional si existen)
_try_include_router("app.routers.profile",  prefix="/profile",  tags=["profile"])
_try_include_router("app.routers.settings", prefix="/settings", tags=["settings"])
