# app/events/alerts_hooks.py
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.models import User  # ajustá el import si tu User está en otro módulo

# Import robusto de MailAlert (ajusta si está en otro archivo)
try:
    from app.models import MailAlert
except ImportError:
    from app.models_mail import MailAlert  # fallback si lo tenés separado

from app.services.pro_alerts import queue_or_push

@event.listens_for(MailAlert, "after_insert")
def on_mail_alert_insert(mapper, connection, target):
    """
    Se ejecuta cuando se inserta una MailAlert.
    Enviamos la notificación PRO sin romper la transacción principal.
    """
    db = Session(bind=connection)
    try:
        user = db.query(User).get(getattr(target, "user_id", None))
        if not user:
            return
        subject = getattr(target, "subject", "Alerta")
        sender  = getattr(target, "sender", "")
        url_id  = getattr(target, "id", None)
        url = f"/mail/alerts/{url_id}" if url_id else "/reports"

        # Encola o envía según cooldown/quiet-hours (si no es PRO, no hace nada)
        queue_or_push(db, user,
            title="Mail sospechoso",
            body=f"Asunto: {subject} — Remitente: {sender}",
            url=url
        )
    except Exception as e:
        # Nunca rompas la transacción de negocio por una notificación
        print("alerts_hooks error:", e)
    finally:
        db.close()
