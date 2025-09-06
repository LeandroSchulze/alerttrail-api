from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pathlib import Path
import os

from app.database import Base, engine
from app.security import get_current_user
from app import models
from app.routers import (
    auth,
    analysis,
    history,
    profile,
    settings as settings_router,
    admin,
)

app = FastAPI(title="AlertTrail")

# --- Static assets (/static) ---
Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Reports (PDFs) en carpeta escribible ---
# Usa REPORTS_DIR si está definida; intenta /var/data/reports; si falla, /tmp/reports
reports_dir = os.getenv("REPORTS_DIR", "/var/data/reports")
try:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
except Exception:
    reports_dir = "/tmp/reports"
    Path(reports_dir).mkdir(parents=True, exist_ok=True)

# Sirve los PDFs en /reports/...
app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

# --- Templates ---
templates = Jinja2Templates(directory="app/templates")

# --- Routers (API) ---
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(history.router)
app.include_router(profile.router)
app.include_router(settings_router.router)
app.include_router(admin.router)

# --- Pages ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: models.User = Depends(get_current_user),
):
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})

# --- Healthcheck ---
@app.get("/health")
def health():
    return {"status": "ok"}

# --- Crear tablas al iniciar (útil en local/primera vez) ---
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
