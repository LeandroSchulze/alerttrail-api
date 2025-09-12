from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
import os

# ──────────────────────────────────────────────────────────────────────────────
# Config básica de la app
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlertTrail",
    version="1.0.0",
    description="AlertTrail API: Dashboard, Log Scanner (PDF) y Mail Scanner",
)

# CORS amplio para pruebas/testers (ajusta si necesitás restringir)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# Directorios: reports (PDFs), static (css/js/img) y templates (Jinja2)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

REPORTS_DIR = os.getenv("REPORTS_DIR", os.path.join(ROOT_DIR, "reports"))
os.makedirs(REPORTS_DIR, exist_ok=True)

STATIC_DIR = os.path.join(ROOT_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Montajes
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# Rutas de UI (landing y dashboard)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root(request: Request):
    """
    Landing mínima con links útiles.
    """
    # Si no existe index.html, devolvemos un HTML simple para evitar 404.
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        return templates.TemplateResponse("index.html", {"request": request})
    html = """
    <!doctype html><html><head><meta charset="utf-8"><title>AlertTrail</title>
    <link rel="stylesheet" href="/static/style.css"></head><body>
    <h1>AlertTrail</h1>
    <ul>
      <li><a href="/dashboard">Ir al Dashboard</a></li>
      <li><a href="/docs">API Docs (Swagger)</a></li>
      <li><a href="/health">Health</a></li>
    </ul>
    </body></html>
    """
    return HTMLResponse(html)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    """
    Dashboard con accesos a Log Scanner y Mail Scanner.
    """
    # Datos dummy; cuando tengas auth real, reemplazalo por el user actual.
    user = {"name": "Invitado"}
    dash_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    if os.path.exists(dash_path):
        return templates.TemplateResponse(
            "dashboard.html", {"request": request, "user": user}
        )
    # Fallback si falta el template
    html = """
    <!doctype html><html><head><meta charset="utf-8"><title>Dashboard - AlertTrail</title>
    <link rel="stylesheet" href="/static/style.css"></head><body>
    <header>
      <h1>Dashboard</h1>
      <p>Usuario: Invitado</p>
      <nav><a href="/">Inicio</a> | <a href="/docs">API Docs</a></nav>
    </header>
    <section>
      <h2>Log Scanner</h2>
      <a class="btn" href="/analysis/generate_pdf" target="_blank">Generar PDF</a>
      <p>Los reportes quedan en <code>/reports</code>.</p>
    </section>
    <section>
      <h2>Mail Scanner</h2>
      <a class="btn" href="/mail/scan" target="_blank">Escanear Mail</a>
    </section>
    </body></html>
    """
    return HTMLResponse(html)


# ──────────────────────────────────────────────────────────────────────────────
# Healthcheck
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health():
    return JSONResponse({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Inclusión de routers si existen (no rompe si aún no están creados)
# ──────────────────────────────────────────────────────────────────────────────
def _try_include_router(import_path: str, attr: str = "router", prefix: str | None = None, tags: list[str] | None = None):
    """
    Incluye un router si el módulo existe; ignora si no.
    """
    try:
        module = __import__(import_path, fromlist=[attr])
        router = getattr(module, attr, None)
        if router is not None:
            app.include_router(router, prefix=prefix or "", tags=tags or [])
    except Exception:
        # Silencioso para que no falle el arranque si falta algún router.
        pass


# Estructura esperada: app/routers/auth.py, analysis.py, mail.py, etc.
_try_include_router("app.routers.auth", prefix="/auth", tags=["auth"])
_try_include_router("app.routers.analysis", prefix="/analysis", tags=["analysis"])
_try_include_router("app.routers.mail", prefix="/mail", tags=["mail"])
_try_include_router("app.routers.admin", prefix="/admin", tags=["admin"])
_try_include_router("app.routers.profile", prefix="/profile", tags=["profile"])
_try_include_router("app.routers.settings", prefix="/settings", tags=["settings"])


# ──────────────────────────────────────────────────────────────────────────────
# Redirección cómoda /api → /docs (opcional)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api", include_in_schema=False)
def api_root():
    return RedirectResponse("/docs")
