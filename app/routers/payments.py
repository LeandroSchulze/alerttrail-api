# app/routers/payments.py
import os, json, requests
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import get_current_user_cookie

router = APIRouter(tags=["payments"])\n\nfrom sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
from ..database import SessionLocal
from datetime import datetime

SubBase = declarative_base()
_sub_engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

class Subscription(SubBase):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    preapproval_id = Column(String, unique=True, index=True)
    plan = Column(String)
    seats = Column(Integer)
    status = Column(String)  # authorized/paused/cancelled/pending
    next_payment_date = Column(String)
    raw = Column(Text)       # raw json from MP
    updated_at = Column(DateTime, default=datetime.utcnow)

try:
    SubBase.metadata.create_all(bind=_sub_engine)
except Exception as _e:
    print("[payments] aviso creando tabla subscriptions:", _e)


# ====== ENV ======
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN", "").strip()
BASE_URL = (os.getenv("BASE_URL") or "https://www.alerttrail.com").rstrip("/")
WEBHOOK_SECRET = os.getenv("MAIL_CRON_SECRET", "secret")

PLAN_CURRENCY = (os.getenv("PLAN_CURRENCY") or "USD").upper()
PRO_PRICE_USD = float(os.getenv("PRO_PRICE_USD", "10"))
BIZ_PRICE_USD = float(os.getenv("BIZ_PRICE_USD", "99"))
BIZ_INCLUDED_SEATS = int(os.getenv("BIZ_INCLUDED_SEATS", "25"))
BIZ_EXTRA_SEAT_USD = float(os.getenv("BIZ_EXTRA_SEAT_USD", "3"))

def _auth_headers():
    if not MP_TOKEN:
        raise HTTPException(status_code=500, detail="Falta MP_ACCESS_TOKEN")
    return {"Authorization": f"Bearer {MP_TOKEN}", "Content-Type": "application/json"}

def _normalize_plan(plan: str) -> str:
    p = (plan or "PRO").upper()
    if p in {"BUSINESS", "EMPRESA", "ENTERPRISE"}:
        return "EMPRESAS"
    return p

def _plan_amount_with_seats(plan: str, seats: int) -> float:
    p = _normalize_plan(plan)
    try:
        s = int(seats or 0)
    except Exception:
        s = 0
    if p == "EMPRESAS":
        base = float(BIZ_PRICE_USD)
        inc  = int(BIZ_INCLUDED_SEATS)
        extra = max(0, s - inc)
        return round(base + (extra * float(BIZ_EXTRA_SEAT_USD)), 2)
    return float(PRO_PRICE_USD)

