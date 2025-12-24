"""Background mail scan utilities.

This module is used by the automatic scheduler (every N minutes).
It scans linked IMAP accounts and stores the last scan result on disk
so the UI (/mail/scanner) and the alerts poller (/alerts/pending) can
consume the same data.

Important: we store items in a stable shape compatible with alerts.

    {
      "uid": "...",
      "subject": "...",
      "from": "...",
      "date": "...",
      "attachments": [...],
      "analysis": { "danger_level": "low|medium|high", "reasons": [...], "iocs": {...}, "hints": {...} }
    }
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

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


def _user_id_from_user(user: User) -> str:
    if getattr(user, "id", None) is not None:
        return str(user.id)
    if getattr(user, "email", None):
        return str(user.email)
    return "unknown"


def _scan_file_for_user_id(user_id: str) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{user_id}.json"


def scan_all_inboxes(limit: int = 50) -> Dict[str, Any]:
    """Scan all active IMAP mailboxes stored in DB and persist last scan per user."""
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
                user: User | None = db.get(User, acc.user_id) if acc.user_id else None
                user_key = _user_id_from_user(user) if user else str(acc.user_id or "unknown")

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

                items: List[Dict[str, Any]] = []
                for it in (res.items or []):
                    analysis = it.analysis
                    items.append(
                        {
                            "uid": str(it.uid or ""),
                            "subject": str(it.subject or ""),
                            "from": str(it.from_email or ""),
                            "date": str(it.date or ""),
                            "attachments": list(it.attachments or []),
                            "analysis": {
                                "danger_level": str(getattr(analysis, "danger_level", "") or "low").lower(),
                                "reasons": list(getattr(analysis, "reasons", []) or []),
                                "iocs": dict(getattr(analysis, "iocs", {}) or {}),
                                "hints": dict(getattr(analysis, "hints", {}) or {}),
                            },
                        }
                    )

                counts = dict(res.counts or {})
                dangerous = int(res.dangerous or 0)
                dangerous_total += dangerous

                payload = {
                    "ok": bool(res.ok),
                    "scanned_at": _now_iso(),
                    "folder": acc.imap_folder or "INBOX",
                    "address": acc.email_address,
                    "total": int(res.total_found or 0),
                    "unread": int(res.unread or 0),
                    "items": items,
                    "counts": counts,
                    "dangerous": dangerous,
                    "error": res.message,
                    "limit": int(limit),
                }

                _save_json(_scan_file_for_user_id(user_key), payload)

            except Exception as e:
                errors += 1
                logger.exception("auto scan failed for account id=%s: %s", getattr(acc, "id", "?"), e)

    return {
        "ok": errors == 0,
        "scanned": scanned,
        "errors": errors,
        "dangerous": dangerous_total,
    }
