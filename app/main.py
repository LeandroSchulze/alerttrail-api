from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from jinja2 import TemplateNotFound
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    get_password_hash,
    verify_password,
)
from app.models import User

app = FastAPI(title="AlertTrail API", version="1.0.0")

# === Static & Templates ===
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
STATIC_DIR    = "app/static"    if Path("app/static").exists()    else "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# === DB dep ===
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# === OpenAPI con cookie ===
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

# === Helpers ===
def db_get(db: Session, model, pk):
    try:
        return db.get(model, pk)           # SA 2.x
    except Exception:
        return db.query(model).get(pk)     # SA 1.x

def truthy(v):
    if isinstance(v, bool): return v
    if isinstance(v, int):  return v == 1
    if isinstance(v, str):  return v.strip().lower() in {"1","true","yes","y","on"}
    return False

# === Rutas públicas ===
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_cookie)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("landing.html", {"request": request})

# Alias clásico: que /login apunte al login visual (si preferís usar /auth/login)
@app.get("/login", response_class=HTMLResponse)
def login_alias():
    return RedirectResponse(url="/auth/login", status_code=302)

# Post de /login (por compatibilidad con tu front antiguo)
@app.post("/login")
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not verify_password(password, getattr(user, "hashed_password", "") or getattr(user, "password_hash", "")):
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

# === Dashboard protegido ===
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    if not current:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    user = db_get(db, User, current.id)
    if not user:
        r = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        r.delete_cookie("access_token")
        return r

    role = (getattr(user, "role", "") or "").lower()
    is_admin = (role == "admin") or truthy(getattr(user, "is_admin", False)) or truthy(getattr(user, "is_superuser", False))

    try:
        return templates.TemplateResponse("dashboard.html", {"request": request, "current_user": user, "is_admin": is_admin})
    except TemplateNotFound:
        html = f"""<!doctype html><meta charset='utf-8'><div style="font-family:system-ui;padding:24px">
          <h1>Dashboard (fallback)</h1><p>Hola <b>{user.name}</b> ({user.email})</p>
          <p>Falta <code>{TEMPLATES_DIR}/dashboard.html</code>.</p>
          <p><a href="/logout">Salir</a></p></div>"""
        return HTMLResponse(html)

# === Routers ===
try:
    from app.routers import auth as auth_router_mod
    app.include_router(auth_router_mod.router)          # <- FALTABA
except Exception as e:
    print("No pude cargar app.routers.auth:", e)

try:
    from app.routers import analysis as analysis_router_mod
    app.include_router(analysis_router_mod.router)
except Exception as e:
    print("No pude cargar app.routers.analysis:", e)

try:
    from app.routers import mail as mail_router_mod
    app.include_router(mail_router_mod.router)
except Exception as e:
    print("No pude cargar app.routers.mail:", e)

try:
    from app.routers import admin as admin_router_mod
    app.include_router(admin_router_mod.router)
except Exception as e:
    print("No pude cargar app.routers.admin:", e)

# === Alias amigables ===
def _exists(p: str) -> bool:
    return any(isinstance(r, APIRoute) and r.path == p for r in app.routes)

if _exists("/analysis/generate-pdf") and not _exists("/analysis/generate_pdf"):
    @app.get("/analysis/generate_pdf")
    def _alias_gen_pdf():
        return RedirectResponse(url="/analysis/generate-pdf", status_code=307)

if _exists("/stats") and not _exists("/admin/stats"):
    @app.get("/admin/stats")
    def _alias_admin_stats():
        return RedirectResponse(url="/stats", status_code=307)

if _exists("/mail/scanner") and not _exists("/mail/scan"):
    @app.get("/mail/scan")
    def _alias_mail_scan():
        return RedirectResponse(url="/mail/scanner", status_code=307)
if _exists("/mail/scan") and not _exists("/mail/scanner"):
    @app.get("/mail/scanner")
    def _alias_mail_scanner():
        return RedirectResponse(url="/mail/scan", status_code=307)

# === Handler global: 401/403 en navegador -> login
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if exc.status_code in (401, 403):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/auth/login", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# === Log de rutas ===
@app.on_event("startup")
def _log_routes():
    paths = sorted([r.path for r in app.routes if isinstance(r, APIRoute)])
    print("\n=== ROUTES ===")
    for p in paths:
        print(p)
    print("==============\n")
