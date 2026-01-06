# app/tasks/mail_poll.py
from __future__ import annotations

import logging
from typing import Optional

from app.database import SessionLocal

logger = logging.getLogger("alerttrail.mail")


def poll_all_accounts(limit: Optional[int] = None, dry_run: bool = False) -> int:
    """
    Entry-point llamado por el BackgroundScheduler en app/main.py.

    - Recorre casillas conectadas (MailAccount, etc.)
    - Genera alertas si corresponde
    - Devuelve cantidad escaneada/procesada (según tu implementación)
    """
    db = SessionLocal()
    try:
        try:
            # Tu lógica real (según tu tasks_mail.py)
            from app.services.mail_scanner import scan_all_connected_mailboxes
        except Exception as e:
            logger.exception("No se pudo importar scan_all_connected_mailboxes: %s", e)
            return 0

        try:
            # Intento con kwargs (limit/dry_run)
            scanned = scan_all_connected_mailboxes(db=db, limit=limit, dry_run=dry_run)  # type: ignore
        except TypeError:
            # Firma legacy
            scanned = scan_all_connected_mailboxes(db)  # type: ignore

        try:
            return int(scanned or 0)
        except Exception:
            return 0
    except Exception:
        logger.exception("Mail poll failed (poll_all_accounts)")
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass
