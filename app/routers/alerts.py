# app/routers/alerts.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.security import get_current_user_cookie
from app.ui import templates

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Persistencia en disco (Render Disk)
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
    """
    Devuelve el user si hay cookie JWT válida.
    Si no hay / expiró / falla decode: devuelve None (sin tirar 401).
    Esto es CLAVE para que el polling /alerts/pending no rompa la UI.
    """
    try:
        return get_current_user_cookie(request)
    except Exception:
        return None


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request):
    # Página simple si la usás (no afecta el polling)
    return templates.TemplateResponse("alerts.html", {"request": request})


@router.get("/pending", include_in_schema=False)
def alerts_pending(request: Request):
    """
    Endpoint que el frontend hace polling cada X segundos:
      GET /alerts/pending

    Respuesta esperada por alert_clients.js:
      { ok: true, pending: false }
      o
      { ok: true, pending: true, alert: { id, title, body, severity } }
    """
    user = _safe_get_user(request)
    if not user:
        # ✅ NO 401: el dashboard puede estar abierto sin sesión todavía
        return JSONResponse({"ok": True, "pending": False})

    scan_path = _scan_file_for(user)
    scan = _load_json(scan_path, {}) or {}
    items = scan.get("items") or []

    # Estado de alerts entregados
    state = _load_json(ALERTS_STATE_FILE, {}) or {}
    uid_key = _user_id(user)
    user_state = state.get(uid_key) or {}
    last_delivered = str(user_state.get("last_delivered_id") or "")

    # Buscamos el mail más reciente con riesgo MEDIUM/HIGH
    # y que no haya sido entregado aún.
    candidate = None
    for it in reversed(items):
        analysis = it.get("analysis") or {}
        level = (analysis.get("danger_level") or "").lower()
        if level not in ("medium", "high"):
            continue

        mail_id = str(it.get("uid") or it.get("id") or "")
        if not mail_id:
            continue

        # si coincide con el último entregado, cortamos
        if last_delivered and mail_id == last_delivered:
            break

        candidate = (mail_id, it, level)
        break

    if not candidate:
        return JSONResponse({"ok": True, "pending": False})

    mail_id, it, level = candidate

    subj = str(it.get("subject") or "(sin asunto)")
    frm = str(it.get("from") or it.get("from_email") or "")
    reasons = (it.get("analysis") or {}).get("reasons") or []
    reason_txt = reasons[0] if reasons else "Se detectaron señales de riesgo en el correo."

    alert_obj = {
        "id": mail_id,
        "title": "⚠️ Alerta de seguridad" if level == "high" else "🔔 Posible phishing",
        "body": f"{subj}\nDe: {frm}\nMotivo: {reason_txt}",
        "severity": "high" if level == "high" else "medium",
    }

    # ✅ Marcamos como “entregado” para no repetirlo en cada poll
    state.setdefault(uid_key, {})
    state[uid_key]["last_delivered_id"] = mail_id
    _save_json(ALERTS_STATE_FILE, state)

    return JSONResponse({"ok": True, "pending": True, "alert": alert_obj})
