# app/routers/alerts.py
import os
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy import text

from app.database import get_db, SessionLocal
from app.security import get_current_user_cookie
from app.services.mail_auth_checks import check_auth

router = APIRouter(prefix="/alerts", tags=["alerts"])
templates = Jinja2Templates(directory="app/templates")

# ------------------------------------------------------------------
# Auto-migración: columnas para semáforo de autenticación
def _ensure_mail_alerts_auth_columns(db: Session):
    """
    Agrega columnas spf_status, dkim_status, dmarc_status si no existen.
    Funciona en SQLite y Postgres.
    """
    dialect = db.bind.dialect.name  # "sqlite" | "postgresql" | ...
    cols = {"spf_status": "VARCHAR(16)", "dkim_status": "VARCHAR(16)", "dmarc_status": "VARCHAR(16)"}

    if dialect == "sqlite":
        rows = db.execute(text("PRAGMA table_info(mail_alerts)")).fetchall()
        existing = {r[1] for r in rows}
        for col, typ in cols.items():
            if col not in existing:
                db.execute(text(f"ALTER TABLE mail_alerts ADD COLUMN {col} {typ}"))
        db.commit()
    else:
        for col, typ in cols.items():
            db.execute(text(f"ALTER TABLE mail_alerts ADD COLUMN IF NOT EXISTS {col} {typ}"))
        db.commit()

# ------------------------------------------------------------------
# helper para obtener el id del usuario (objeto o dict)
def _uid(u):
    if isinstance(u, dict):
        return u.get("id") or u.get("uid") or u.get("sub")
    return getattr(u, "id", None)
# ------------------------------------------------------------------

# 1) Modelo de datos (fallback)…
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
        # claves y contenido
        msg_uid = Column(String, index=True)
        subject = Column(Text, default="")
        sender = Column(String, default="")              # alias posible de from_email
        from_email = Column(String, default="")          # opcional si existe en tu DB
        snippet = Column(Text, default="")
        link = Column(String, default="/mail/scanner")
        score = Column(Integer, default=0)
        reason = Column(String, default="")              # compat previo
        # estados
        created_at = Column(DateTime, default=dt.datetime.utcnow)
        updated_at = Column(DateTime, nullable=True)
        is_read = Column(Boolean, default=False)
        # semáforo de autenticación
        spf_status = Column(String(16), default="")
        dkim_status = Column(String(16), default="")
        dmarc_status = Column(String(16), default="")

    try:
        LocalBase.metadata.create_all(_engine)
    except Exception:
        pass

# 2) Helper create_alert
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
    spf_status: str = "",
    dkim_status: str = "",
    dmarc_status: str = "",
):
    # idempotencia si hay msg_uid/ext_key
    if hasattr(Alert, "msg_uid") and ext_key:
        existing = (
            db.query(Alert)
            .filter(Alert.user_id == user_id, Alert.msg_uid == ext_key)
            .first()
        )
        if existing:
            return existing

    fields = {"user_id": user_id, "subject": (subject or "")[:250]}
    # alias / columnas opcionales
    if hasattr(Alert, "sender"):
        fields["sender"] = (from_email or "")[:250]
    if hasattr(Alert, "from_email"):
        fields["from_email"] = (from_email or "")[:250]
    if hasattr(Alert, "reason"):
        fields["reason"] = (snippet or "")[:5000]
    if hasattr(Alert, "snippet"):
        fields["snippet"] = (snippet or "")[:5000]
    if hasattr(Alert, "link"):
        fields["link"] = link or "/mail/scanner"
    if hasattr(Alert, "score"):
        fields["score"] = int(score or 0)
    if hasattr(Alert, "msg_uid") and ext_key:
        fields["msg_uid"] = ext_key
    # semáforo (si existen columnas)
    if hasattr(Alert, "spf_status"):
        fields["spf_status"] = (spf_status or "")
    if hasattr(Alert, "dkim_status"):
        fields["dkim_status"] = (dkim_status or "")
    if hasattr(Alert, "dmarc_status"):
        fields["dmarc_status"] = (dmarc_status or "")

    a = Alert(**fields)  # type: ignore
    db.add(a)
    db.commit()
    return a

# 3) unread-count
@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    uid = _uid(user)
    if not uid:
        raise HTTPException(status_code=401, detail="No autenticado")

    count = db.query(Alert).filter(Alert.user_id == uid, Alert.is_read == False).count()
    return {"count": int(count)}


