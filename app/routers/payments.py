# app/routers/payments.py
import os
import json
import logging
import requests
from typing import Optional, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..security import get_current_user_cookie
from ..models import User, Organization, PaymentHistory

# Definimos el prefijo aquí para que coincida con tus botones (/payments/...)
router = APIRouter(prefix="/payments", tags=["payments"])
log = logging.getLogger(__name__)

# ====== Config / Env ======
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
MP_MIN_AMOUNT_USD = float(os.getenv("MP_MIN_AMOUNT_USD", "15"))
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or "http://localhost:8080").rstrip("/")

def _require_mp_token():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado")

def _mp_headers():
    return {"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"}

# -------------------------
# User helpers
# -------------------------
def _user_get(user, key: str, default=None):
    if user is None: return default
    if isinstance(user, dict): return user.get(key, default)
    return getattr(user, key, default)

def _user_id(user) -> Optional[int]:
    uid = _user_get(user, "id") or _user_get(user, "sub")
    try: return int(str(uid)) if uid else None
    except: return None

# ====== Precio / moneda ======
def _amount_currency(plan: str, seats: int) -> Tuple[float, str]:
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper().strip()
    pro_price = float(os.getenv("PLAN_PRICE") or 15.00)
    biz_base = float(os.getenv("BIZ_PRICE_MONTH_USD") or 99.0)
    biz_extra = float(os.getenv("BIZ_EXTRA_SET_USD") or 3.0)
    included = int(os.getenv("BIZ_INCLUDED_SEATS") or 25)

    plan_norm = (plan or "PRO").upper().strip()
    if plan_norm == "BIZ":
        total_seats = max(int(seats or included), 1)
        extras = max(0, total_seats - included)
        amount = biz_base + (extras * biz_extra)
    else:
        amount = pro_price

    if currency == "USD" and amount < MP_MIN_AMOUNT_USD:
        amount = MP_MIN_AMOUNT_USD
    return (float(amount), currency)

# -------------------------
# ENDPOINT PRINCIPAL: /payments/pay
# -------------------------
@router.get("/pay")
async def pay(plan: str = "PRO", seats: int = 1, user=Depends(get_current_user_cookie)):
    _require_mp_token()
    uid = _user_id(user)
    if not uid:
        return RedirectResponse(url="/auth/login")

    amount, currency = _amount_currency(plan, seats)
    
    # IMPORTANTE: Formato exacto que espera tu Webhook para parsear
    # user:ID:plan:PLAN:seats:CANTIDAD
    ext_ref = f"user:{uid}:plan:{plan.upper()}:seats:{seats}:ts:{int(datetime.now().timestamp())}"

    preference_data = {
        "items": [
            {
                "title": f"AlertTrail - Plan {plan.upper()}",
                "quantity": 1,
                "unit_price": amount,
                "currency_id": currency
            }
        ],
        "back_urls": {
            "success": f"{PUBLIC_BASE_URL}/billing/subscriptions?payment=success",
            "failure": f"{PUBLIC_BASE_URL}/billing/subscriptions?payment=failure",
            "pending": f"{PUBLIC_BASE_URL}/billing/subscriptions?payment=pending"
        },
        "auto_return": "approved",
        "external_reference": ext_ref,
        "notification_url": f"{PUBLIC_BASE_URL}/payments/webhook"
    }

    try:
        r = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers=_mp_headers(),
            json=preference_data,
            timeout=20
        )
        r.raise_for_status()
        res = r.json()
        # Redirigimos al usuario al checkout de Mercado Pago
        return RedirectResponse(url=res["init_point"])
    except Exception as e:
        log.error(f"Error creando preferencia MP: {e}")
        raise HTTPException(status_code=500, detail="Error al conectar con Mercado Pago")

# -------------------------
# LÓGICA DE ACTIVACIÓN
# -------------------------
def _activate_plan(db: Session, user_id: int, plan: str, seats: int, expiry: Optional[datetime] = None):
    u = db.query(User).filter(User.id == user_id).first()
    if not u: return
    
    plan_norm = plan.upper()
    u.plan = plan_norm
    u.is_pro = True
    if expiry: u.pro_expires_at = expiry
    else: u.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    if plan_norm == "BIZ":
        org = db.query(Organization).filter(Organization.owner_user_id == u.id).first()
        if not org:
            org = Organization(
                name=f"Empresa de {u.name or u.email}",
                owner_user_id=u.id,
                plan="BIZ",
                seats_total=max(seats, 25),
                seats_used=1
            )
            db.add(org)
            db.flush()
        else:
            org.seats_total = max(seats, org.seats_total)
        u.org_id = org.id
        u.is_org_admin = True
    
    db.commit()
    log.info(f"✅ Plan {plan_norm} activado para usuario {user_id}")

# ====== WEBHOOK ======
@router.post("/webhook")
async def payments_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        log.info(f"Webhook recibido: {body}")
    except: 
        return JSONResponse({"ok": False}, status_code=200)

    topic = body.get("topic") or body.get("type")
    resource_id = body.get("data", {}).get("id") or body.get("id")

    if topic in ("payment", "payment.updated") and resource_id:
        url = f"https://api.mercadopago.com/v1/payments/{resource_id}"
        r = requests.get(url, headers=_mp_headers())
        if r.status_code == 200:
            pdata = r.json()
            if pdata.get("status") == "approved":
                ext_ref = pdata.get("external_reference") or ""
                try:
                    # Parseo: user:1:plan:BIZ:seats:25:...
                    parts = ext_ref.split(":")
                    uid = int(parts[1])
                    plan = parts[3]
                    seats = int(parts[5])
                    _activate_plan(db, uid, plan, seats)
                except Exception as e: 
                    log.error(f"Error parseando external_ref '{ext_ref}': {e}")

    return JSONResponse({"ok": True})
