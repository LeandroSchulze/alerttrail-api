# app/routers/alerts.py
import os
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, UniqueConstraint

from app.database import get_db, SessionLocal
from app.security import get_current_user_cookie

router = APIRouter(prefix="/alerts", tags=["alerts"])

# ------------------------------------------------------------------------------
# 1) Modelo de datos
#    - Si existe app.models.Alert lo usamos.
#    - Si NO existe, definimos uno local (tabla: mail_alerts) y la creamos.
# ------------------------------------------------------------------------------
try:
    from app.models import Alert as ORMAlert, User  # preferencia por tu modelo
except Exception:
    ORMAlert = None
    from app.models import User  # igual intentamos User

if ORMAlert is not None:
    Alert = ORMAlert
    LocalBase = None
else:
    LocalBase = declarative_base()
    _engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

    class Alert(LocalBase):
        __tablename__ = "mail_alerts"
        __table_args__ = (UniqueConstraint("ext_key", name="uq_mail_alerts_extkey"),)

        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
        subject = Column(String, default="")
        from_email = Column(String, default="")
        snippet = Column(Text, default="")
        score = Column(Integer, default=0)     # riesgo / heurística
        link = Column(String, default="/mail/scanner")
        is_read = Column(Boolean, default=False)
        ext_key = Column(String, nullable=True, index=True)  # idempotencia opcional
        created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc))
        updated_at = Column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc))

    try:
        LocalBase.metadata.create_all(_engine)
    except Exception:
        pass

# ------------------------------------------------------------------------------
# 2) Helper para crear alertas desde el scanner (sin HTTP)
# ------------------------------------------------------------------------------
def create_alert(
    db: Session,
    *,
    user_id: int,
    subject: str,
    from_email: str,
    snippet: str = "",
    score: int = 0,
    link: str = "/mail/scanner",
    ext_key: Optional[str] = None,
):
    """
    Crea una alerta. Si se pasa ext_key y ya existe, se devuelve la existente (idempotente).
    Usar desde tu código Python del scanner: create_alert(db, user_id=..., subject=..., from_email=...)
    """
    # Si el modelo tiene ext_key, probamos idempotencia
    if hasattr(Alert, "ext_key") and ext_key:
        existing = db.query(Alert).filter(Alert.ext_key == ext_key).first()
        if existing:
            return existing

    alert = Alert(
        user_id=user_id,
        subject=(subject or "")[:250],
        from_email=(from_email or "")[:250],
        snippet=(snippet or "")[:5000],
        score=int(score or 0),
        link=link or "/mail/scanner",
    )
    if hasattr(alert, "ext_key"):
        alert.ext_key = ext_key
    db.add(alert)
    db.commit()
    return alert

# ------------------------------------------------------------------------------
# 3) Endpoint de compatibilidad: unread-count (con tu firma original)
# ------------------------------------------------------------------------------
@router.get("/unread-count")
def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    # Si no hay modelo (raro), devolvemos 0
    if Alert is None:
        return {"count": 0}
    count = db.query(Alert).filter(Alert.user_id == user.id, Alert.is_read == False).count()
    return {"count": count}

# ------------------------------------------------------------------------------
# 4) PUSH HTTP (para cron/worker): crear alerta vía request
#    Seguridad mínima con token de cabecera: X-Alert-Push-Token
# ------------------------------------------------------------------------------
ALERT_PUSH_TOKEN = (os.getenv("ALERT_PUSH_TOKEN") or "").strip()

@router.post("/push", response_class=JSONResponse)
def push_alert(
    request: Request,
    email: Optional[str] = Query(None, description="Email del usuario (si no pasás user_id)"),
    user_id: Optional[int] = Query(None, description="ID del usuario"),
    subject: str = Query(...),
    from_email: str = Query(...),
    snippet: str = Query(""),
    score: int = Query(0),
    link: str = Query("/mail/scanner"),
    ext_key: Optional[str] = Query(None, description="Idempotency key (opcional)"),
    db: Session = Depends(get_db),
):
    token = request.headers.get("x-alert-push-token", "")
    if ALERT_PUSH_TOKEN and token != ALERT_PUSH_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido")

    # Resolver usuario
    u = None
    if user_id:
        u = db.query(User).get(user_id)
    elif email:
        u = db.query(User).filter(User.email.ilike(email)).first()

    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    a = create_alert(
        db,
        user_id=u.id,
        subject=subject,
        from_email=from_email,
        snippet=snippet,
        score=score,
        link=link,
        ext_key=ext_key,
    )
    return {"ok": True, "id": a.id}

# ------------------------------------------------------------------------------
# 5) PENDING: el frontend pregunta si hay alerta pendiente (no leída)
# ------------------------------------------------------------------------------
@router.get("/pending", response_class=JSONResponse)
def pending_alert(db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    if not user:
        return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)

    a = (
        db.query(Alert)
        .filter(Alert.user_id == user.id, Alert.is_read == False)
        .order_by(Alert.id.desc())
        .first()
    )
    if not a:
        return {"ok": True, "pending": False}

    return {
        "ok": True,
        "pending": True,
        "alert": {
            "id": a.id,
            "subject": getattr(a, "subject", "") or "",
            "from_email": getattr(a, "from_email", "") or "",
            "snippet": (getattr(a, "snippet", "") or "")[:500],
            "score": int(getattr(a, "score", 0) or 0),
            "link": getattr(a, "link", "/mail/scanner") or "/mail/scanner",
            "created_at": (a.created_at.isoformat() if getattr(a, "created_at", None) else None),
        },
    }

# ------------------------------------------------------------------------------
# 6) ACK: marcar alerta como leída
# ------------------------------------------------------------------------------
@router.post("/{alert_id}/ack", response_class=JSONResponse)
def ack_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    if not user:
        return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)

    a = db.query(Alert).filter(Alert.id == alert_id, Alert.user_id == user.id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    if hasattr(a, "is_read"):
        a.is_read = True
    if hasattr(a, "updated_at"):
        a.updated_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {"ok": True}
