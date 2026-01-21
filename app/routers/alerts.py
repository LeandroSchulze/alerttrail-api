from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.security import get_current_user_cookie
from app.ui import templates

# ✅ PUSH
from app.routers.push import _load as _load_push
from app.utils.webpush import send_web_push

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

ALERTS_STATE_FILE = MAIL_DATA_DIR / "alerts_state.json"


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))


def _safe_get_user(request: Request):
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None


def _user_id(user: Dict[str, Any]) -> str:
    return str(user.get("id") or user.get("email"))


def _scan_file_for(user):
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"


def _parse_date_ts(v: str) -> int:
    try:
        dt = parsedate_to_datetime(v)
        return int(dt.timestamp())
    except Exception:
        return 0


def _extract_level(item):
    analysis = item.get("analysis") or {}
    return (analysis.get("danger_level") or item.get("level") or "low").lower()


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    return templates.TemplateResponse("alerts.html", {"request": request})


@router.get("/pending", include_in_schema=False)
def alerts_pending(request: Request):
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "pending": False})

    scan = _load_json(_scan_file_for(user), {})
    items = scan.get("items") or []

    state = _load_json(ALERTS_STATE_FILE, {})
    uid = _user_id(user)
    last_id = state.get(uid, {}).get("last_delivered_id")

    for it in sorted(items, key=lambda x: _parse_date_ts(x.get("date", "")), reverse=True):
        level = _extract_level(it)
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id"))
        if mail_id == last_id:
            break

        alert = {
            "id": mail_id,
            "title": "⚠️ Security Alert",
            "body": f"{it.get('subject')}\nFrom: {it.get('from')}",
            "severity": level,
        }

        # ✅ PUSH REAL
        subs = _load_push().get(uid, [])
        for sub in subs:
            send_web_push(sub, alert)

        state.setdefault(uid, {})["last_delivered_id"] = mail_id
        _save_json(ALERTS_STATE_FILE, state)

        return JSONResponse({"ok": True, "pending": True, "alert": alert})

    return JSONResponse({"ok": True, "pending": False})
