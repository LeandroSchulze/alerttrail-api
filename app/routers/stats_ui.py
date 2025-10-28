# app/routers/stats_ui.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/stats", tags=["stats"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_class=HTMLResponse)
def stats_page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    # métricas simples (podés ajustar a tus tablas reales)
    total_users = db.query(func.count(User.id)).scalar() or 0
    plan_free  = db.query(func.count(User.id)).filter(func.lower(User.plan) == "free").scalar() or 0
    plan_pro   = db.query(func.count(User.id)).filter(func.lower(User.plan) == "pro").scalar() or 0
    plan_biz   = db.query(func.count(User.id)).filter(func.lower(User.plan).in_(("biz","business","empresas","empresa"))).scalar() or 0

    # placeholder de “descargas del mes” (si tenés tabla de reportes, reemplazá por count real)
    downloads_this_month = 0

    ctx = {
        "request": request,
        "page_title": "Estadísticas",
        "kpis": {
            "total_users": total_users,
            "free": plan_free, "pro": plan_pro, "biz": plan_biz,
            "downloads_month": downloads_this_month,
        }
    }
    return request.app.state.templates.TemplateResponse("stats.html", ctx)
