# app/events/alerts_hooks.py
import logging
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.models import User  # Ajustá el import si tu User está en otro módulo

# Configuración de logs para ver qué pasa en Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AlertTrail.Hooks")

# Import robusto de MailAlert
try:
    from app.models import MailAlert
except ImportError:
    from app.models_mail import MailAlert  # fallback si lo tenés separado

from app.services.pro_alerts import queue_or_push

@event.listens_for(MailAlert, "after_insert")
def on_mail_alert_insert(mapper, connection, target):
    """
    Se ejecuta automáticamente cuando se inserta una MailAlert en la DB.
    Ideal para que el Cron Job dispare la notificación al detectar un riesgo.
    """
    # Usamos el objeto Session vinculado a la conexión actual
    db = Session(bind=connection)
    
    try:
        user_id = getattr(target, "user_id", None)
        user = db.query(User).get(user_id)
        
        if not user:
            logger.warning(f"⚠️ No se encontró el usuario {user_id} para la alerta {target.id}")
            return

        # Extraemos datos básicos del mail detectado
        subject = getattr(target, "subject", "Alerta de Seguridad")
        sender  = getattr(target, "sender", "Desconocido")
        url_id  = getattr(target, "id", None)
        
        # El nivel de riesgo (para personalizar el mensaje si querés)
        verdict = getattr(target, "verdict", "ALTO")
        
        # Construimos la URL a la que llevará el clic en la notificación
        url = f"/mail/alerts/{url_id}" if url_id else "/reports"

        logger.info(f"🚀 Disparando notificación Web Push para usuario {user_id} - Riesgo: {verdict}")

        # Enviamos la notificación PRO (Web Push con VAPID)
        # Asegurate de que 'user' tenga el campo de suscripción en la DB
        queue_or_push(
            db, 
            user,
            title=f"⚠️ Mail Sospechoso ({verdict})",
            body=f"De: {sender}\nAsunto: {subject}",
            url=url
        )
        
    except Exception as e:
        # Importante: nunca bloqueamos el escaneo si la notificación falla
        logger.error(f"❌ Error enviando notificación en el hook: {str(e)}")
    finally:
        db.close()
