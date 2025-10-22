# app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from calendar import monthrange
from pydantic import BaseModel, EmailStr

from app.database import SessionLocal, get_db
from app.security import get_current_user_cookie
from app.models import User

# intenta detectar tu modelo de reportes
ReportModel = None
try:
    from app.models import PDFReport as ReportModel
except Exception:
    try:
        from app.models import Report as ReportModel  # por compatibilidad
    except Exception:
        ReportModel = None

router = APIRouter(prefix="/admin", tags=["admin"])

# ----------------- Helpers -----------------
def require_admin(u: User):
    """
    Acepta distintos indicadores de admin para ser más robusto:
      - role == 'admin' (tu caso actual)
      - is_admin / is_superuser (por si existen en el modelo)
    """
    role = (getattr(u, "role", "") or "").lower()
    is_admin_flag = bool(getattr(u, "is_admin", False)) or bool(getattr(u, "is_superuser", False))
    if not u or (role != "admin" and not is_admin_flag):
        raise HTTPException(status_code=403, detail="Solo admin")

# ----------------- Aliases / Redirecciones -----------------
@router.get("/subscriptions", include_in_schema=False)
def admin_subscriptions_redirect():
    # Si el dashboard apunta a /admin/subscriptions, llevá al destino correcto
    return RedirectResponse(url="/billing/subscriptions", status_code=302)

@router.get("/billing", include_in_schema=False)
def admin_billing_redirect():
    # Alias por si algún botón apunta a /admin/billing
    return RedirectResponse(url="/billing", status_code=302)

# ----------------- Stats (JSON) -----------------
@router.get("/stats", name="admin_stats")
def stats(db= Depends(get_db), current=Depends(get_current_user_cookie)):
    require_admin(current)
    now = datetime.utcnow()
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year, now.month, monthrange(now.year, now.month)[1], 23, 59, 59)

    pdfs_mes = 0
    if ReportModel is not None and hasattr(ReportModel, "created_at"):
        pdfs_mes = db.query(ReportModel).filter(
            ReportModel.created_at >= start, ReportModel.created_at <= end
        ).count()

    usuarios_free = db.query(User).filter(User.plan == "FREE").count()
    usuarios_pro = db.query(User).filter(User.plan == "PRO").count()
    try:
        usuarios_biz = db.query(User).filter(User.plan == "BIZ").count()
    except Exception:
        usuarios_biz = 0

    return {
        "pdfs_mes": pdfs_mes,
        "usuarios_free": usuarios_free,
        "usuarios_pro": usuarios_pro,
        "usuarios_biz": usuarios_biz,
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
    }

# ----------------- Suscripciones (nuevo, mínimo) -----------------

@router.get("/user/{email}/subscription", tags=["admin"])
def admin_get_subscription(
    email: str,
    db= Depends(get_db),
    current=Depends(get_current_user_cookie),
):
    """
    Ver estado de suscripción de un usuario por email (case-insensitive).
    """
    require_admin(current)
    email_norm = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return {
        "email": user.email,
        "is_pro": bool(getattr(user, "is_pro", False)),
        "plan": getattr(user, "plan", None),
        "plan_expires": getattr(user, "plan_expires", None),
    }

class ForceProReq(BaseModel):
    email: EmailStr
    months: int = 1

@router.post("/force_pro", tags=["admin"])
def admin_force_pro(
    req: ForceProReq,
    db= Depends(get_db),
    current=Depends(get_current_user_cookie),
):
    """
    Activar PRO manualmente a un usuario por X meses (default 1).
    Deja el plan como 'PRO' (coherente con /admin/stats).
    """
    require_admin(current)

    email_norm = req.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email_norm).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    now = datetime.utcnow()
    expires = getattr(user, "plan_expires", None) or now
    if expires < now:
        expires = now
    expires = expires + timedelta(days=30 * max(req.months, 1))

    user.is_pro = True
    user.plan = "PRO"
    user.plan_expires = expires
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "email": user.email,
        "is_pro": True,
        "plan": user.plan,
        "plan_expires": user.plan_expires,
    }
