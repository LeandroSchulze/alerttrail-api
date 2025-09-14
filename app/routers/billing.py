import os
import datetime as dt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_id

router = APIRouter(prefix="/billing", tags=["billing"])

# templates: funciona si están en app/templates o en /templates (fallback)
import os as _os
_BASE = _os.path.dirname(_os.path.dirname(__file__))
_ROOT = _os.path.dirname(_BASE)
_TPL = _os.path.join(_BASE, "templates")
if not _os.path.isdir(_TPL):
    _TPL = _os.path.join(_ROOT, "templates")
templates = Jinja2Templates(directory=_TPL)

def _now():
    return dt.datetime.utcnow()

@router.get("", response_class=HTMLResponse)
async def billing_home(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.query(User).get(user_id)
    is_pro = user.plan == "PRO" and (user.plan_expires is None or user.plan_expires > _now())
    days_left = None
    if user.plan_expires:
        days_left = max(0, (user.plan_expires - _now()).days)
    return templates.TemplateResponse(
        "billing.html",
        {"request": request, "user": user, "is_pro": is_pro, "days_left": days_left},
    )

@router.post("/upgrade")
async def upgrade_plan(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    coupon: str = Form(default=""),
):
    user = db.query(User).get(user_id)

    # Modo manual: activamos PRO por N días (o por cupón)
    default_days = int(os.getenv("MANUAL_PRO_DAYS", "30"))
    coupon_code = os.getenv("COUPON_CODE", "")
    coupon_days = int(os.getenv("COUPON_DAYS", "60"))

    add_days = coupon_days if coupon and coupon == coupon_code and coupon_code else default_days

    base = user.plan_expires if (user.plan == "PRO" and user.plan_expires and user.plan_expires > _now()) else _now()
    user.plan = "PRO"
    user.plan_expires = base + dt.timedelta(days=add_days)
    db.commit()
    return RedirectResponse("/billing", status_code=302)

@router.post("/cancel")
async def cancel_plan(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.query(User).get(user_id)
    trial_days = int(os.getenv("TRIAL_DAYS", "5"))
    user.plan = "FREE"
    user.plan_expires = _now() + dt.timedelta(days=trial_days)
    db.commit()
    return RedirectResponse("/billing", status_code=302)
