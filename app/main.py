from fastapi import FastAPI, Request, Depends, status, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from datetime import datetime
from jinja2 import TemplateNotFound

from app.database import SessionLocal
from app.security import (
    issue_access_cookie,
    get_current_user_cookie,
    get_password_hash,
    verify_password,
)
from app.models import User

app = FastAPI(title="AlertTrail API", version="1.0.0")

# static & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
# DB dep
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# OpenAPI con cookieAuth (Swagger usa tu cookie de sesión)
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

# Helpers compat SA 1.x/2.x
def db_get(db: Session, model, pk):
    try:
        return db.get(model, pk)           # SA 2.x
    except Exception:
        return db.query(model).get(pk)     # SA 1.x

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
def login_action(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
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
        name=name.strip() or "Usuario",
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

    try:
        return templates.TemplateResponse("dashboard.html", {"request": request, "current_user": user})
    except TemplateNotFound:
        # Fallback para que no rompa si falta el template en el deploy
        html = f"""
        <!doctype html><meta charset="utf-8">
        <title>AlertTrail — Dashboard</title>
        <div style="font-family:system-ui;padding:24px">
          <h1>Dashboard (fallback)</h1>
          <p>Hola <b>{user.name}</b> ({user.email})</p>
          <p>No se encontró <code>templates/dashboard.html</code>. Subí ese archivo
             o verifica la ruta y el nombre de la carpeta <code>templates/</code> (sensible a mayúsculas).</p>
          <p><a href="/logout">Salir</a></p>
        </div>
        """
        return HTMLResponse(html)

# ---------- Router Admin ----------
try:
    from app.routers import admin as admin_router
    app.include_router(admin_router.router, prefix="/admin", tags=["Admin"])
except Exception:
    pass
