# app/routers/alerts.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.security import get_current_user_cookie
from app.ui import templates

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

ALERTS_STATE_FILE = MAIL_DATA_DIR / "alerts_state.json"


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


def _user_id(user: Dict[str, Any]) -> str:
    for k in ("sub", "id", "user_id", "email"):
        v = (user or {}).get(k)
        if v:
            return str(v)
    return "unknown"


def _scan_file_for(user: Dict[str, Any]) -> Path:
    return MAIL_DATA_DIR / f"scan_last_{_user_id(user)}.json"


def _safe_get_user(request: Request) -> Optional[Dict[str, Any]]:
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None


def _extract_level(it: Dict[str, Any]) -> str:
    analysis = (it.get("analysis") or {}) if isinstance(it, dict) else {}
    lvl = str(analysis.get("danger_level") or "").lower().strip()
    if not lvl:
        lvl = str(it.get("level") or "").lower().strip()
    if lvl in ("alto", "high"):
        return "high"
    if lvl in ("medio", "medium"):
        return "medium"
    return "low"


def _extract_reasons(it: Dict[str, Any]) -> list:
    analysis = it.get("analysis") or {}
    reasons = analysis.get("reasons")
    if isinstance(reasons, list) and reasons:
        return reasons
    r2 = it.get("reasons")
    if isinstance(r2, list) and r2:
        return r2
    return []


def _extract_id(it: Dict[str, Any]) -> str:
    for k in ("uid", "id", "message_id"):
        v = it.get(k)
        if v:
            return str(v)
    subj = str(it.get("subject") or "")
    date = str(it.get("date") or "")
    return f"{subj}|{date}".strip("|")


def _latest_risky(items: list, last_delivered: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
    for it in reversed(items or []):
        if not isinstance(it, dict):
            continue
        lvl = _extract_level(it)
        if lvl not in ("medium", "high"):
            continue
        mail_id = _extract_id(it)
        if last_delivered and mail_id == last_delivered:
            break
        return mail_id, it, lvl
    return None


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    return templates.TemplateResponse("alerts.html", {"request": request})


@router.get("/pending", include_in_schema=False)
def alerts_pending(request: Request):
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "pending": False})

    scan = _load_json(_scan_file_for(user), {}) or {}
    items = scan.get("items") or []

    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid_key = _user_id(user)
    user_state = state.get(uid_key) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    cand = _latest_risky(items, last_delivered)
    if not cand:
        return JSONResponse({"ok": True, "pending": False})

    mail_id, it, level = cand

    subj = str(it.get("subject") or "(sin asunto)")
    frm = str(it.get("from") or it.get("from_email") or it.get("sender") or "")
    reasons = _extract_reasons(it)
    reason_txt = reasons[0] if reasons else "Se detectaron señales de riesgo en el correo."

    alert_obj = {
        "id": mail_id,
        "title": "⚠️ Alerta de seguridad" if level == "high" else "🔔 Posible phishing",
        "body": f"{subj}\nDe: {frm}\nMotivo: {reason_txt}",
        "severity": "high" if level == "high" else "medium",
    }

    state.setdefault(uid_key, {})
    state[uid_key]["last_delivered_id"] = mail_id
    _save_json(ALERTS_STATE_FILE, state)

    return JSONResponse({"ok": True, "pending": True, "alert": alert_obj})


@router.get("/unread-count", include_in_schema=False)
def unread_count(request: Request):
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "count": 0})

    scan = _load_json(_scan_file_for(user), {}) or {}
    items = scan.get("items") or []

    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid_key = _user_id(user)
    user_state = state.get(uid_key) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    count = 0
    for it in reversed(items or []):
        if not isinstance(it, dict):
            continue
        mail_id = _extract_id(it)
        if last_delivered and mail_id == last_delivered:
            break
        if _extract_level(it) in ("medium", "high"):
            count += 1

    return JSONResponse({"ok": True, "count": count})
