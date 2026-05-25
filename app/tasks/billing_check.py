# app/tasks/billing_check.py
from datetime import datetime, date, timedelta
import logging
from app.database import SessionLocal
from app.models import User  # O tu modelo de suscripción
from app.services.notifier import send_email_reminder  # Tu lógica de enviar mails

log = logging.getLogger(__name__)

def check_monthly_billing():
    db = SessionLocal()
    today = date.today()
    
    try:
        # 1. ENVIAR RECORDATORIO (Faltan 3 días para el vencimiento)
        reminder_date = today + timedelta(days=3)
        users_to_remind = db.query(User).filter(
            User.subscription_status == "active",
            User.valid_until == reminder_date
        ).all()
        
        for u in users_to_remind:
            log.info(f"Enviando recordatorio de pago a: {u.email}")
            send_email_reminder(
                email=u.email, 
                subject="Tu abono de AlertTrail vencerá pronto",
                body="Hola! Te recordamos que en 3 días vence tu acceso. Para seguir protegido, recordá realizar tu pago."
            )

        # 2. PAUSAR ACCESO (Ya se cumplieron los 30 días y no pagó)
        expired_users = db.query(User).filter(
            User.subscription_status == "active",
            User.valid_until < today
        ).all()
        
        for u in expired_users:
            log.info(f"Pausando cuenta por falta de pago: {u.email}")
            u.subscription_status = "paused"
            # Acá podés mandarle un mail avisando que se pausó
            send_email_reminder(
                email=u.email,
                subject="Acceso pausado - AlertTrail",
                body="Tu acceso ha sido pausado temporalmente por falta de pago. Podés reactivarlo en cualquier momento realizando el abono."
            )
            
        db.commit()
    except Exception as e:
        log.error(f"Error en el chequeo de facturación: {e}")
        db.rollback()
    finally:
        db.close()
