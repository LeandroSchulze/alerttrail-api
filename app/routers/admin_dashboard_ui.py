# app/routers/admin_dashboard_ui.py
from __future__ import annotations

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.ui import templates
from app.security import get_current_user_cookie_optional
from app.database import get_db
from sqlalchemy.orm import Session
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin-ui"])


# -------------------------------------------------
# Seguridad: solo super admin
# -------------------------------------------------
def _require_super_admin(user_dict: dict | None):
    if not user_dict:
        raise HTTPException(status_code=401, detail="No autenticado")

    email = user_dict.get("email")
    if email != "admin@alerttrail.com":
        raise HTTPException(status_code=403, detail="Acceso restringido")


# -------------------------------------------------
# Admin dashboard
# -------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie_optional),
):
    _require_super_admin(user)

    # métricas básicas (ejemplo, no rompe nada)
    total_users = db.query(User).count()
    free_users = db.query(User).filter(User.plan == "FREE").count()
    pro_users = db.query(User).filter(User.plan == "PRO").count()
    biz_users = db.query(User).filter(User.plan == "BIZ").count()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "current_user": user,
            "metrics": {
                "total": total_users,
                "free": free_users,
                "pro": pro_users,
                "biz": biz_users,
            },
        },
    )
