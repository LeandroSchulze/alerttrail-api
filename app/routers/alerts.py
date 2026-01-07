from fastapi import APIRouter
from pathlib import Path
import json
from datetime import datetime

router = APIRouter(prefix="/alerts", tags=["alerts"])

DATA_DIR = Path("data")
MAIL_SCAN_PATH = DATA_DIR / "scan_last_mails.json"


def _safe_load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_date_ts(v):
    """
    Best-effort timestamp parse. Returns int seconds.
    Supports:
      - epoch seconds/int-like
      - ISO strings
      - RFC2822 (via email.utils in mail router; here we just try ISO)
    """
    if v is None:
        return 0

    # already numeric
    try:
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if s.isdigit():
            return int(s)
    except Exception:
        pass

    # try ISO formats
    try:
        s = str(v).strip()
        # allow trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return 0


def _mail_items_sorted(scan):
    """
    Returns scan items sorted newest-first, with date_ts normalized.
    """
    if not isinstance(scan, dict):
        return []
    items = scan.get("items") or scan.get("mails") or []
    if not isinstance(items, list):
        return []

    norm = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # normalize date_ts if missing
        if "date_ts" not in it:
            it["date_ts"] = _parse_date_ts(it.get("date") or it.get("internalDate") or it.get("received_at"))
        norm.append(it)

    norm.sort(key=lambda x: x.get("date_ts", 0), reverse=True)
    return norm


@router.get("/pending")
def pending_alerts():
    """
    Returns newest suspicious mail alert (danger_level medium/high) if present.
    """
    scan = _safe_load_json(MAIL_SCAN_PATH)
    items = _mail_items_sorted(scan)

    for it in items:
        analysis = it.get("analysis") or {}
        level = (analysis.get("danger_level") or it.get("level") or "").lower()
        if level in ("high", "medium"):
            # shape for frontend toast/notif
            title = "Email sospechoso detectado"
            subj = it.get("subject") or "(sin asunto)"
            sender = it.get("from") or it.get("sender") or "(sin remitente)"
            return {
                "has_alert": True,
                "type": "mail_suspicious",
                "severity": level,
                "title": title,
                "message": f"{subj} — {sender}",
                "data": {
                    "subject": subj,
                    "from": sender,
                    "date": it.get("date"),
                    "date_ts": it.get("date_ts"),
                    "reasons": analysis.get("reasons") or [],
                },
            }

    return {"has_alert": False}


@router.get("/unread-count")
def unread_count():
    """
    Count suspicious mails in last scan (medium/high).
    Used for badge in UI.
    """
    scan = _safe_load_json(MAIL_SCAN_PATH)
    items = _mail_items_sorted(scan)

    cnt = 0
    for it in items:
        analysis = it.get("analysis") or {}
        level = (analysis.get("danger_level") or it.get("level") or "").lower()
        if level in ("high", "medium"):
            cnt += 1

    return {"count": cnt}
