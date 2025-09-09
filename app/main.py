import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

APP_NAME = "AlertTrail"
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")

# --- App base ---
app = FastAPI(title=APP_NAME)

# CORS abierto (ajústalo si necesitás restringir orígenes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dirs persistentes (Render) ---
os.makedirs(REPORTS_DIR, exist_ok=True)

# Servir PDFs generados de forma pública
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# --- Routers (incluye sólo los que existan) ---
try:
    from app.routers import analysis
    app.include_router(analysis.router)
except Exception:
    pass

try:
    from app.routers import auth
    app.include_router(auth.router)
except Exception:
    pass

try:
    from app.routers import profile
    app.include_router(profile.router)
except Exception:
    pass

try:
    from app.routers import admin
    app.include_router(admin.router)
except Exception:
    pass

try:
    from app.routers import settings
    app.include_router(settings.router)
except Exception:
    pass

# --- Healthcheck para Render ---
@app.get("/health")
def health():
    return {"status": "ok"}
