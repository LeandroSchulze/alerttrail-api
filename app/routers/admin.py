# app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
from calendar import monthrange

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
    if not u or getattr(u, "role", None) != "admin":
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
def stats(db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
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
