# app/routers/admin_dashboard.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


def _require_super_admin(user: User):
    if not user or user.email != "admin@alerttrail.com":
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/stats")
def admin_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    _require_super_admin(user)

    now = datetime.utcnow()
    last_24h = now - timedelta(days=1)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    total = db.query(User).count()

    free = db.query(User).filter(User.plan == "FREE").count()
    pro = db.query(User).filter(User.plan == "PRO").count()
    biz = db.query(User).filter(User.plan == "BIZ").count()

    new_24h = db.query(User).filter(User.created_at >= last_24h).count()
    new_7d = db.query(User).filter(User.created_at >= last_7d).count()
    new_30d = db.query(User).filter(User.created_at >= last_30d).count()

    return {
        "total_users": total,
        "by_plan": {
            "FREE": free,
            "PRO": pro,
            "BIZ": biz,
        },
        "new_users": {
            "24h": new_24h,
            "7d": new_7d,
            "30d": new_30d,
        },
    }
