# app/services/mail_scanner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime


@dataclass
class MailScannerItem:
    uid: str
    subject: str
    from_email: str
    date: str
    score: int
    reasons: List[str]


@dataclass
class MailScannerResult:
    ok: bool
    message: str
    total_found: int
    unread: int
    dangerous: int
    items: List[MailScannerItem]
    counts: dict
    scanned_at: str


def danger_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def to_scanner_result(res, scanned_at: Optional[datetime] = None) -> MailScannerResult:
    scanned_at = scanned_at or datetime.utcnow()

    items: List[MailScannerItem] = []
    for it in list(getattr(res, "items", []) or []):
        items.append(
            MailScannerItem(
                uid=str(getattr(it, "uid", "") or ""),
                subject=str(getattr(it, "subject", "") or ""),
                from_email=str(getattr(it, "from_email", "") or ""),
                date=str(getattr(it, "date", "") or ""),
                score=int(getattr(it, "score", 0) or 0),
                reasons=list(getattr(it, "reasons", []) or []),
            )
        )

    return MailScannerResult(
        ok=bool(getattr(res, "ok", False)),
        message=str(getattr(res, "message", "") or ""),
        total_found=int(getattr(res, "total_found", 0) or 0),
        unread=int(getattr(res, "unread", 0) or 0),
        dangerous=int(getattr(res, "dangerous", 0) or 0),
        items=items,
        counts=dict(getattr(res, "counts", {}) or {}),
        scanned_at=str(scanned_at),
    )


def scan_all_connected_mailboxes():
    """Compat: main.py / tasks_mail esperan esta función en mail_scanner.py.

    La implementación real hoy vive en app.services.mail.scan_all_inboxes().
    """
    from app.services.mail import scan_all_inboxes

    return scan_all_inboxes()
