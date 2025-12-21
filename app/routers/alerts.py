# app/routers/alerts.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models_pro_alerts import ProAlertQueue
from app.security import get_current_user_cookie

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _infer_level(title: str, message: str) -> str:
    blob = f"{title or ''} {message or ''}".lower()
    if "alto" in blob or "high" in blob or "crítico" in blob or "critico" in blob:
        return "high"
    if "medio" in blob or "medium" in blob:
        return "medium"
    if "bajo" in blob or "low" in blob:
        return "low"
    return "info"


@router.get("/pending")
def pending_alerts(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint que usa el frontend (polling) para mostrar toasts / popups:
      GET /alerts/pending  ->  { "alerts": [ {id,title,message,level,url} ] }

    - Si no hay usuario logueado, devuelve lista vacía (no rompe el JS).
    - Consume (borra) los items de la cola para no repetirlos.
    """
    try:
        user = get_current_user_cookie(request, db)
    except Exception:
        return {"alerts": []}

    rows = (
        db.query(ProAlertQueue)
        .filter(ProAlertQueue.user_id == user.id)
        .order_by(ProAlertQueue.created_at.asc(), ProAlertQueue.id.asc())
        .limit(10)
        .all()
    )

    if not rows:
        return {"alerts": []}

    alerts_out = []
    for r in rows:
        title = (r.title or "").strip()
        message = (r.body or "").strip()
        alerts_out.append(
            {
                "id": r.id,
                "title": title or "Alerta",
                "message": message or "",
                "level": _infer_level(title, message),
                "url": r.url or "",
            }
        )

    # ✅ consumir la cola (evita duplicados en el polling)
    for r in rows:
        db.delete(r)
    db.commit()

    return {"alerts": alerts_out}
