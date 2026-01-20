from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User
from app.ui import templates
from app.security import get_current_user_cookie_optional

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: dict | None):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    if user.get("email") != "admin@alerttrail.com":
        raise HTTPException(status_code=403, detail="Solo admin")


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie_optional),
):
    require_admin(user)

    total_users = db.query(User).count()

    now = datetime.utcnow()
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    new_users_month = (
        db.query(User)
        .filter(User.created_at >= start_month)
        .count()
    )

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "current_user": user,
            "total_users": total_users,
            "new_users_month": new_users_month,
            "month": start_month.strftime("%B %Y"),
        },
    )
