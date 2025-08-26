import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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

# include routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(analysis.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(admin.router)

@app.get("/health")
def health():
    return {"status": "ok"}

# simple login page (token flow instructions)
@app.get("/login")
def login_page():
    return {
        "info": "Usa /auth/login con form-data (username=email, password) para obtener access_token. Luego, usa el token como 'Authorization: Bearer <token>' y visita '/'"
    }