# 4) Página HTML del Centro de Alertas
@router.get("", response_class=HTMLResponse)
def alerts_page(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    # Sólo para asegurar columnas si cae aquí primero
    _ensure_mail_alerts_auth_columns(db)

    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    return templates.TemplateResponse("alerts.html", {"request": request, "user": user})


# 5) API de listado con filtros (para la tabla)
@router.get("/list", response_class=JSONResponse)
def alerts_list(
    request: Request,
    q: Optional[str] = Query(None),
    sev: Optional[str] = Query(None, description="high|medium|low"),
    status: Optional[str] = Query(None, description="pending|ack"),
    days: Optional[int] = Query(7, description="últimos N días"),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    uid = _uid(user)
    if not uid:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Si tenés Alert como modelo ORM global, usamos ese
    if Alert is not None and not isinstance(Alert, type):
        raise RuntimeError("Alert mal definido")

    # Si Alert viene de app.models lo usamos directo;
    # si no, definimos un modelo inline compatible
    if Alert.__module__.startswith("app.models"):
        MailAlert = Alert
    else:
        # Modelo inline compatible
        Base = declarative_base()
        class MailAlert(Base):
            __tablename__ = "mail_alerts"
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, index=True, nullable=False)
            subject = Column(Text, default="")
            sender = Column(String, default="")
            from_email = Column(String, default="")
            snippet = Column(Text, default="")
            score = Column(Integer, default=0)
            link = Column(String, default="/mail/scanner")
            is_read = Column(Boolean, default=False)
            created_at = Column(DateTime, default=dt.datetime.utcnow)
            spf_status = Column(String(16), default="")
            dkim_status = Column(String(16), default="")
            dmarc_status = Column(String(16), default="")

    query = db.query(MailAlert).filter(MailAlert.user_id == uid)

    if days:
        since = dt.datetime.utcnow() - dt.timedelta(days=int(days))
        query = query.filter(MailAlert.created_at >= since)

    if status in ("pending", "ack"):
        want_read = (status == "ack")
        query = query.filter(MailAlert.is_read == want_read)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (MailAlert.subject.ilike(like))
            | (MailAlert.snippet.ilike(like))
            | (MailAlert.sender.ilike(like))
            | (MailAlert.from_email.ilike(like))
        )

    rows = query.order_by(MailAlert.id.desc()).limit(limit).all()

    items = []
    for r in rows:
        from_addr = (getattr(r, "from_email", "") or getattr(r, "sender", "") or "").strip()
        # overall simple: fail > pass > warn
        spf = (r.spf_status or "unknown").lower()
        dkim = (r.dkim_status or "unknown").lower()
        dmarc = (r.dmarc_status or "unknown").lower()

        if "fail" in (dkim, dmarc):
            overall = "fail"
        elif "pass" in (spf, dkim, dmarc):
            overall = "pass"
        else:
            overall = "warn"

        created_iso = None
        created = getattr(r, "created_at", None)
        if created:
            try:
                created_iso = created.isoformat()
            except Exception:
                created_iso = str(created)

        items.append({
            "id": r.id,
            "subject": r.subject or "",
            "from_email": from_addr,
            "snippet": (r.snippet or getattr(r, "reason", "") or "")[:5000],
            "score": int(getattr(r, "score", 0) or 0),
            "link": r.link or "/mail/scanner",
            "is_read": bool(r.is_read),
            "created_at": created_iso,
            "auth_overall": overall,
            "spf_status": spf,
            "dkim_status": dkim,
            "dmarc_status": dmarc,
        })

    return {"ok": True, "items": items}


# 6) PUSH HTTP (crea alerta + semáforo)
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
    db= Depends(get_db),
):
    token = request.headers.get("x-alert-push-token", "")
    if ALERT_PUSH_TOKEN and token != ALERT_PUSH_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido")

    _ensure_mail_alerts_auth_columns(db)

    u = None
    if user_id:
        u = db.query(User).get(user_id)
    elif email:
        u = db.query(User).filter(User.email.ilike(email)).first()

    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Semáforo SPF/DKIM/DMARC
    domain = ""
    try:
        domain = (from_email or "").split("@", 1)[1].lower().strip()
    except Exception:
        domain = ""

    auth_res = {"spf":{"status":"unknown"},"dkim":{"status":"unknown"},"dmarc":{"status":"unknown"}}
    if domain:
        # Si llega header Authentication-Results, mejora DKIM
        auth_res = check_auth(domain, request.headers.get("Authentication-Results"))

    spf_status  = (auth_res.get("spf", {}).get("status") or "unknown").lower()
    dkim_status = (auth_res.get("dkim", {}).get("status") or "unknown").lower()
    dmarc_status= (auth_res.get("dmarc", {}).get("status") or "unknown").lower()

    a = create_alert(
        db,
        user_id=u.id,
        subject=subject,
        from_email=from_email,
        snippet=snippet,
        score=score,
        link=link,
        ext_key=ext_key,
        spf_status=spf_status,
        dkim_status=dkim_status,
        dmarc_status=dmarc_status,
    )
    return {"ok": True, "id": a.id}

# 7) pending (usa _uid)
@router.get("/pending", response_class=JSONResponse)
def pending_alert(db= Depends(get_db), user=Depends(get_current_user_cookie)):
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
    try:
        created_iso = created.isoformat() if created else None
    except Exception:
        created_iso = str(created) if created else None

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

# 8) ACK (usa _uid)
@router.post("/{alert_id}/ack", response_class=JSONResponse)
def ack_alert(alert_id: int, db= Depends(get_db), user=Depends(get_current_user_cookie)):
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
