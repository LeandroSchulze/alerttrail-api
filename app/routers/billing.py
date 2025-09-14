import os
import datetime as dt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Organization
from app.security import get_current_user_id

router = APIRouter(prefix="/billing", tags=["billing"])

# templates fallback: app/templates o /templates
import os as _os
_BASE = _os.path.dirname(_os.path.dirname(__file__))
_ROOT = _os.path.dirname(_BASE)
_TPL = _os.path.join(_BASE, "templates")
if not _os.path.isdir(_TPL):
    _TPL = _os.path.join(_ROOT, "templates")
templates = Jinja2Templates(directory=_TPL)

def _now():
    return dt.datetime.utcnow()

def _pricing_pro():
    month = float(os.getenv("PRO_PRICE_MONTH_USD", "10"))
    disc_pct = float(os.getenv("PRO_ANNUAL_DISCOUNT_PCT", "10"))
    year = round(month * 12 * (1 - disc_pct/100))
    return month, disc_pct, int(year)

def _pricing_biz():
    price = float(os.getenv("BIZ_PRICE_MONTH_USD", "99"))
    included = int(os.getenv("BIZ_INCLUDED_SEATS", "25"))
    extra = float(os.getenv("BIZ_EXTRA_SEAT_USD", "3"))
    disc_pct = float(os.getenv("PRO_ANNUAL_DISCOUNT_PCT", "10"))
    year = round(price * 12 * (1 - disc_pct/100))
    return price, included, extra, disc_pct, int(year)

@router.get("", response_class=HTMLResponse)
async def billing_home(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.query(User).get(user_id)
    is_pro = user.plan in ("PRO", "BUSINESS") and (user.plan_expires is None or user.plan_expires > _now())
    days_left = None
    if user.plan_expires:
        days_left = max(0, (user.plan_expires - _now()).days)

    price_month, disc_pct, price_year = _pricing_pro()
    biz_price, biz_included, biz_extra, biz_disc, biz_year = _pricing_biz()

    ctx = {
        "request": request,
        "user": user,
        "is_pro": is_pro,
        "days_left": days_left,
        "price_month": price_month,
        "disc_pct": disc_pct,
        "price_year": price_year,
        "biz_price": biz_price,
        "biz_included": biz_included,
        "biz_extra": biz_extra,
        "biz_disc": biz_disc,
        "biz_year": biz_year,
    }
    return templates.TemplateResponse("billing.html", ctx)

@router.post("/upgrade_pro")
async def upgrade_pro(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    coupon: str = Form(default=""),
):
    user = db.query(User).get(user_id)

    default_days = int(os.getenv("MANUAL_PRO_DAYS", "30"))
    coupon_code = os.getenv("COUPON_CODE", "")
    coupon_days = int(os.getenv("COUPON_DAYS", "60"))
    add_days = coupon_days if (coupon and coupon == coupon_code and coupon_code) else default_days

    base = user.plan_expires if (user.plan in ("PRO","BUSINESS") and user.plan_expires and user.plan_expires > _now()) else _now()
    user.plan = "PRO"
    user.plan_expires = base + dt.timedelta(days=add_days)
    db.commit()
    return RedirectResponse("/billing", status_code=302)

@router.post("/upgrade_business")
async def upgrade_business(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.query(User).get(user_id)
    add_days = int(os.getenv("MANUAL_BUSINESS_DAYS", "30"))
    base = user.plan_expires if (user.plan in ("PRO","BUSINESS") and user.plan_expires and user.plan_expires > _now()) else _now()

    # 1) Activar plan en el usuario (para gating inmediato)
    user.plan = "BUSINESS"
    user.plan_expires = base + dt.timedelta(days=add_days)

    # 2) Crear/actualizar una Organization del usuario (owner)
    biz_price = float(os.getenv("BIZ_PRICE_MONTH_USD", "99"))
    included = int(os.getenv("BIZ_INCLUDED_SEATS", "25"))
    extra = int(os.getenv("BIZ_EXTRA_SEAT_USD", "3"))

    org = db.query(Organization).filter(Organization.owner_user_id == user.id).first()
    if not org:
        # nombre simple: dominio del email si existe, si no, nombre del usuario
        name = (user.email.split("@")[1] if "@" in user.email else f"Org de {user.name}")
        org = Organization(
            name=name,
            owner_user_id=user.id,
            plan="BUSINESS",
            seats_included=included,
            extra_seat_usd=extra,
            plan_expires=user.plan_expires,
        )
        db.add(org)
    else:
        org.plan = "BUSINESS"
        org.seats_included = included
        org.extra_seat_usd = extra
        org.plan_expires = user.plan_expires

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
