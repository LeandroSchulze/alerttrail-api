"""
Background mail scan utilities.

Este módulo lo usa el scheduler automático (cada N minutos) para escanear
las casillas IMAP linkeadas y guardar el *último resultado* en disco.

Ese mismo archivo es consumido por:
  - UI: /mail/scanner
  - Poller de pop-ups: /alerts/pending

Formato estable guardado en disco (por usuario):

  {
    "ok": true,
    "scanned_at": "2025-01-01T00:00:00Z",
    "folder": "INBOX",
    "address": "user@domain.com",
    "total": 25,
    "unread": 0,
    "items": [
      {
        "uid": "...",
        "subject": "...",
        "from": "...",
        "date": "...",
        "attachments": [...],
        "analysis": {
          "danger_level": "low|medium|high",
          "reasons": [...],
          "iocs": {...},
          "hints": {...}
        }
      }
    ],
    "counts": {...},
    "dangerous": 2,
    "error": null,
    "limit": 50
  }
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database import get_db
from app.models import MailAccount, User
from app.services.mail_scan import scan_mailbox

logger = logging.getLogger("alerttrail.mail")

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_key(user: Optional[User], fallback_user_id: Optional[int] = None) -> str:
    """
    Clave estable para el archivo scan_last_{user_key}.json
    Debe matchear con _user_id() del router /mail (normalmente payload.sub == user.id).
    """
    if user and getattr(user, "id", None) is not None:
        return str(user.id)
    if fallback_user_id is not None:
        return str(fallback_user_id)
    if user and getattr(user, "email", None):
        return str(user.email)
    return "unknown"


def _scan_file_for_user_id(user_id: str) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{user_id}.json"


def scan_all_inboxes(limit: int = 50) -> Dict[str, Any]:
    """
    Escanea TODAS las casillas IMAP activas en DB (MailAccount.is_active==True)
    y persiste el último scan por usuario.

    OJO: esto es lo que usa el auto-scan programado.
    """
    scanned = 0
    errors = 0
    dangerous_total = 0

    with next(get_db()) as db:
        accounts: List[MailAccount] = (
            db.query(MailAccount).filter(MailAccount.is_active == True).all()  # noqa: E712
        )

        for acc in accounts:
            scanned += 1
            try:
                user: Optional[User] = db.get(User, acc.user_id) if acc.user_id else None
                user_key = _user_key(user, fallback_user_id=acc.user_id)

                res = scan_mailbox(
                    host=acc.imap_host,
                    port=int(acc.imap_port or 993),
                    username=acc.imap_username,
                    password=acc.imap_password,
                    folder=acc.imap_folder or "INBOX",
                    use_ssl=bool(acc.imap_ssl if acc.imap_ssl is not None else True),
                    limit=int(limit),
                    mark_read=bool(acc.mark_read or False),
                )

                # Normalizamos items para que /alerts/pending funcione siempre
                items: List[Dict[str, Any]] = []
                for it in (res.items or []):
                    analysis = getattr(it, "analysis", None)

                    items.append(
                        {
                            "uid": str(getattr(it, "uid", "") or ""),
                            "subject": str(getattr(it, "subject", "") or ""),
                            "from": str(getattr(it, "from_email", "") or ""),
                            "date": str(getattr(it, "date", "") or ""),
                            "attachments": list(getattr(it, "attachments", []) or []),
                            "analysis": {
                                "danger_level": str(getattr(analysis, "danger_level", "") or "low").lower(),
                                "reasons": list(getattr(analysis, "reasons", []) or []),
                                "iocs": dict(getattr(analysis, "iocs", {}) or {}),
                                "hints": dict(getattr(analysis, "hints", {}) or {}),
                            },
                        }
                    )

                dangerous = int(getattr(res, "dangerous", 0) or 0)
                dangerous_total += dangerous

                payload = {
                    "ok": bool(getattr(res, "ok", True)),
                    "scanned_at": _now_iso(),
                    "folder": acc.imap_folder or "INBOX",
                    "address": getattr(acc, "email_address", None) or getattr(acc, "imap_username", None),
                    "total": int(getattr(res, "total_found", 0) or 0),
                    "unread": int(getattr(res, "unread", 0) or 0),
                    "items": items,
                    "counts": dict(getattr(res, "counts", {}) or {}),
                    "dangerous": dangerous,
                    "error": getattr(res, "message", None),
                    "limit": int(limit),
                }

                _save_json(_scan_file_for_user_id(user_key), payload)

            except Exception as e:
                errors += 1
                logger.exception("AUTO_MAIL_SCAN failed account_id=%s: %s", getattr(acc, "id", "?"), e)

    return {
        "ok": errors == 0,
        "scanned": scanned,
        "errors": errors,
        "dangerous": dangerous_total,
    }
