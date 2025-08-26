import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse  # <- agrega este import
from .database import Base, engine
from .routers import auth, dashboard, analysis, profile, settings, admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AlertTrail")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# static & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.state.templates = templates

# routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(analysis.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(admin.router)

# ⬇️ PONER ESTA RUTA DESPUÉS DE LO ANTERIOR (ya existe app.state.templates)
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return app.state.templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "ok"}