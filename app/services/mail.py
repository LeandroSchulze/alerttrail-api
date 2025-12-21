# app/services/mail.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.services.mail_scan import scan_mailbox

logger = logging.getLogger("alerttrail.mailjobs")


MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_all_inboxes() -> Dict[str, Any]:
    """
    Background job: scan every linked account (JSON store) and persist last scan per user.
    Enable via MAIL_CRON_ENABLED=1 and choose interval with MAIL_CRON_MINUTES.
    """
    linked_all = _load_json(LINKED_FILE, {}) or {}
    if not isinstance(linked_all, dict) or not linked_all:
        logger.info("scan_all_inboxes: no linked accounts found")
        return {"ok": True, "linked": 0, "scanned": 0, "errors": 0}

    limit = int(os.getenv("MAIL_SCAN_LIMIT", "25"))
    scanned = 0
    errors = 0

    for user_id, cfg in linked_all.items():
        try:
            if not isinstance(cfg, dict):
                continue

            host = cfg.get("server") or "imap.gmail.com"
            port = int(cfg.get("port") or 993)
            folder = cfg.get("folder") or "INBOX"
            use_ssl = bool(cfg.get("use_ssl", True))
            username = cfg.get("username") or cfg.get("address") or ""
            password = cfg.get("password") or ""

            res = scan_mailbox(
                host=host,
                port=port,
                username=username,
                password=password,
                folder=folder,
                use_ssl=use_ssl,
                limit=limit,
                mark_read=False,
            )

            items = []
            for it in res.items:
                score = int(getattr(it.analysis, "risk_score", 0) or 0)
                level = (getattr(it.analysis, "danger_level", "") or "").upper()
                reasons = getattr(it.analysis, "reasons", []) or []

                verdict = "BAJO"
                if level in ("ALTO", "HIGH"):
                    verdict = "ALTO"
                elif level in ("MEDIO", "MEDIUM"):
                    verdict = "MEDIO"

                items.append(
                    {
                        "from": it.from_email,
                        "subject": it.subject,
                        "date": it.date or "",
                        "score": score,
                        "level": level,
                        "reasons": reasons,
                        "sender": it.from_email or "—",
                        "verdict": verdict,
                    }
                )

            out = {
                "ok": True,
                "scanned_at": datetime.utcnow().isoformat() + "Z",
                "server": host,
                "folder": folder,
                "total": int(res.total_found or 0),
                "items": items,
                "error": None,
                "limit": int(limit),
            }
            _save_json(MAIL_DATA_DIR / f"scan_last_{user_id}.json", out)
            scanned += 1

        except Exception as e:
            errors += 1
            logger.exception("scan_all_inboxes error for user_id=%s: %s", user_id, str(e))

    return {
        "ok": True,
        "linked": len(linked_all),
        "scanned": scanned,
        "errors": errors,
    }
