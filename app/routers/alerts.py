# app/routers/alerts.py
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

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

ALERTS_STATE_FILE = MAIL_DATA_DIR / "alerts_state.json"


# -------------------------
# Helpers
# -------------------------
def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_get_user(request: Request) -> Optional[Dict[str, Any]]:
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None


def _user_id(user: Dict[str, Any]) -> str:
    return str(user.get("id") or user.get("email") or "anon")


def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"


def _parse_date_ts(v: str) -> int:
    s = (v or "").strip()
    if not s:
        return 0
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _level_from_item(item: Dict[str, Any]) -> str:
    analysis = item.get("analysis") or {}
    level = (
        analysis.get("danger_level")
        or item.get("danger_level")
        or item.get("level")
        or ""
    ).strip().lower()

    if level in ("alto", "high"):
        return "high"
    if level in ("medio", "medium"):
        return "medium"
    return "low"


def _items_newest_first(items: list) -> list:
    norm = []
    for it in items:
        if not isinstance(it, dict):
            continue
        it.setdefault("date_ts", _parse_date_ts(str(it.get("date") or "")))
        norm.append(it)

    norm.sort(key=lambda x: int(x.get("date_ts") or 0), reverse=True)
    return norm


# -------------------------
# Routes
# -------------------------
@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    return templates.TemplateResponse(
        "alerts.html",
        {"request": request},
    )


@router.get("/pending", include_in_schema=False)
def alerts_pending(request: Request):
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "pending": False})

    scan = _load_json(_scan_file_for(user), {}) or {}
    items = scan.get("items") or []
    if not isinstance(items, list):
        items = []

    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid = _user_id(user)
    user_state = state.get(uid) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    for it in _items_newest_first(items):
        level = _level_from_item(it)
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue

        if last_delivered and mail_id == last_delivered:
            return JSONResponse({"ok": True, "pending": False})

        alert = {
            "id": mail_id,
            "title": "⚠️ Security alert" if level == "high" else "🔔 Possible phishing",
            "body": f"{it.get('subject')}\nFrom: {it.get('from')}",
            "severity": level,
        }

        state.setdefault(uid, {})
        state[uid]["last_delivered_id"] = mail_id
        _save_json(ALERTS_STATE_FILE, state)

        return JSONResponse(
            {
                "ok": True,
                "pending": True,
                "alert": alert,
            }
        )

    return JSONResponse({"ok": True, "pending": False})
