from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os, datetime as dt

from app.database import get_db
from app.models import User, AllowedIP, ReportDownload
from app.security import get_current_user_id, get_password_hash
from app.guards import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

# templates fallback (app/templates o /templates)
_BASE = os.path.dirname(os.path.dirname(__file__))
_ROOT = os.path.dirname(_BASE)
_TPL = os.path.join(_BASE, "templates")
if not os.path.isdir(_TPL):
    _TPL = os.path.join(_ROOT, "templates")
templates = Jinja2Templates(directory=_TPL)

@router.post("/create_admin")
async def create_admin(email: str, password: str, name: str = "Admin", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.password_hash = get_password_hash(password)
        user.name = name
        user.role = "admin"
    else:
        user = User(email=email, name=name, password_hash=get_password_hash(password), role="admin", plan="PRO")
        db.add(user)
    db.commit()
    return {"status": "ok"}

@router.post("/allow_ip")
async def allow_ip(email: str, ip: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"status": "error", "detail": "Usuario no encontrado"}
    exists = db.query(AllowedIP).filter(AllowedIP.user_id == user.id, AllowedIP.ip == ip).first()
    if not exists:
        db.add(AllowedIP(user_id=user.id, ip=ip, label="admin"))
        db.commit()
    return {"status": "ok"}

@router.get("/stats", response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    _: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = dt.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Descargas del mes
    downloads_month = db.query(ReportDownload).filter(ReportDownload.created_at >= month_start).count()

    # Distribución por plan efectivo (según expiración)
    users = db.query(User).all()
    free = pro = business = 0
    for u in users:
        active = (u.plan_expires is None or u.plan_expires > now)
        if u.plan == "BUSINESS" and active:
            business += 1
        elif u.plan == "PRO" and active:
            pro += 1
        else:
            free += 1

    total_users = len(users)
    ctx = {
        "request": request,
        "downloads_month": downloads_month,
        "free": free,
        "pro": pro,
        "business": business,
        "total_users": total_users,
        "month_label": month_start.strftime("%B %Y"),
    }
    return templates.TemplateResponse("admin_stats.html", ctx)
