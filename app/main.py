import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

APP_NAME = "AlertTrail"
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistencia para PDFs en Render
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# Home amigable (evita {"detail":"Not Found"} en la raíz)
@app.get("/", include_in_schema=False)
def home():
    html = """
    <html>
      <head><meta charset="utf-8"><title>AlertTrail</title></head>
      <body style="font-family:system-ui;margin:40px;">
        <h1>AlertTrail</h1>
        <p>Servicio en línea ✅</p>
        <ul>
          <li><a href="/dashboard">Ir al Dashboard</a></li>
          <li><a href="/docs">Abrir Swagger (API docs)</a></li>
          <li><a href="/health">Healthcheck</a></li>
        </ul>
      </body>
    </html>
    """
    return HTMLResponse(html)

# Healthcheck para Render
@app.get("/health")
def health():
    return {"status": "ok"}

# Routers
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
