from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from datetime import datetime
import os

# ==== Importa tu stack existente ====
# Ajustá estos imports a tu proyecto real
from app.database import SessionLocal, engine
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    get_password_hash,
    verify_password,
)
from app.models import User  # Debe tener: id, name, email, hashed_password, role, plan, created_at
# Routers existentes (si los tenés)
try:
    from app.routers import admin as admin_router  # el que te paso más abajo
except Exception:
    admin_router = None

app = FastAPI(title="AlertTrail API", version="1.0.0")

# Static & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ===== DB dependency =====
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===== OpenAPI: usar cookieAuth automáticamente en Swagger =====
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description="API de AlertTrail",
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    components["cookieAuth"] = {"type": "apiKey", "in": "cookie", "name": "access_token"}
    # aplica cookieAuth por defecto
    for path in openapi_schema.get("paths", {}).values():
        for method in path.values():
            if isinstance(method, dict):
                method.setdefault("security", [{"cookieAuth": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ====== Rutas públicas (sin necesidad de admin) ======

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_cookie)):
    # Si está logueado, lo llevo al dashboard; si no, landing simple con links
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    # emitir cookie JWT HTTPOnly
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
    # Evitar duplicados
    exists = db.query(User).filter(User.email == email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Ese email ya está registrado")
    user = User(
        name=name.strip() or "Usuario",
        email=email.lower(),
        hashed_password=get_password_hash(password),
        role="user",
        plan="FREE",
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    issue_access_cookie(response, {"sub": str(user.id)})
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
def logout(response: Response):
    # Invalida la cookie eliminándola
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token")
    return response

# ====== Dashboard protegido por cookie ======
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    if not current:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Datos básicos del usuario para la vista
    user = db.query(User).get(current.id)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": user,
        },
    )

# ====== Incluye router de Admin (stats) ======
if admin_router:
    app.include_router(admin_router.router, prefix="/admin", tags=["Admin"])
