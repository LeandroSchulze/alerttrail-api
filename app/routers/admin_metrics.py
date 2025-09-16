# app/routers/admin_metrics.py
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.security import get_current_user_cookie

# Estos modelos los definimos en otros routers:
# - ReportDownload en analysis.py
# - MailAlert en mail.py
try:
    from app.routers.analysis import ReportDownload
except Exception:
    ReportDownload = None  # type: ignore
try:
    from app.routers.mail import MailAlert
except Exception:
    MailAlert = None  # type: ignore

router = APIRouter(prefix="/admin", tags=["admin"])

FREE_EMAIL_DOMAINS = {
    "gmail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
    "yahoo.com.ar", "icloud.com", "proton.me", "protonmail.com", "gmx.com",
    "aol.com", "msn.com", "ymail.com"
}

def _is_business_domain(email: str) -> bool:
    dom = (email or "").split("@")[-1].lower().strip()
    return dom and dom not in FREE_EMAIL_DOMAINS

@router.get("/metrics")
def admin_metrics(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user or not bool(getattr(user, "is_admin", False)):
        raise HTTPException(status_code=403, detail="forbidden")

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    downloads_month = 0
    if ReportDownload is not None:
        downloads_month = (
            db.query(func.count(ReportDownload.id))
            .filter(ReportDownload.created_at >= month_start)
            .scalar()
        ) or 0

    free_users = (
        db.query(func.count(models.User.id))
        .filter(func.lower(models.User.plan) == "free")
        .scalar()
    ) or 0

    pro_users = (
        db.query(func.count(models.User.id))
        .filter(func.lower(models.User.plan) == "pro")
        .scalar()
    ) or 0

    return {
        "period": month_start.strftime("%Y-%m"),
        "downloads_this_month": downloads_month,
        "users_free": free_users,
        "users_pro": pro_users,
    }

@router.get("/metrics/extended")
def admin_metrics_extended(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    user = get_current_user_cookie(request, db)
    if not user or not bool(getattr(user, "is_admin", False)):
        raise HTTPException(status_code=403, detail="forbidden")

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    d14 = now - timedelta(days=14)
    d30 = now - timedelta(days=30)

    # --- users: free / pro / empresas / nuevos del mes
    users: List[models.User] = db.query(models.User).all()
    free_count = sum(1 for u in users if (getattr(u, "plan", "") or "").lower() == "free")
    pro_count  = sum(1 for u in users if (getattr(u, "plan", "") or "").lower() == "pro")
    biz_domains = { (u.email or "").split("@")[-1].lower().strip()
                    for u in users if u.email and _is_business_domain(u.email) }
    companies_count = len(biz_domains)

    if hasattr(models.User, "created_at"):
        new_users_month = db.query(func.count(models.User.id)).filter(
            models.User.created_at >= month_start
        ).scalar() or 0
    else:
        new_users_month = None  # campo no disponible

    # --- descargas: totales mes, por día (14d), top descargadores, activos 30d
    downloads_month = 0
    downloads_by_day: Dict[str, int] = {}
    top_downloaders: List[Dict[str, Any]] = []
    active_users_30d = 0

    if ReportDownload is not None:
        q = db.query(ReportDownload).filter(ReportDownload.created_at >= month_start).all()
        downloads_month = len(q)

        # by day (últimos 14 días)
        q14 = db.query(ReportDownload).filter(ReportDownload.created_at >= d14).all()
        day_counter: Dict[str, int] = defaultdict(int)
        for r in q14:
            day_counter[r.created_at.date().isoformat()] += 1
        # completar días vacíos
        downloads_by_day = {
            (d14 + timedelta(days=i)).date().isoformat(): day_counter.get((d14 + timedelta(days=i)).date().isoformat(), 0)
            for i in range(15)
        }

        # top descargadores
        counter = Counter(r.user_id for r in q if getattr(r, "user_id", None) is not None)
        if counter:
            # mapear ids a email
            uid_to_email = {
                u.id: u.email for u in db.query(models.User)
                .filter(models.User.id.in_(list(counter.keys()))).all()
            }
            top_downloaders = [
                {"user_id": uid, "email": uid_to_email.get(uid, "(desconocido)"), "downloads": cnt}
                for uid, cnt in counter.most_common(5)
            ]

        # usuarios activos en 30 días: distintos user_id en descargas
        q30 = db.query(ReportDownload).filter(ReportDownload.created_at >= d30).all()
        active_users_30d = len({r.user_id for r in q30 if r.user_id})

    # --- alertas de correo (mes y desglose por motivo)
    alerts_month = 0
    alerts_unread = 0
    alert_reasons: Dict[str, int] = {}
    if MailAlert is not None:
        malerts = db.query(MailAlert).filter(MailAlert.created_at >= month_start).all()
        alerts_month = len(malerts)
        alerts_unread = sum(1 for a in malerts if not getattr(a, "is_read", False))
        for a in malerts:
            reason = (a.reason or "").strip()
            if not reason:
                continue
            for part in [p.strip() for p in reason.split(";") if p.strip()]:
                alert_reasons[part] = alert_reasons.get(part, 0) + 1

    return {
        "period": month_start.strftime("%Y-%m"),
        "users": {
            "free": free_count,
            "pro": pro_count,
            "companies_count": companies_count,
            "new_this_month": new_users_month,
        },
        "downloads": {
            "this_month": downloads_month,
            "by_day_14d": downloads_by_day,
            "top_downloaders": top_downloaders,
            "active_users_30d": active_users_30d,
        },
        "mail_alerts": {
            "this_month": alerts_month,
            "unread": alerts_unread,
            "reasons": alert_reasons,
        },
    }
