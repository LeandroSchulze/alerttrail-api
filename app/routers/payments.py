# app/routers/payments.py
import os
import json
import uuid
import requests
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..security import get_current_user_cookie
from ..models import User, Organization, PaymentHistory  # <-- Importamos modelos necesarios

router = APIRouter()
log = logging.getLogger(__name__)

# ====== Config / Env ======
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
REQ_TIMEOUT = int(os.getenv("MP_REQ_TIMEOUT_SEC", "25"))
MP_MIN_AMOUNT_USD = float(os.getenv("MP_MIN_AMOUNT_USD", "15"))

def _require_mp_token():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado")

def _mp_headers():
    return {"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"}

# -------------------------
# User helpers (dict or ORM)
# -------------------------
def _user_get(user, key: str, default=None):
    if user is None: return default
    if isinstance(user, dict): return user.get(key, default)
    return getattr(user, key, default)

def _user_id(user) -> Optional[int]:
    uid = _user_get(user, "id") or _user_get(user, "sub")
    try: return int(str(uid)) if uid else None
    except: return None

def _user_email(user) -> Optional[str]:
    email = _user_get(user, "email")
    return str(email).strip() if email else None

# ====== Precio / moneda ======
def _amount_currency(plan: str, seats: int) -> Tuple[float, str]:
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper().strip()
    pro_price = float(os.getenv("PLAN_PRICE") or 9.99)
    
    # BIZ (25 asientos por defecto)
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

# ====== Modelo local de suscripción (Sincronizado) ======
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint, Numeric
from sqlalchemy.orm import declarative_base

SubBase = declarative_base()
_engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

class Subscription(SubBase):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("preapproval_id", name="uq_preapproval_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    preapproval_id = Column(String, unique=True, index=True)
    status = Column(String) # authorized/paused/cancelled
    plan = Column(String)
    seats = Column(Integer, default=1)
    currency = Column(String, default="USD")
    amount = Column(Numeric(10, 2))
    next_payment_date = Column(String)
    external_reference = Column(String, index=True)
    raw = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

try: SubBase.metadata.create_all(_engine)
except: pass

# -------------------------
# LÓGICA DE ACTIVACIÓN (Aquí se crean los 25 asientos)
# -------------------------
def _activate_plan(db: Session, user_id: int, plan: str, seats: int, expiry: Optional[datetime] = None):
    u = db.get(User, user_id)
    if not u: return
    
    plan_norm = plan.upper()
    u.plan = plan_norm
    u.is_pro = True
    if expiry: u.pro_expires_at = expiry
    else: u.pro_expires_at = datetime.utcnow() + timedelta(days=30)

    # Si es plan BIZ, creamos/actualizamos la Organización con sus 25 asientos
    if plan_norm == "BIZ":
        org = db.query(Organization).filter(Organization.owner_user_id == u.id).first()
        if not org:
            org = Organization(
                name=f"Empresa de {u.name or u.email}",
                owner_user_id=u.id,
                plan="BIZ",
                seats_total=max(seats, 25), # Forzamos el mínimo de 25
                seats_used=1
            )
            db.add(org)
            db.flush()
        u.org_id = org.id
        u.is_org_admin = True
    
    db.commit()
    log.info(f"Plan {plan_norm} activado para usuario {user_id} ({seats} asientos)")

# ====== WEBHOOK UNIFICADO ======
@router.post("/payments/webhook")
async def payments_webhook(request: Request, db: Session = Depends(get_db)):
    _require_mp_token()
    try:
        body = await request.json()
    except: return JSONResponse({"ok": False}, status_code=200)

    topic = body.get("topic") or body.get("type")
    resource_id = body.get("data", {}).get("id") or body.get("id")

    if not resource_id: return JSONResponse({"ok": True}, status_code=200)

    # CASO 1: Pago Único (Checkout)
    if topic in ("payment", "payment.updated"):
        url = f"https://api.mercadopago.com/v1/payments/{resource_id}"
        r = requests.get(url, headers=_mp_headers())
        if r.status_code == 200:
            pdata = r.json()
            if pdata.get("status") == "approved":
                ext_ref = pdata.get("external_reference") or ""
                # Parsear: user:1:plan:BIZ:seats:25:...
                try:
                    parts = ext_ref.split(":")
                    uid = int(parts[1])
                    plan = parts[3]
                    seats = int(parts[5])
                    _activate_plan(db, uid, plan, seats)
                except: log.error(f"Error parseando external_ref: {ext_ref}")

    # CASO 2: Suscripción (Preapproval)
    elif topic in ("preapproval", "subscription"):
        res = _sync_preapproval(db, preapproval_id=resource_id)
        # _sync_preapproval ya llama a _activate_user_plan_if_authorized internamente

    return JSONResponse({"ok": True})

# --- Mantener el resto de tus funciones auxiliares (_sync_preapproval, etc) ---
# ... (Copiar de tu archivo original las funciones _mp_create_preference, _mp_get_preapproval, etc.) ...

# Reemplaza tu _activate_user_plan_if_authorized original por esta para incluir la lógica de Org:
def _activate_user_plan_if_authorized(db: Session, *, sub: Subscription):
    if (sub.status or "").lower() == "authorized" and sub.user_id:
        expiry = None
        if sub.next_payment_date:
            try: expiry = datetime.fromisoformat(sub.next_payment_date.replace("Z", "+00:00"))
            except: pass
        _activate_plan(db, sub.user_id, sub.plan, sub.seats, expiry)

# ... (Copiar tus endpoints de /payments/pay y /payments/subscribe del archivo anterior) ...
