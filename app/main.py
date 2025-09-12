# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
import os

from app.database import SessionLocal
from app.models import User
from app.utils.security import decode_token

app = FastAPI(
    title="AlertTrail",
    version="1.0.0",
    description="AlertTrail API: Dashboard, Log Scanner (PDF) y Mail Scanner",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

REPORTS_DIR = os.getenv("REPORTS_DIR", os.path.join(ROOT_DIR, "reports"))
os.makedirs(REPORTS_DIR, exist_ok=True)
STATIC_DIR = os.path.join(ROOT_DIR, "static"); os.makedirs(STATIC_DIR, exist_ok=True)
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates"); os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def _current_user_from_cookie(request: Request):
    token = request.cookies.get("access_token")
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

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root(request: Request):
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
    </ul></body></html>
    """
    return HTMLResponse(html)

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    user = _current_user_from_cookie(request)
    ctx_user = {"name": user.name} if user else {"name": "Invitado"}
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": ctx_user})

@app.get("/api", include_in_schema=False)
def api_root():
    return RedirectResponse("/docs")

@app.get("/health", tags=["health"])
def health():
    return JSONResponse({"status": "ok"})

# ─── Inclusión de routers ─────────────────────────────────────────────────────
def _try_include_router(import_path: str, attr: str = "router", prefix: str | None = None, tags: list[str] | None = None):
    try:
        module = __import__(import_path, fromlist=[attr])
        router = getattr(module, attr, None)
        if router is not None:
            app.include_router(router, prefix=prefix or "", tags=tags or [])
    except Exception:
        pass

_try_include_router("app.routers.auth",     prefix="/auth",     tags=["auth"])
_try_include_router("app.routers.analysis", prefix="/analysis", tags=["analysis"])
_try_include_router("app.routers.mail",     prefix="/mail",     tags=["mail"])
_try_include_router("app.routers.admin",    prefix="/admin",    tags=["admin"])
