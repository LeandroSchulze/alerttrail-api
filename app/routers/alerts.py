# app/routers/alerts.py
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Ajustá estos imports a tu modelo real de Alert
try:
    from app.models import Alert
except Exception:
    Alert = None  # si no existe, el endpoint devuelve 0

@router.get("/unread-count")
def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    if Alert is None:
        return {"count": 0}
    count = db.query(Alert).filter(Alert.user_id == user.id, Alert.is_read == False).count()
    return {"count": count}
