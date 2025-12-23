# app/plan_guard.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.security import get_current_user_cookie
from app.database import get_db
from app.models import User


USAGE_DIR = Path(os.getenv("USAGE_DIR", "/var/data/usage"))
USAGE_DIR.mkdir(parents=True, exist_ok=True)

LOG_SCANS_FILE = USAGE_DIR / "log_scans_weekly.json"

FREE_LOG_SCANS_PER_WEEK = int(os.getenv("FREE_LOG_SCANS_PER_WEEK", "5"))


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


def _monday_utc_key(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.date().isoformat()


@dataclass
class CurrentUser:
    id: int
    email: str
    role: str
    plan: str
    is_pro: bool


def get_current_user_db(request: Request) -> CurrentUser:
    """
    JWT cookie -> DB user (source of truth).
    """
    payload = get_current_user_cookie(request)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    try:
        uid = int(str(sub))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    with next(get_db()) as db:
        user = db.get(User, uid)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    role = (user.role or "").lower()
    plan = (user.plan or "FREE").upper()

    is_admin = role == "admin"
    if is_admin:
        plan = "PRO"

    is_pro = plan == "PRO" or is_admin

    return CurrentUser(
        id=user.id,
        email=user.email,
        role=role,
        plan=plan,
        is_pro=is_pro,
    )


def require_pro(request: Request) -> CurrentUser:
    """
    Para templates que SOLO PRO/ADMIN pueden ver.
    """
    cu = get_current_user_db(request)
    if not cu.is_pro:
        # UI friendly: redirigimos al dashboard con query
        raise HTTPException(status_code=403, detail="PRO_REQUIRED")
    return cu


def enforce_free_log_scans_limit(request: Request) -> None:
    """
    FREE: máx N scans por semana.
    PRO/ADMIN: ilimitado.
    """
    cu = get_current_user_db(request)
    if cu.is_pro:
        return

    key = _monday_utc_key()
    data = _load_json(LOG_SCANS_FILE, {}) or {}
    user_bucket = data.get(str(cu.id), {}) or {}
    used = int(user_bucket.get(key, 0) or 0)

    if used >= FREE_LOG_SCANS_PER_WEEK:
        raise HTTPException(
            status_code=429,
            detail=f"LIMIT_REACHED: free plan allows {FREE_LOG_SCANS_PER_WEEK}/week",
        )

    user_bucket[key] = used + 1
    data[str(cu.id)] = user_bucket
    _save_json(LOG_SCANS_FILE, data)
