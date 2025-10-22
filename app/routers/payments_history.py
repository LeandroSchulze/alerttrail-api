# app/routers/payments_history.py
from __future__ import annotations

from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentHistory, User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

def _safe_currency(code: Optional[str]) -> str:
    if not code:
        return "USD"
    return str(code).upper()

@router.get("/history")
def my_payment_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = (
        db.query(PaymentHistory)
        .filter(PaymentHistory.user_id == user.id)
        .order_by(PaymentHistory.created_at.desc())
    )
    items: List[PaymentHistory] = q.offset(offset).limit(limit).all()
    result = []
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
