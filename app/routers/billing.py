from __future__ import annotations
import os, uuid, requests
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import PaymentHistory, User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICE_CENTS = int(os.getenv("PLAN_PRICE_CENTS", "1000"))  # USD 10 por defecto
PLAN_CURRENCY = os.getenv("PLAN_CURRENCY", "USD").upper()
REQ_TIMEOUT = int(os.getenv("MP_REQ_TIMEOUT_SEC", "25"))

def _list_user_payments(db: Session, user_id: int, show_all: bool) -> List[PaymentHistory]:
    q = db.query(PaymentHistory).filter(PaymentHistory.user_id == user_id).order_by(desc(PaymentHistory.created_at))
    if not show_all:
        q = q.limit(20)
    return q.all()

@router.get("", response_class=HTMLResponse, name="billing_page")
def billing_page(request: Request, db: Session = Depends(get_db), all: int = Query(0)):
    """Renderiza tu template billing.html con la lista de pagos del usuario."""
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    payments = _list_user_payments(db, user.id, show_all=bool(all))
    ctx_payments: List[Dict[str, Any]] = [
        {
            "created_at": p.created_at,
            "provider": p.provider,
            "amount": round((p.amount_cents or 0) / 100.0, 2),
            "currency": (p.currency or "USD").upper(),
            "status": p.status,
        }
        for p in payments
    ]
    return request.app.state.templates.TemplateResponse(
        "billing.html",
        {"request": request, "payments": ctx_payments},
    )

@router.get("/payments", name="billing_payments")
def billing_payments(request: Request, db: Session = Depends(get_db), all: int = Query(0)):
    """Endpoint JSON que usan tus links url_for('billing_payments')."""
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    rows = _list_user_payments(db, user.id, show_all=bool(all))
    return {
        "ok": True,
        "items": [{
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "provider": r.provider,
            "amount": round((r.amount_cents or 0) / 100.0, 2),
            "currency": (r.currency or "USD").upper(),
            "status": r.status,
            "payment_id": r.payment_id,
        } for r in rows]
    }

@router.post("/checkout/mp")
def create_mp_checkout(request: Request, db: Session = Depends(get_db)):
    """Crea una preferencia de MP y devuelve init_point (no modifica tu template)."""
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    access_token = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
    if not access_token:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado")

    notification_url = (os.getenv("MP_WEBHOOK_URL") or "").strip()
    if not notification_url:
        # Usa tu propia ruta si no seteaste MP_WEBHOOK_URL
        try:
            notification_url = str(request.url_for("payments_mp_webhook")).replace("http://", "https://")
        except Exception:
            raise HTTPException(status_code=500, detail="Configura MP_WEBHOOK_URL o monta correctamente el webhook")

    preference = {
        "items": [{
            "title": "AlertTrail PRO (1 mes)",
            "quantity": 1,
            "currency_id": PLAN_CURRENCY,
            "unit_price": round(PLAN_PRICE_CENTS / 100.0, 2),
        }],
        "payer": {"email": user.email},
        "external_reference": f"user:{user.id}|plan:PRO|period:monthly|origin:billing|req:{uuid.uuid4()}",
        "back_urls": {
            "success": str(request.url_for("billing_page")),
            "pending": str(request.url_for("billing_page")),
            "failure": str(request.url_for("billing_page")),
        },
        "auto_return": "approved",
        "binary_mode": True,
        "statement_descriptor": "ALERTTRAIL",
        "notification_url": notification_url,
    }

    r = requests.post(
        "https://api.mercadopago.com/checkout/preferences",
        json=preference,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQ_TIMEOUT,
    )
    data = r.json()
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"MP error {r.status_code}: {data}")
    return {"ok": True, "init_point": data.get("init_point"), "id": data.get("id")}

# Alias rápido para evitar 404 hoy
@router.get("/subscriptions", include_in_schema=False)
def billing_subscriptions_alias():
    return RedirectResponse(url="/billing", status_code=302)
