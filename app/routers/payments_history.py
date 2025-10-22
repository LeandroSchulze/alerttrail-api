# app/routers/payments_history.py
from __future__ import annotations

from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentHistory, User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(get_current_user_cookie)]

def _safe_currency(code: Optional[str]) -> str:
    if not code:
        return "USD"
    return str(code).upper()

def _discover_pro_expiry(user: User) -> Optional[datetime]:
    for candidate in ("pro_expires_at", "plan_pro_expires_at", "pro_until", "pro_expiry"):
        if hasattr(user, candidate):
            return getattr(user, candidate)
    return None

@router.get("/me", response_model=None)
def my_billing_status(
    user: UserDep,
):
    now = datetime.now(timezone.utc)
    pro_expiry = _discover_pro_expiry(user)
    is_pro = bool(pro_expiry and pro_expiry > now)
    remaining_days = None
    remaining_hours = None
    if pro_expiry:
        delta = pro_expiry - now
        remaining_days = max(0, int(delta.total_seconds() // 86400))
        remaining_hours = max(0, int((delta.total_seconds() % 86400) // 3600))

    return {
        "ok": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": getattr(user, "name", user.email),
        },
        "plan": getattr(user, "plan", "FREE") or "FREE",
        "is_pro": is_pro,
        "pro_expires_at": pro_expiry.isoformat() if pro_expiry else None,
        "remaining_days": remaining_days,
        "remaining_hours": remaining_hours,
    }

@router.get("/history", response_model=None)
def my_payment_history(
    db: DbDep,
    user: UserDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = (
        db.query(PaymentHistory)
        .filter(PaymentHistory.user_id == user.id)
        .order_by(PaymentHistory.created_at.desc())
    )
    items: List[PaymentHistory] = q.offset(offset).limit(limit).all()
    result: List[Dict[str, Any]] = []
    for r in items:
        result.append(
            {
                "payment_id": r.payment_id,
                "provider": r.provider,
                "status": r.status,
                "amount_cents": int(r.amount_cents or 0),
                "currency": _safe_currency(r.currency),
                "description": r.description,
                "plan": r.plan,
                "period": r.period,
                "external_reference": r.external_reference,
                "payer_email": r.payer_email,
                "origin": r.origin,
                "created_at": (r.created_at or datetime.now(timezone.utc)).isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
        )
    return {"ok": True, "count": len(result), "items": result}

