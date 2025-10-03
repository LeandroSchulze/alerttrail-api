# app/routers/alerts.py
import os
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean

from app.database import get_db, SessionLocal
from app.security import get_current_user_cookie

router = APIRouter(prefix="/alerts", tags=["alerts"])

# ------------------------------------------------------------------
# helper para obtener el id del usuario (objeto o dict)
def _uid(u):
    if isinstance(u, dict):
        return u.get("id") or u.get("uid") or u.get("sub")
    return getattr(u, "id", None)
# ------------------------------------------------------------------

# 1) Modelo de datos…
try:
    from app.models import Alert as ORMAlert, User  # si tu proyecto lo define
    Alert = ORMAlert
    LocalBase = None
except Exception:
    from app.models import User  # igual intentamos User
    LocalBase = declarative_base()
    _engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

    class Alert(LocalBase):
        __tablename__ = "mail_alerts"
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
        msg_uid = Column(String, index=True)
        subject = Column(Text, default="")
        sender = Column(String, default="")
        reason = Column(String, default="")
        created_at = Column(DateTime, default=dt.datetime.utcnow)
        is_read = Column(Boolean, default=False)

    try:
        LocalBase.metadata.create_all(_engine)
    except Exception:
        pass

# 2) Helper create_alert (sin cambios relevantes)
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
    if hasattr(Alert, "msg_uid") and ext_key:
        existing = (
            db.query(Alert)
            .filter(Alert.user_id == user_id, Alert.msg_uid == ext_key)
            .first()
        )
        if existing:
            return existing

    fields = {"user_id": user_id, "subject": (subject or "")[:250]}
    if hasattr(Alert, "sender"):
        fields["sender"] = (from_email or "")[:250]
    if hasattr(Alert, "reason"):
        fields["reason"] = (snippet or "")[:5000]
    if ext_key and hasattr(Alert, "msg_uid"):
        fields["msg_uid"] = ext_key
    if hasattr(Alert, "from_email"):
        fields["from_email"] = (from_email or "")[:250]
    if hasattr(Alert, "snippet"):
        fields["snippet"] = (snippet or "")[:5000]
    if hasattr(Alert, "link"):
        fields["link"] = link or "/mail/scanner"
    if hasattr(Alert, "score"):
        fields["score"] = int(score or 0)
    if hasattr(Alert, "ext_key") and ext_key:
        fields["ext_key"] = ext_key

    a = Alert(**fields)  # type: ignore
    db.add(a)
    db.commit()
    return a

# 3) unread-count
@router.get("/unread-count")
def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    uid = _uid(user)
    count = db.query(Alert).filter(Alert.user_id == uid, Alert.is_read == False).count()
    return {"count": int(count)}

# 4) PUSH HTTP (igual que tu versión)
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

# 5) pending (usa _uid para evitar AttributeError)
@router.get("/pending", response_class=JSONResponse)
def pending_alert(db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    uid = _uid(user)
    if not uid:
        return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)

    a = (
        db.query(Alert)
        .filter(Alert.user_id == uid, Alert.is_read == False)
        .order_by(Alert.id.desc())
        .first()
    )
    if not a:
        return {"ok": True, "pending": False}

    from_email = getattr(a, "from_email", None) or getattr(a, "sender", "") or ""
    snippet = getattr(a, "snippet", None) or getattr(a, "reason", "") or ""
    link = getattr(a, "link", "/mail/scanner") or "/mail/scanner"

    created = getattr(a, "created_at", None)
    created_iso = None
    if created:
        try:
            created_iso = created.isoformat()
        except Exception:
            created_iso = str(created)

    return {
        "ok": True,
        "pending": True,
        "alert": {
            "id": a.id,
            "subject": getattr(a, "subject", "") or "",
            "from_email": from_email,
            "snippet": snippet[:500],
            "score": int(getattr(a, "score", 0) or 0),
            "link": link,
            "created_at": created_iso,
        },
    }

# 6) ACK (usa _uid)
@router.post("/{alert_id}/ack", response_class=JSONResponse)
def ack_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    uid = _uid(user)
    if not uid:
        return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)

    a = db.query(Alert).filter(Alert.id == alert_id, Alert.user_id == uid).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    if hasattr(a, "is_read"):
        a.is_read = True
    if hasattr(a, "updated_at"):
        a.updated_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {"ok": True}
