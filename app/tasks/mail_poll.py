# app/tasks/mail_poll.py
from __future__ import annotations

import logging
import sys
import os

from app.services.mail_scanner import scan_all_connected_mailboxes
from app.routers.push import trigger_push_notification, _load

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
            # Lógica temporal: Notificar a todos los que tengan una suscripción activa
            # Esto asegura que recibas la alerta mientras ajustamos la granularidad por ID
            data = _load()
            for user_id in data.keys():
                log.info("Sending push alert to user: %s", user_id)
                trigger_push_notification(
                    user_id=user_id,
                    title="Alerta de Seguridad",
                    body="Se detectaron correos sospechosos en tu bandeja."
                )
        
        return scanned_count
    except Exception as e:
        log.exception("Mail poll failed: %s", e)
        return 0


# 🔑 CLAVE: permitir ejecución standalone (cron)
if __name__ == "__main__":
    scanned = poll_all_accounts()
    # exit code útil para cron / logs
    sys.exit(0 if scanned >= 0 else 1)
