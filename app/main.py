import os
import datetime as dt
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db, Base, get_engine
from app.models import User, Setting
from app.security import (
    get_password_hash,
    verify_password,
    issue_access_cookie,
    get_current_user_id,
)
from app.routers import mail as mail_router, billing as billing_router

app = FastAPI(title="AlertTrail")

# --- Paths / dirs (con fallback a raíz del repo) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # .../app
ROOT_DIR = os.path.dirname(BASE_DIR)                    # repo root

def pick_dir(*candidates):
    for d in candidates:
        if os.path.isdir(d):
            return d
    os.makedirs(candidates[0], exist_ok=True)
    return candidates[0]

TEMPLATES_DIR = pick_dir(
    os.path.join(BASE_DIR, "templates"),
    os.path.join(ROOT_DIR, "templates"),
)
STATIC_DIR = pick_dir(
    os.path.join(BASE_DIR, "static"),
    os.path.join(ROOT_DIR, "static"),
)

REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# Static & templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Create tables if missing
Base.metadata.create_all(bind=get_engine())

# --- Middleware: exigir login para vistas HTML ---
PUBLIC_PREFIXES = ("/auth/login", "/auth/register", "/health", "/static", "/staticdownload")

@app.middleware("http")
async def require_login_for_html(request: Request, call_next):
    path = request.url.path
    accept = request.headers.get("accept", "")
    wants_html = "text/html" in accept or "*/*" in accept  # navegadores
    if wants_html and not any(path.startswith(p) for p in PUBLIC_PREFIXES):
        if not request.cookies.get("access_token"):
            return RedirectResponse("/auth/login")
    return await call_next(request)

# --- 401 -> redirección a login en vistas HTML ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/auth/login")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def index():
    return RedirectResponse("/dashboard")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.query(User).get(user_id)
    now = dt.datetime.utcnow()
    is_pro = user.plan == "PRO" and (user.plan_expires is None or user.plan_expires > now)
    trial_left = 0
    if user.plan == "FREE" and user.plan_expires:
        trial_left = max(0, (user.plan_expires - now).days)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "is_pro": is_pro, "trial_left": trial_left},
    )

# ---------- Auth (web) ----------
@app.get("/auth/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/auth/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Credenciales incorrectas")
    resp = RedirectResponse("/dashboard", status_code=302)
    issue_access_cookie(resp, user.id)
    return resp

@app.get("/auth/logout")
async def logout():
    resp = RedirectResponse("/auth/login")
    resp.delete_cookie("access_token")
    return resp

@app.get("/auth/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/auth/register")
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    exists = db.query(User).filter(User.email == email).first()
    if exists:
        raise HTTPException(400, "Email ya registrado")

    trial_days = int(os.getenv("TRIAL_DAYS", "5"))
    plan = "FREE"
    expires = dt.datetime.utcnow() + dt.timedelta(days=trial_days)

    # PROMO: primeras N con PRO por X días
    if os.getenv("PROMO_ENABLED", "false").lower() == "true":
        limit = int(os.getenv("PROMO_LIMIT", "10"))
        promo = db.query(Setting).filter(Setting.key == "promo_used").first()
        used = int(promo.value) if promo else 0
        if used < limit:
            plan = "PRO"
            expires = dt.datetime.utcnow() + dt.timedelta(
                days=int(os.getenv("PROMO_DURATION_DAYS", "60"))
            )
            if promo:
                promo.value = str(used + 1)
            else:
                db.add(Setting(key="promo_used", value="1"))

    user = User(
        name=name,
        email=email,
        password_hash=get_password_hash(password),
        plan=plan,
        plan_expires=expires,
    )
    db.add(user)
    db.commit()

    resp = RedirectResponse("/dashboard", status_code=302)
    issue_access_cookie(resp, user.id)
    return resp

# ---------- Log Scanner (PDF) ----------
@app.post("/analysis/generate_pdf")
async def generate_pdf(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from reportlab.pdfgen import canvas

    fname = f"report_{user_id}_{int(dt.datetime.utcnow().timestamp())}.pdf"
    path = os.path.join(REPORTS_DIR, fname)
    c = canvas.Canvas(path)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 800, "AlertTrail Report")
    c.setFont("Helvetica", 12)
    c.drawString(72, 780, "Estado: OK")
    c.save()

    url = f"/reports/{fname}"
    # API -> JSON; formulario -> HTML
    if "application/json" in request.headers.get("accept", ""):
        return {"url": url}
    return templates.TemplateResponse("pdf_ready.html", {"request": request, "url": url})

@app.get("/reports/{fname}", response_class=HTMLResponse)
async def get_report(fname: str):
    path = os.path.join(REPORTS_DIR, fname)
    if not os.path.exists(path):
        raise HTTPException(404, "No encontrado")
    return HTMLResponse(f"<a href='/staticdownload?f={fname}'>Descargar {fname}</a>")

@app.get("/staticdownload")
async def staticdownload(f: str):
    return FileResponse(
        os.path.join(REPORTS_DIR, f), media_type="application/pdf", filename=f
    )

# ---------- Routers ----------
app.include_router(mail_router.router)
app.include_router(billing_router.router)
