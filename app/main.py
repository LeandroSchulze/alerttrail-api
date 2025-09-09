from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os

from app.database import Base, engine
from app.routers import auth, analysis, profile, admin

app = FastAPI(title="AlertTrail")

Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

reports_dir = os.getenv("REPORTS_DIR", "/var/data/reports")
try:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
except Exception:
    reports_dir = "/tmp/reports"
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(profile.router)
app.include_router(admin.router)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "ok"}

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
