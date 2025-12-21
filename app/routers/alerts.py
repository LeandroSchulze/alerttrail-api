# app/routers/alerts.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.ui import templates
from app.i18n import get_lang_from_request, t
from app.security import get_current_user_cookie

# DB (optional for pending alerts)
from app.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(tags=["alerts"])


def _user_id_from_any(user: Any) -> Optional[int]:
    """
    Tries to extract a numeric user id from whatever get_current_user_cookie returns
    (dict payload, ORM model, etc.). Returns None if not possible.
    """
    if user is None:
        return None
    if isinstance(user, dict):
        # some setups store id under "id"; others store subject in "sub"
        if user.get("id") is not None:
            try:
                return int(user["id"])
            except Exception:
                return None
        if user.get("sub") is not None:
            try:
                return int(user["sub"])
            except Exception:
                return None
        return None
    # ORM-like object
    for key in ("id", "user_id"):
        if hasattr(user, key):
            try:
                return int(getattr(user, key))
            except Exception:
                return None
    return None


def _is_pro_user(user: Any) -> bool:
    """
    Conservative PRO check. If we can't determine, we return False (safe default).
    """
    if user is None:
        return False
    if isinstance(user, dict):
        plan = (user.get("plan") or "").upper()
        return plan == "PRO"
    plan = getattr(user, "plan", None) or getattr(user, "tier", None) or ""
    return str(plan).upper() == "PRO"


@router.get("/alerts", response_class=HTMLResponse, include_in_schema=False)
def alerts_page(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang_from_request(request)
    # keep template params minimal and safe
    return templates.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
        },
    )


@router.get("/alerts/pending", include_in_schema=False)
def alerts_pending(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """
    Endpoint polled by the UI to check if there are pending desktop alerts.
    If the PRO alert queue model isn't present, or user isn't PRO, returns empty.
    """
    # If not PRO, don't break the UI; just return empty.
    if not _is_pro_user(user):
        return {"count": 0, "items": []}

    user_id = _user_id_from_any(user)
    if not user_id:
        return {"count": 0, "items": []}

    # Import lazily so we don't break startup if the file/model isn't present.
    try:
        from app.models_pro_alerts import ProAlertQueue  # type: ignore
    except Exception:
        return {"count": 0, "items": []}

    try:
        rows = (
            db.query(ProAlertQueue)
            .filter(ProAlertQueue.user_id == user_id)
            .order_by(ProAlertQueue.created_at.desc())
            .limit(10)
            .all()
        )

        items: List[Dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "id": getattr(r, "id", None),
                    "title": getattr(r, "title", "") or "",
                    "body": getattr(r, "body", "") or "",
                    "url": getattr(r, "url", None),
                    "created_at": getattr(r, "created_at", None).isoformat()
                    if getattr(r, "created_at", None)
                    else None,
                }
            )

        return {"count": len(items), "items": items}
    except Exception:
        # Never break the dashboard polling
        return {"count": 0, "items": []}
