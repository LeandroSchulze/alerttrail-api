# app/tasks/mail_poll.py
from __future__ import annotations

import logging
import sys

from app.services.mail_scanner import scan_all_connected_mailboxes

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
        scanned = scan_all_connected_mailboxes()
        log.info("Mail poll completed. Accounts scanned: %s", scanned)
        return scanned
    except Exception as e:
        log.exception("Mail poll failed: %s", e)
        return 0


# 🔑 CLAVE: permitir ejecución standalone (cron)
if __name__ == "__main__":
    scanned = poll_all_accounts()
    # exit code útil para cron / logs
    sys.exit(0 if scanned >= 0 else 1)
