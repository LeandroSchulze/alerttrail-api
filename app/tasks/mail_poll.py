# app/tasks/mail_poll.py
from __future__ import annotations

import logging
import sys
import os
import json
from pathlib import Path

from app.services.mail_scanner import scan_all_connected_mailboxes
from app.routers.push import trigger_push_notification
from app.database import SessionLocal
from app.models import PushSubscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mail-poll] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# Archivo para evitar spam de notificaciones
CACHE_FILE = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail")) / "last_alerted_uids.json"

def _get_notified_uids() -> set:
    try:
        if CACHE_FILE.exists():
            return set(json.loads(CACHE_FILE.read_text()))
    except: pass
    return set()

def _save_notified_uid(uid: str):
    uids = _get_notified_uids()
    uids.add(uid)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(list(uids)[-50:])) # Guardamos solo los últimos 50

def poll_all_accounts() -> int:
    """
    Escaneo inteligente: Solo notifica si el nivel es ALTA y no se ha notificado antes.
    """
    try:
        # scan_all_connected_mailboxes debería devolver una estructura con los resultados
        # Ajustado para que si retorna datos, los procesemos
        results = scan_all_connected_mailboxes() # Asegúrate que esta función devuelva los items
        log.info("Mail poll completed.")
        
        db = SessionLocal()
        notified_uids = _get_notified_uids()
        new_alerts = 0

        try:
            # Iteramos sobre los resultados. Ajusta esto según el retorno real de scan_all_connected_mailboxes
            # Asumo que devuelve una lista de cuentas o resultados
            for account_scan in (results if isinstance(results, list) else []):
                user_id = getattr(account_scan, "user_id", None)
                items = getattr(account_scan, "items", [])

                for item in items:
                    # 1. Filtro estricto: Solo nivel ALTA
                    analysis = getattr(item, "analysis", {})
                    level = getattr(analysis, "danger_level", "low").lower()
                    uid = str(item.uid)

                    if level == "alta" and uid not in notified_uids:
                        log.info("🔔 ALERTA ALTA detectada para usuario %s: %s", user_id, item.subject)
                        
                        trigger_push_notification(
                            user_id=user_id,
                            title="🚨 ALERTA CRÍTICA DE SEGURIDAD",
                            body=f"Amenaza detectada: {item.subject[:40]}"
                        )
                        
                        _save_notified_uid(uid)
                        new_alerts += 1
                        
        except Exception as e:
            log.error("Error procesando alertas: %s", e)
        finally:
            db.close()
        
        return new_alerts
    except Exception as e:
        log.exception("Mail poll failed: %s", e)
        return 0

if __name__ == "__main__":
    scanned = poll_all_accounts()
    sys.exit(0)
