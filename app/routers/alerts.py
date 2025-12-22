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
    if not user:
        return "anon"
    for k in ("sub", "id", "user_id", "email"):
        v = user.get(k)
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

def _normalize_level(item: Dict[str, Any]) -> Tuple[str, int, str]:
    """
    Devuelve (level_low|medium|high, score, reason_text)
    Compatible con:
      - item["analysis"]["danger_level"]
      - item["verdict"] (ALTO/MEDIO/BAJO)
      - item["level"]   (HIGH/MEDIUM/LOW)
    """
    analysis = item.get("analysis") or {}
    dl = str(analysis.get("danger_level") or "").lower().strip()

    verdict = str(item.get("verdict") or "").upper().strip()
    lvl = str(item.get("level") or "").upper().strip()

    score = 0
    try:
        score = int(analysis.get("risk_score") or item.get("score") or 0)
    except Exception:
        score = 0

    reasons = analysis.get("reasons") or item.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        reason_txt = str(reasons[0])
    else:
        reason_txt = "Se detectaron señales de riesgo en el correo."

    if dl in ("high", "alto"):
        return "high", score, reason_txt
    if dl in ("medium", "medio"):
        return "medium", score, reason_txt
    if dl in ("low", "bajo"):
        return "low", score, reason_txt

    if verdict == "ALTO" or lvl == "HIGH":
        return "high", score, reason_txt
    if verdict == "MEDIO" or lvl == "MEDIUM":
        return "medium", score, reason_txt
    return "low", score, reason_txt

@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    return templates.TemplateResponse("alerts.html", {"request": request})

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
    for it in items:
        level, _, _ = _normalize_level(it)
        if level not in ("medium", "high"):
            continue
        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue
        if last_delivered and mail_id == last_delivered:
            continue
        count += 1

    return JSONResponse({"ok": True, "count": count})

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

    candidate = None

    # buscamos lo más reciente con medium/high
    for it in reversed(items):
        level, _, reason_txt = _normalize_level(it)
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue

        if last_delivered and mail_id == last_delivered:
            break

        candidate = (mail_id, it, level, reason_txt)
        break

    if not candidate:
        return JSONResponse({"ok": True, "pending": False})

    mail_id, it, level, reason_txt = candidate

    subj = str(it.get("subject") or "(sin asunto)")
    frm = str(it.get("from") or it.get("from_email") or "")

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
