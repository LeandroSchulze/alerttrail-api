# app/routers/billing.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

def _months_to_days(m: int) -> int:
    return 30 * max(m, 1)

@router.get("/preview", response_class=JSONResponse)
def billing_preview(plan: str = Query("PRO"), months: int = Query(1, ge=1, le=12),
                    user=Depends(get_current_user_cookie)):
    now = datetime.now(timezone.utc)
    exp = getattr(user, "pro_expires_at", None)
    base = exp if (exp and isinstance(exp, datetime) and exp > now) else now
    new_exp = base + timedelta(days=_months_to_days(months))
    return {"ok": True, "plan": plan.upper(), "months": months,
            "current_expires_at": exp.isoformat() if exp else None,
            "new_expires_at": new_exp.isoformat()}

