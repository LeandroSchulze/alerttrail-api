# app/routers/billing_ui.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/billing/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    # Traemos el usuario completo desde la DB
    u: User | None = db.query(User).filter(User.id == user["sub"]).first()

    # Normalizamos plan (extiende trial/expiraciones, etc.)
    try:
        from app.security.billing_guard import normalize_user_plan
        if u:
            normalize_user_plan(db, u)
            db.refresh(u)
    except Exception:
        pass

    # Plan “efectivo”: si es admin o is_pro, tratamos como PRO para visualización
    raw_plan = ((u.plan if u else None) or "FREE").upper()
    is_admin = bool(getattr(u, "is_admin", False) or getattr(u, "is_superuser", False))
    is_pro   = bool(getattr(u, "is_pro", False))
    effective_plan = "PRO" if (is_admin or is_pro) else raw_plan

    ctx = {
        "request": request,
        "user": u,
        "is_admin": is_admin,
        "is_pro": is_pro,
        "plan": effective_plan,   # <- usar este en el template
        "raw_plan": raw_plan,     # opcional, por si querés mostrar el plan real de DB
        # precios
        "price_month": 10.00,
        "price_year": 96.00,
        "biz_included": 25,
        "biz_extra": 3.00,
    }
    return request.app.state.templates.TemplateResponse("billing_subscriptions.html", ctx)
