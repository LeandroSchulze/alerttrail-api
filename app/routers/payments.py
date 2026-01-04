# app/routers/payments.py
# Fixes:
# - back_url must be absolute
# - retry without auto_recurring.currency_id if MP rejects it
# - enforce/auto-adjust minimum amount for preapproval (MP_MIN_AMOUNT, default 15)

import os
import json
import uuid
from typing import Optional, Tuple

import requests
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..security import get_current_user_cookie
from ..models import User

router = APIRouter()

MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()

REQ_TIMEOUT = int(os.getenv("MP_REQ_TIMEOUT_SEC", "25"))

# ✅ Mercado Pago min amount (varía por cuenta/país). Default: 15
MP_MIN_AMOUNT = float(os.getenv("MP_MIN_AMOUNT") or 15.0)


def _require_mp_token():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado en el entorno")


def _mp_headers():
    return {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _secure_compare(a: str, b: str) -> bool:
    try:
        import hmac
        return hmac.compare_digest(a.encode(), b.encode())
    except Exception:
        return False


def _user_get(user, key: str, default=None):
    if user is None:
        return default
    try:
        if isinstance(user, dict):
            return user.get(key, default)
        return getattr(user, key, default)
    except Exception:
        return default


def _user_id(user) -> Optional[int]:
    uid = _user_get(user, "id", None)
    if uid is not None:
        try:
            return int(str(uid))
        except Exception:
            return None
    sub = _user_get(user, "sub", None)
    try:
        return int(str(sub)) if sub is not None else None
    except Exception:
        return None


def _user_email(user) -> Optional[str]:
    email = _user_get(user, "email", None)
    return str(email).strip() if email else None


def _is_abs_url(u: str) -> bool:
    u = (u or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _absolute_url_from_request(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    path = (path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _resolve_back_url(request: Request) -> str:
    env_url = (os.getenv("MP_BACK_URL") or "").strip()
    if env_url:
        if _is_abs_url(env_url):
            return env_url
        return _absolute_url_from_request(request, env_url)
    return _absolute_url_from_request(request, "/billing/return")


def _amount_currency(plan: str, seats: int) -> Tuple[float, str]:
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    pro_price = float(os.getenv("PRO_PRICE_USD") or os.getenv("PLAN_PRICE") or 10.0)
    biz_base = float(os.getenv("BIZ_PRICE_USD") or 99.0)  # ✅ tu default deseado
    biz_extra = float(os.getenv("BIZ_EXTRA_SEAT_USD") or 3.0)  # ✅ tu default deseado
    included = int(os.getenv("BIZ_INCLUDED_SEATS") or 25)
    plan_norm = (plan or "PRO").upper()

    if plan_norm == "BIZ":
        total_seats = max(int(seats or included), 1)
        extras = max(0, total_seats - included)
        amount = biz_base + extras * biz_extra
    else:
        amount = pro_price

    return (float(amount), currency)


# ====== Modelo local de suscripción ======
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

SubBase = declarative_base()
_engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind


class Subscription(SubBase):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("preapproval_id", name="uq_preapproval_id"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    preapproval_id = Column(String, unique=True, index=True)
    status = Column(String, index=True)
    plan = Column(String)
    seats = Column(Integer, default=1)
    currency = Column(String, default="USD")
    amount = Column(Integer)
    next_payment_date = Column(String)
    external_reference = Column(String, index=True)
    raw = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


try:
    SubBase.metadata.create_all(_engine)
except Exception:
    pass


def _preapproval_payload(
    *,
    payer_email: str,
    amount: float,
    currency: Optional[str],
    reason: str,
    external_ref: str,
    back_url: str,
    include_currency: bool = True,
):
    auto_recurring = {
        "frequency": 1,
        "frequency_type": "months",
        "transaction_amount": float(amount),
    }
    if include_currency and currency:
        auto_recurring["currency_id"] = currency

    return {
        "payer_email": payer_email,
        "auto_recurring": auto_recurring,
        "reason": reason,
        "external_reference": external_ref,
        "back_url": back_url,
    }


def _mp_create_preapproval(payload: dict) -> dict:
    url = "https://api.mercadopago.com/preapproval"
    try:
        r = requests.post(url, headers=_mp_headers(), data=json.dumps(payload), timeout=REQ_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"MP preapproval error: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP preapproval error {r.status_code}: {r.text}")
    return r.json()


def _mp_get_preapproval(preapproval_id: str) -> dict:
    url = f"https://api.mercadopago.com/preapproval/{preapproval_id}"
    try:
        r = requests.get(url, headers=_mp_headers(), timeout=REQ_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"MP GET preapproval error: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP GET preapproval error {r.status_code}: {r.text}")
    return r.json()


def _mp_update_preapproval(preapproval_id: str, payload: dict) -> dict:
    url = f"https://api.mercadopago.com/preapproval/{preapproval_id}"
    try:
        r = requests.put(url, headers=_mp_headers(), data=json.dumps(payload), timeout=REQ_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"MP PUT preapproval error: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP PUT preapproval error {r.status_code}: {r.text}")
    return r.json()


def _upsert_subscription(
    db: Session,
    *,
    user_id: Optional[int],
    preapproval_id: str,
    data: dict,
    plan: Optional[str] = None,
    seats: Optional[int] = None,
):
    status_mp = (data.get("status") or "").lower()
    next_payment_date = (data.get("auto_recurring") or {}).get("next_payment_date") or ""
    currency = (data.get("auto_recurring") or {}).get("currency_id") or (os.getenv("PLAN_CURRENCY") or "USD").upper()
    amount = (data.get("auto_recurring") or {}).get("transaction_amount") or 0
    plan_final = (plan or data.get("reason") or "PRO").upper()

    if "BIZ" in plan_final:
        plan_final = "BIZ"
    elif "PRO" in plan_final:
        plan_final = "PRO"
    else:
        plan_final = (plan or "PRO").upper()

    sub = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
    if sub:
        sub.status = status_mp
        sub.plan = plan_final
        if seats is not None:
            sub.seats = seats
        sub.currency = currency
        try:
            sub.amount = int(round(float(amount)))
        except Exception:
            sub.amount = 0
        sub.next_payment_date = next_payment_date
        sub.raw = json.dumps(data, ensure_ascii=False)
        sub.updated_at = datetime.now(timezone.utc)
        if user_id is not None and not sub.user_id:
            sub.user_id = user_id
    else:
        try:
            amt = int(round(float(amount)))
        except Exception:
            amt = 0
        sub = Subscription(
            user_id=user_id,
            preapproval_id=preapproval_id,
            status=status_mp,
            plan=plan_final,
            seats=seats if seats is not None else 1,
            currency=currency,
            amount=amt,
            next_payment_date=next_payment_date,
            external_reference=data.get("external_reference") or "",
            raw=json.dumps(data, ensure_ascii=False),
        )
        db.add(sub)

    db.commit()
    return sub


def _activate_user_plan_if_authorized(db: Session, *, sub: Subscription):
    if (sub.status or "").lower() == "authorized" and sub.user_id:
        u = db.get(User, sub.user_id)
        if u:
            if hasattr(u, "plan"):
                u.plan = (sub.plan or "PRO").upper()
            if hasattr(u, "is_pro"):
                try:
                    setattr(u, "is_pro", u.plan.upper() == "PRO" if hasattr(u, "plan") else True)
                except Exception:
                    setattr(u, "is_pro", True)
            if hasattr(u, "pro_expires_at") and sub.next_payment_date:
                iso = str(sub.next_payment_date)
                try:
                    u.pro_expires_at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except Exception:
                    pass
            if hasattr(u, "updated_at"):
                u.updated_at = datetime.now(timezone.utc)
            db.commit()


def _sync_preapproval(db: Session, *, preapproval_id: str) -> dict:
    detail = _mp_get_preapproval(preapproval_id)

    existing = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
    user_id = existing.user_id if existing else None

    sub = _upsert_subscription(
        db,
        user_id=user_id,
        preapproval_id=preapproval_id,
        data=detail,
        plan=(existing.plan if existing else None),
        seats=(existing.seats if existing else None),
    )
    _activate_user_plan_if_authorized(db, sub=sub)
    return {
        "ok": True,
        "status": (detail.get("status") or "").lower(),
        "next_payment_date": (detail.get("auto_recurring") or {}).get("next_payment_date") or "",
        "preapproval_id": preapproval_id,
    }


def _normalize_amount_for_mp(amount: float) -> float:
    try:
        a = float(amount)
    except Exception:
        a = 0.0
    if a < MP_MIN_AMOUNT:
        return float(MP_MIN_AMOUNT)
    return a


@router.get("/payments/subscribe", response_class=RedirectResponse)
def payments_subscribe(
    request: Request,
    plan: str = Query(..., description="Plan a suscribirse: PRO o BIZ"),
    seats: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    _require_mp_token()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Necesitás iniciar sesión")

    uid = _user_id(user)
    email = _user_email(user)
    if not uid or not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Necesitás iniciar sesión")

    plan_norm = (plan or "").upper().strip()
    if plan_norm not in {"PRO", "BIZ"}:
        raise HTTPException(status_code=400, detail="Plan inválido: usar PRO o BIZ")

    amount, currency = _amount_currency(plan_norm, seats)
    # ✅ ajustar por mínimo de MP (para evitar "Cannot pay an amount lower than ...")
    amount = _normalize_amount_for_mp(amount)

    external_ref = f"sub-{plan_norm}-{uid}-{uuid.uuid4().hex[:8]}"
    reason = f"AlertTrail {plan_norm} ({currency} {amount})"
    back_url = _resolve_back_url(request)

    # 1) Con currency_id
    payload = _preapproval_payload(
        payer_email=email,
        amount=amount,
        currency=currency,
        reason=reason,
        external_ref=external_ref,
        back_url=back_url,
        include_currency=True,
    )

    try:
        data = _mp_create_preapproval(payload)
    except HTTPException as he:
        msg = str(he.detail or "")

        # 2) Retry sin currency_id si MP lo rechaza
        if "auto_recurring.currency_id" in msg or "Invalid field -> auto_recurring.currency_id" in msg:
            payload2 = _preapproval_payload(
                payer_email=email,
                amount=amount,
                currency=None,
                reason=reason,
                external_ref=external_ref,
                back_url=back_url,
                include_currency=False,
            )
            data = _mp_create_preapproval(payload2)
        # 3) Si MP se queja por mínimo, subir al mínimo y reintentar
        elif "Cannot pay an amount lower than" in msg:
            amount2 = _normalize_amount_for_mp(MP_MIN_AMOUNT)
            payload3 = _preapproval_payload(
                payer_email=email,
                amount=amount2,
                currency=currency,
                reason=f"AlertTrail {plan_norm} ({currency} {amount2})",
                external_ref=external_ref,
                back_url=back_url,
                include_currency=True,
            )
            try:
                data = _mp_create_preapproval(payload3)
            except HTTPException:
                # último intento sin currency
                payload4 = _preapproval_payload(
                    payer_email=email,
                    amount=amount2,
                    currency=None,
                    reason=f"AlertTrail {plan_norm} ({currency} {amount2})",
                    external_ref=external_ref,
                    back_url=back_url,
                    include_currency=False,
                )
                data = _mp_create_preapproval(payload4)
        else:
            raise

    preapproval_id = data.get("id")
    init_point = data.get("init_point") or data.get("sandbox_init_point")

    if not preapproval_id:
        raise HTTPException(status_code=502, detail="MP no devolvió preapproval id")

    _upsert_subscription(
        db,
        user_id=uid,
        preapproval_id=preapproval_id,
        data=data,
        plan=plan_norm,
        seats=seats if plan_norm == "BIZ" else 1,
    )

    return RedirectResponse(init_point or "/billing")


@router.get("/payments/status", response_class=JSONResponse)
def payments_status(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    _require_mp_token()
    return _sync_preapproval(db, preapproval_id=preapproval_id)


@router.post("/payments/cancel", response_class=JSONResponse)
def payments_cancel(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    _require_mp_token()
    detail = _mp_update_preapproval(preapproval_id, {"status": "paused"})
    _upsert_subscription(db, user_id=_user_id(user), preapproval_id=preapproval_id, data=detail)
    return {"ok": True, "status": (detail.get("status") or "").lower()}


@router.post("/payments/webhook", response_class=JSONResponse)
async def payments_webhook(request: Request, db: Session = Depends(get_db)):
    _require_mp_token()

    if MP_WEBHOOK_SECRET:
        provided = request.headers.get("X-Webhook-Secret", "")
        if not _secure_compare(MP_WEBHOOK_SECRET, provided):
            return JSONResponse({"ok": False, "error": "firma inválida"}, status_code=200)

    preapproval_id = None
    topic = None

    try:
        body = await request.json()
    except Exception:
        body = {}

    if isinstance(body, dict):
        data = body.get("data") or {}
        preapproval_id = data.get("id") or body.get("id") or preapproval_id
        topic = body.get("topic") or body.get("type") or topic

    if not preapproval_id:
        qp = dict(request.query_params)
        preapproval_id = qp.get("id") or qp.get("preapproval_id") or preapproval_id
        topic = qp.get("topic") or qp.get("type") or topic

    if not preapproval_id:
        return JSONResponse({"ok": False, "ignored": True, "reason": "sin id"}, status_code=200)

    try:
        result = _sync_preapproval(db, preapproval_id=preapproval_id)
    except HTTPException as he:
        return JSONResponse({"ok": False, "error": he.detail}, status_code=200)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)

    return JSONResponse({"ok": True, "topic": topic or "", **result}, status_code=200)


@router.get("/billing/return", response_class=HTMLResponse)
def billing_return(preapproval_id: Optional[str] = None, db: Session = Depends(get_db)):
    if preapproval_id:
        try:
            _sync_preapproval(db, preapproval_id=preapproval_id)
        except Exception:
            pass

    html = """
    <h1>Suscripción AlertTrail</h1>
    <p>Si autorizaste el débito automático, tu plan quedará activo en minutos.
    Podés volver al <a href="/dashboard">dashboard</a> o revisar tu
    <a href="/billing/subscriptions">estado de suscripción</a>.</p>
    """
    return HTMLResponse(html)


@router.get("/payments/sync_latest", response_class=JSONResponse)
def payments_sync_latest(db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    uid = _user_id(user)
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Necesitás iniciar sesión")

    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == uid)
        .order_by(Subscription.updated_at.desc())
        .first()
    )
    if not sub:
        return {"ok": False, "reason": "sin suscripciones"}

    return _sync_preapproval(db, preapproval_id=sub.preapproval_id)
