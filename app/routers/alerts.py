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


def _extract_level_and_reasons(item: Dict[str, Any]) -> Tuple[str, list]:
    """
    Normaliza diferentes formatos de items:
      - Nuevo: item['analysis']['danger_level'] + item['analysis']['reasons']
      - Legacy: item['level'] + item['reasons']
    """
    analysis = item.get("analysis") or {}
    level = (analysis.get("danger_level") or item.get("level") or "").strip().lower()
    reasons = analysis.get("reasons") or item.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = []
    return level, reasons


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    return templates.TemplateResponse("alerts.html", {"request": request})


@router.get("/unread-count", include_in_schema=False)
def unread_count(request: Request):
    """
    Para el FAB del base.html.
    Devuelve cantidad de alertas 'pendientes' (medium/high) no entregadas aún.
    """
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "count": 0})

    scan = _load_json(_scan_file_for(user), {}) or {}
    items = scan.get("items") or []
    if not isinstance(items, list):
        items = []

    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid_key = _user_id(user)
    user_state = state.get(uid_key) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        level, _reasons = _extract_level_and_reasons(it)
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue

        if last_delivered and mail_id == last_delivered:
            break

        count += 1

    return JSONResponse({"ok": True, "count": count})


@router.get("/pending", include_in_schema=False)
def alerts_pending(request: Request):
    """
    Polling por JS:
      GET /alerts/pending

    Respuesta:
      { ok: true, pending: false }
      o
      { ok: true, pending: true, alert: { id, title, body, severity } }
    """
    user = _safe_get_user(request)
    if not user:
        return JSONResponse({"ok": True, "pending": False})

    scan = _load_json(_scan_file_for(user), {}) or {}
    items = scan.get("items") or []
    if not isinstance(items, list):
        items = []

    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid_key = _user_id(user)
    user_state = state.get(uid_key) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    # buscamos el más reciente (asumimos que items viene newest-first o, mínimo, append newest al final)
    candidate = None
    for it in reversed(items):
        if not isinstance(it, dict):
            continue

        level, reasons = _extract_level_and_reasons(it)
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue

        if last_delivered and mail_id == last_delivered:
            break

        candidate = (mail_id, it, level, reasons)
        break

    if not candidate:
        return JSONResponse({"ok": True, "pending": False})

    mail_id, it, level, reasons = candidate

    subj = str(it.get("subject") or "(sin asunto)")
    frm = str(it.get("from") or it.get("from_email") or "")
    reason_txt = (reasons[0] if reasons else "Se detectaron señales de riesgo en el correo.")

    alert_obj = {
        "id": mail_id,
        "title": "⚠️ Alerta de seguridad" if level == "high" else "🔔 Posible phishing",
        "body": f"{subj}\nDe: {frm}\nMotivo: {reason_txt}",
        "severity": "high" if level == "high" else "medium",
    }

    # marcar como entregado
    state.setdefault(uid_key, {})
    state[uid_key]["last_delivered_id"] = mail_id
    _save_json(ALERTS_STATE_FILE, state)

    return JSONResponse({"ok": True, "pending": True, "alert": alert_obj})
