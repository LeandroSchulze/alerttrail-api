from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session


def scan_all_connected_mailboxes(db: Optional[Session] = None, limit: int | None = None, dry_run: bool = False) -> int:
    """
    Motor real para /tasks/mail/poll.
    - db se acepta para compatibilidad (aunque hoy el scan usa JSON store).
    - limit/dry_run por compatibilidad con el endpoint (dry_run hoy no cambia nada).
    Retorna cantidad de casillas escaneadas.
    """
    from app.services.mail import scan_all_inboxes
    import os

    if limit is not None:
        os.environ["MAIL_SCAN_LIMIT"] = str(int(limit))

    out = scan_all_inboxes()
    return int(out.get("scanned", 0) or 0)
