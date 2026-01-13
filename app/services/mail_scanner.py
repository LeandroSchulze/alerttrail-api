from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from email.utils import parsedate_to_datetime

from app.services.mail_scan import scan_mailbox

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _verdict_from_level(level: str) -> str:
    lvl = (level or "low").lower()
    if lvl == "high":
        return "ALTO"
    if lvl == "medium":
        return "MEDIO"
    return "BAJO"


def _safe_date_ts(v: str) -> int:
    """
    Convierte Date del mail a timestamp estable.
    NUNCA rompe el orden.
    """
    try:
        dt = parsedate_to_datetime(v)
        if dt is None:
            return 0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def scan_all_connected_mailboxes(
    db=None,
    limit: int | None = None,
    dry_run: bool = False,
    **kwargs
) -> int:
    """
    Llamado por /tasks/mail/poll
    Escanea TODAS las casillas y guarda scan_last_<user>.json
    """

    all_linked: Dict[str, Any] = _load_json(LINKED_FILE, {}) or {}
    if not isinstance(all_linked, dict):
        all_linked = {}

    lim = int(limit or 50)
    scanned = 0

    for user_id, linked in all_linked.items():
        if not isinstance(linked, dict):
            continue

        scanned += 1
        try:
            res = scan_mailbox(
                host=linked.get("host") or "imap.gmail.com",
                port=int(linked.get("port") or 993),
                username=linked.get("username") or "",
                password=linked.get("password") or "",
                folder=linked.get("folder") or "INBOX",
                use_ssl=bool(linked.get("use_ssl", True)),
                limit=lim,
                mark_read=bool(linked.get("mark_read", False)),  # 👈 NO marca leídos
            )

            items = []
            for it in (res.items or []):
                analysis = getattr(it, "analysis", None)
                danger_level = str(getattr(analysis, "danger_level", "") or "low").lower()
                reasons = list(getattr(analysis, "reasons", []) or [])

                date_str = str(it.date or "")
                items.append(
                    {
                        "uid": str(it.uid or ""),
                        "subject": str(it.subject or ""),
                        "from": str(it.from_email or ""),
                        "date": date_str,
                        "date_ts": _safe_date_ts(date_str),
                        "verdict": _verdict_from_level(danger_level),
                        "reasons": reasons,
                    }
                )

            # 🔽 CLAVE: ordenar SIEMPRE por fecha (más nuevo primero)
            items.sort(key=lambda x: int(x.get("date_ts") or 0), reverse=True)

            payload = {
                "ok": bool(res.ok),
                "scanned_at": _now_iso(),
                "folder": linked.get("folder") or "INBOX",
                "address": linked.get("address") or linked.get("username") or "",
                "total": int(res.total_found or 0),
                "unread": int(res.unread or 0),
                "items": items,
                "error": (res.message or "") if not res.ok else None,
                "limit": lim,
            }

            if not dry_run:
                _save_json(MAIL_DATA_DIR / f"scan_last_{user_id}.json", payload)

        except Exception as e:
            if not dry_run:
                _save_json(
                    MAIL_DATA_DIR / f"scan_last_{user_id}.json",
                    {
                        "ok": False,
                        "scanned_at": _now_iso(),
                        "error": str(e),
                        "items": [],
                        "limit": lim,
                    },
                )

    return scanned
