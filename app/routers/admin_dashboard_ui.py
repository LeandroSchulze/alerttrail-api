# app/routers/admin_dashboard_ui.py

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie
from app.ui import templates

router = APIRouter(prefix="/admin", tags=["admin-dashboard-ui"])


def _require_super_admin(user: User):
    if not user or user.email != "admin@alerttrail.com":
        raise HTTPException(status_code=403)


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    _require_super_admin(user)

    # Lógica simple inline (no dependencia circular)
    total = db.query(User).count()
    free = db.query(User).filter(User.plan == "FREE").count()
    pro = db.query(User).filter(User.plan == "PRO").count()
    biz = db.query(User).filter(User.plan == "BIZ").count()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "current_user": user,
            "stats": {
                "total": total,
                "free": free,
                "pro": pro,
                "biz": biz,
            },
        },
    )
