# app/routers/admin_payments.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, and_

from app.database import get_db
from app.models import User, PaymentHistory
from app.guards import require_admin  # <- FIX: antes apuntaba a app.deps.admin_guard

router = APIRouter(prefix="/admin/payments", tags=["admin-payments"])

def _discover_pro_expiry_attr() -> str:
    return "pro_expires_at"

def _now_utc():
    return datetime.now(timezone.utc)

@router.get("", response_class=HTMLResponse, response_model=None)
def admin_payments_page(request: Request, admin = Depends(require_admin)):
    return request.app.state.templates.TemplateResponse(
        "admin_payments.html",
        {"request": request, "page_title": "Pagos | Admin"},
    )

@router.get("/metrics", response_model=None)
def payments_metrics(
    db = Depends(get_db),
    admin = Depends(require_admin),
):
    now = _now_utc()
    days_30 = now - timedelta(days=30)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = db.query(func.count(User.id)).scalar() or 0

    pro_attr = _discover_pro_expiry_attr()
    pro_active = db.query(func.count(User.id)).filter(getattr(User, pro_attr) > now).scalar() or 0

    pro_expiring_7d = db.query(func.count(User.id)).filter(
        and_(getattr(User, pro_attr) > now, getattr(User, pro_attr) <= now + timedelta(days=7))
    ).scalar() or 0

    rev_30d_rows = (
        db.query(
            PaymentHistory.currency.label("currency"),
            func.sum(PaymentHistory.amount_cents).label("sum_cents"),
            func.count(PaymentHistory.id).label("count_payments"),
        )
        .filter(
            PaymentHistory.status.in_(["approved", "authorized"]),
            PaymentHistory.created_at >= days_30,
        )
        .group_by(PaymentHistory.currency)
        .all()
    )
    revenue_30d = [
        {"currency": (r.currency or "USD").upper(), "amount_cents": int(r.sum_cents or 0), "count": int(r.count_payments or 0)}
        for r in rev_30d_rows
    ]

    rev_today_rows = (
        db.query(
            PaymentHistory.currency.label("currency"),
            func.sum(PaymentHistory.amount_cents).label("sum_cents"),
        )
        .filter(
            PaymentHistory.status.in_(["approved", "authorized"]),
            PaymentHistory.created_at >= today_start,
        )
        .group_by(PaymentHistory.currency)
        .all()
    )
    revenue_today = [
        {"currency": (r.currency or "USD").upper(), "amount_cents": int(r.sum_cents or 0)}
        for r in rev_today_rows
    ]

    arpu_30d_usd = None
    usd_row = next((x for x in revenue_30d if x["currency"] == "USD"), None)
    if total_users > 0 and usd_row:
        arpu_30d_usd = round((usd_row["amount_cents"] / 100.0) / total_users, 2)

    return {
        "ok": True,
        "totals": {
            "total_users": total_users,
            "pro_active": pro_active,
            "pro_expiring_7d": pro_expiring_7d,
        },
        "revenue": {
            "last_30d": revenue_30d,
            "today": revenue_today,
            "arpu_30d_usd": arpu_30d_usd,
        },
    }

@router.get("/list", response_model=None)
def payments_list(
    db = Depends(get_db),
    admin = Depends(require_admin),
    email: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="approved|authorized|pending|rejected|refunded|cancelled"),
    provider: Optional[str] = Query(None, description="mercado_pago|internal|stripe|..."),
    date_from: Optional[str] = Query(None, description="ISO date or YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date or YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(PaymentHistory)

    if email:
        q = q.filter(func.lower(PaymentHistory.payer_email).like(f"%{email.strip().lower()}%"))

    if status:
        q = q.filter(func.lower(PaymentHistory.status) == status.strip().lower())

    if provider:
        q = q.filter(func.lower(PaymentHistory.provider) == provider.strip().lower())

    def _parse_date(s: str):
        try:
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                return datetime.fromisoformat(s + "T00:00:00+00:00")
            return datetime.fromisoformat(s)
        except Exception:
            return None

    if date_from:
        dtf = _parse_date(date_from)
        if dtf:
            q = q.filter(PaymentHistory.created_at >= dtf)
    if date_to:
        dtt = _parse_date(date_to)
        if dtt:
            q = q.filter(PaymentHistory.created_at <= dtt)

    total = q.count()
    rows: List[PaymentHistory] = q.order_by(PaymentHistory.created_at.desc()).offset(offset).limit(limit).all()

    def _row(r: PaymentHistory) -> Dict[str, Any]:
        return {
            "payment_id": r.payment_id,
            "provider": r.provider,
            "status": r.status,
            "amount_cents": int(r.amount_cents or 0),
            "currency": (r.currency or "USD").upper(),
            "description": r.description,
            "plan": r.plan,
            "period": r.period,
            "external_reference": r.external_reference,
            "payer_email": r.payer_email,
            "origin": r.origin,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "user_id": r.user_id,
        }

    return {
        "ok": True,
        "total": total,
        "items": [_row(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }
