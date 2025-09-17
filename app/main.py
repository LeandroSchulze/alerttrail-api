from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from jinja2 import TemplateNotFound
from datetime import datetime
from pathlib import Path
from importlib import import_module

from app.database import SessionLocal
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    get_password_hash,
    verify_password,
)
from app.models import User

app = FastAPI(title="AlertTrail API", version="1.0.0")

# --- Auto-detect de rutas para static/templates ---
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- DB dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- OpenAPI: Swagger usa cookieAuth automáticamente ---
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="API de AlertTrail",
        routes=app.routes,
    )
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

# --- Helpers compat SA 1.x / 2.x ---
def db_get(db: Session, model, pk):
    try:
        return db.get(model, pk)           # SQLAlchemy 2.x
    except Exception:
        return db.query(model).get(pk)     # SQLAlchemy 1.x

def truthy(v):
    if isinstance(v, bool): return v
    if isinstance(v, int):  return v == 1
    if isinstance(v, str):  return v.strip().lower() in {"1","true","yes","y","on"}
    return False

# ---------- Rutas públicas ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_cookie)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_action(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    issue_access_cookie(response, {"sub": str(user.id)})
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
def register_action(
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == email.lower()).first():
        raise HTTPException(status_code=400, detail="Ese email ya está registrado")
    user = User(
        name=(name or "").strip() or "Usuario",
        email=email.lower(),
        hashed_password=get_password_hash(password),
        role="user",
        plan="FREE",
        created_at=datetime.utcnow(),
    )
    db.add(user); db.commit(); db.refresh(user)
    issue_access_cookie(response, {"sub": str(user.id)})
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
def logout(_response: Response):
    r = RedirectResponse(url="/")
    r.delete_cookie("access_token")
    return r

# ---------- Dashboard protegido ----------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    if not current:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user = db_get(db, User, current.id)
    if not user:
        r = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        r.delete_cookie("access_token")
        return r

    # Detección robusta de admin
    role = (getattr(user, "role", "") or "").lower()
    is_admin = (role == "admin") or truthy(getattr(user, "is_admin", False)) or truthy(getattr(user, "is_superuser", False))

    try:
        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "current_user": user, "is_admin": is_admin},
        )
    except TemplateNotFound:
        html = f"""
        <!doctype html><meta charset='utf-8'>
        <title>AlertTrail — Dashboard</title>
        <div style="font-family:system-ui;padding:24px">
          <h1>Dashboard (fallback)</h1>
          <p>Hola <b>{user.name}</b> ({user.email})</p>
          <p>No se encontró <code>{TEMPLATES_DIR}/dashboard.html</code>.</p>
          <p><a href="/logout">Salir</a></p>
        </div>"""
        return HTMLResponse(html)

# ---------- Incluir routers reales (SIN prefijo extra) ----------
def include_router_if_exists(module_path: str, tag: str) -> bool:
    try:
        mod = import_module(module_path)
        router = getattr(mod, "router", None)
        if router:
            # OJO: sin prefix aquí. Respetamos el prefix que el router ya tenga.
            app.include_router(router, tags=[tag])
            return True
    except Exception:
        pass
    return False

analysis_included = any([
    include_router_if_exists("app.routers.analysis", "Analysis"),
    include_router_if_exists("app.routers.reports",  "Analysis"),
    include_router_if_exists("app.routers.report",   "Analysis"),
    include_router_if_exists("app.routers.pdf",      "Analysis"),
])

mail_included = any([
    include_router_if_exists("app.routers.mail",         "Mail"),
    include_router_if_exists("app.routers.email",        "Mail"),
    include_router_if_exists("app.routers.mail_scanner", "Mail"),
])

include_router_if_exists("app.routers.admin", "Admin")

# ---------- Aliases si quedó doble prefijo (p.ej. /analysis/analysis/...) ----------
def route_exists(path: str) -> bool:
    for r in app.routes:
        if getattr(r, "path", None) == path:
            return True
    return False

def add_alias(expected: str, actual: str):
    if route_exists(actual) and not route_exists(expected):
        async def _redir():
            return RedirectResponse(url=actual, status_code=307)
        # Aceptamos GET/POST por si tu endpoint original usa POST
        app.add_api_route(expected, _redir, methods=["GET", "POST"])

# Posibles combinaciones que suelen quedar
add_alias("/analysis/generate_pdf", "/analysis/analysis/generate_pdf")
add_alias("/mail/connect",          "/mail/mail/connect")
add_alias("/mail/scan",             "/mail/mail/scan")

# ---------- Placeholders si faltan routers en este build ----------
if not (route_exists("/analysis/generate_pdf") or route_exists("/analysis/analysis/generate_pdf")):
    @app.get("/analysis/generate_pdf")
    def _analysis_placeholder():
        return JSONResponse({"detail": "Ruta /analysis/generate_pdf no está instalada en este build."}, status_code=501)

if not (route_exists("/mail/connect") or route_exists("/mail/mail/connect")):
    @app.get("/mail/connect")
    def _mail_connect_placeholder():
        return JSONResponse({"detail": "Ruta /mail/connect no está instalada en este build."}, status_code=501)

if not (route_exists("/mail/scan") or route_exists("/mail/mail/scan")):
    @app.get("/mail/scan")
    def _mail_scan_placeholder():
        return JSONResponse({"detail": "Ruta /mail/scan no está instalada en este build."}, status_code=501)