@router.get("/billing/checkout")
def billing_checkout_get(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    # Mantener compatibilidad con checkout one-shot existente
    return RedirectResponse(url=f"/billing/checkout?plan={plan}&seats={seats}", status_code=303)

@router.get("/billing/checkout/empresas")
def billing_checkout_empresas(db: Session = Depends(get_db), user = Depends(get_current_user_cookie)):
    return RedirectResponse(url=f"/billing/checkout?plan=EMPRESAS&seats={BIZ_INCLUDED_SEATS}", status_code=303)

@router.get("/billing/subscribe")
def billing_subscribe(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    norm_plan = _normalize_plan(plan)
    amount = _plan_amount_with_seats(norm_plan, seats)
    body = {
        "payer_email": getattr(user, "email", None) or "test_user@example.com",
        "reason": f"AlertTrail {norm_plan} mensual",
        "external_reference": json.dumps({
            "user_id": getattr(user, "id", None),
            "plan": norm_plan,
            "seats": int(seats) if seats else (BIZ_INCLUDED_SEATS if norm_plan == "EMPRESAS" else 1),
            "ts": datetime.utcnow().isoformat()
        }),
        "back_url": f"{BASE_URL}/billing/return",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(amount),
            "currency_id": PLAN_CURRENCY,
        }
    }
    r = requests.post("https://api.mercadopago.com/preapproval", headers=_auth_headers(), data=json.dumps(body))
    if r.status_code not in (200,201):
        try: det = r.json()
        except Exception: det = {"raw": r.text}
        raise HTTPException(status_code=500, detail={"error":"MP preapproval create failed", "detail": det})
    pre = r.json()
    try:
        pre_id = pre.get('id')
        if pre_id:
            sub = db.query(Subscription).filter(Subscription.preapproval_id==pre_id).first()
            if sub:
                sub.status = 'pending'
                sub.plan = norm_plan
                sub.seats = int(seats or 0)
                sub.raw = json.dumps(pre)[:4000]
                sub.updated_at = datetime.utcnow()
            else:
                db.add(Subscription(user_id=getattr(user,'id',None), preapproval_id=pre_id, plan=norm_plan, seats=int(seats or 0), status='pending', next_payment_date=None, raw=json.dumps(pre)[:4000]))
            try: db.commit()
            except Exception: db.rollback()
    except Exception: pass

    init_point = pre.get("init_point") or pre.get("sandbox_init_point")
    if not init_point:
        raise HTTPException(status_code=500, detail="MP preapproval sin init_point")
    return RedirectResponse(url=init_point, status_code=303)

@router.post("/mp/webhook")
async def mp_webhook(request: Request, db: Session = Depends(get_db)):
    secret = request.query_params.get("secret")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    topic = (payload.get("type") or payload.get("topic") or "").lower()
    data  = payload.get("data") or {}
    res_id = data.get("id") or payload.get("id")

    # Suscripciones
    if topic == "preapproval" or (topic == "" and res_id):
        pre_id = res_id or payload.get("preapproval_id")
        if pre_id:
            pr = requests.get(f"https://api.mercadopago.com/preapproval/{pre_id}", headers=_auth_headers())
            if pr.status_code == 200:
                pj = pr.json()
                status_mp = (pj.get("status") or "").lower()
                next_date = pj.get('next_payment_date')
                try:
                    meta = json.loads(pj.get("external_reference") or "{}")
                except Exception:
                    meta = {}
                user_id = meta.get("user_id")
                plan    = _normalize_plan(meta.get("plan") or "PRO")
                # Upsert subscription row
                try:
                    sub = db.query(Subscription).filter(Subscription.preapproval_id==pre_id).first()
                    if sub:
                        sub.user_id = sub.user_id or user_id
                        sub.plan = plan
                        sub.status = status_mp
                        sub.seats = meta.get('seats') or sub.seats
                        sub.next_payment_date = next_date
                        sub.raw = json.dumps(pj)[:4000]
                        sub.updated_at = datetime.utcnow()
                    else:
                        db.add(Subscription(user_id=user_id, preapproval_id=pre_id, plan=plan, seats=meta.get('seats') or 0, status=status_mp, next_payment_date=next_date, raw=json.dumps(pj)[:4000]))
                    try: db.commit()
                    except Exception: db.rollback()
                except Exception: pass
                if status_mp == "authorized" and user_id:
                    from ..models import User
                    u = db.query(User).get(user_id)
                    if u:
                        try:
                            u.plan = plan
                            db.commit()
                        except Exception:
                            db.rollback()
                return {"ok": True, "plan": plan, "user_id": user_id, "status": status_mp}
            return {"ok": True, "skip": "preapproval lookup failed or missing"}

    # Pago único (compat)
    if topic in {"payment"} or True:
        payment_id = res_id or request.query_params.get("id")
        if not payment_id:
            return {"ok": True, "skip": "no payment id"}
        pr = requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers=_auth_headers())
        if pr.status_code != 200:
            return {"ok": False, "error": "payment lookup failed"}
        p = pr.json()
        status_mp = (p.get("status") or "").lower()
        md = p.get("metadata") or {}
        user_id = md.get("user_id")
        plan = _normalize_plan(md.get("plan") or "PRO")
        if status_mp == "approved" and user_id:
            from ..models import User
            u = db.query(User).get(user_id)
            if u:
                try:
                    u.plan = plan
                    db.commit()
                except Exception:
                    db.rollback()
        return {"ok": True, "status": status_mp, "user_id": user_id, "plan": plan}

@router.get("/billing/return", response_class=HTMLResponse)
def billing_return():
    return HTMLResponse("<h1>Suscripción</h1><p>Si autorizaste el débito automático, tu plan quedará activo en minutos.</p>")

