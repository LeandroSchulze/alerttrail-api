# app/tasks/mail_poll.py
from __future__ import annotations

import logging
import sys
import os

from app.services.mail_scanner import scan_all_connected_mailboxes
from app.routers.push import trigger_push_notification
# --- CONEXIONES COMPATIBLES AGREGADAS ---
from app.database import SessionLocal
from app.models import PushSubscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mail-poll] %(levelname)s: %(message)s",
)

log = logging.getLogger(__name__)


def poll_all_accounts() -> int:
    """
    Entry point REAL del auto scan.
    Llamado por:
      - cron
      - APScheduler (si está activo)
    """
    try:
        # Ejecuta el escaneo de todas las cuentas
        scanned_count = scan_all_connected_mailboxes()
        log.info("Mail poll completed. Accounts scanned: %s", scanned_count)
        
        # Si se escanearon cuentas, disparamos la notificación
        if scanned_count > 0:
            # 🔌 CONEXIÓN REAL CON POSTGRESQL:
            # Abrimos una sesión manual limpia (esencial para tareas en segundo plano / hilos)
            db = SessionLocal()
            try:
                # Buscamos de forma única todos los user_id que tengan alertas configuradas
                active_subs = db.query(PushSubscription.user_id).distinct().all()
                
                for (user_id,) in active_subs:
                    log.info("Sending push alert to user: %s", user_id)
                    trigger_push_notification(
                        user_id=user_id,
                        title="Alerta de Seguridad",
                        body="Se detectaron correos sospechosos en tu bandeja."
                    )
            except Exception as db_err:
                log.error("Error al obtener suscripciones de la DB en segundo plano: %s", db_err)
            finally:
                db.close() # 🔑 CLAVE: Cerramos siempre la conexión para no agotar el pool de Railway
        
        return scanned_count
    except Exception as e:
        log.exception("Mail poll failed: %s", e)
        return 0


# 🔑 CLAVE: permitir ejecución standalone (cron)
if __name__ == "__main__":
    scanned = poll_all_accounts()
    # exit code útil para cron / logs
    sys.exit(0 if scanned >= 0 else 1)
