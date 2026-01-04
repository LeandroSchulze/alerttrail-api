# app/routers/payments.py
# --- Updated: webhook signature (optional), robust MP calls, idempotent sync/activate ---
# --- Tweaks: FastAPI v2-friendly param validation (no regex in Query), SQLAlchemy .get() usage, minor hardening ---

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

# ====== Config / Env ======
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()

REQ_TIMEOUT = int(os.getenv("MP_REQ_TIMEOUT_SEC", "25"))


def _require_mp_token():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado en el entorno")


def _mp_headers():
    return {"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"}


def _secure_compare(a: str, b: str) -> bool:
    try:
        import hmac
        return hmac.compare_digest(a.encode(), b.encode())
    except Exception:
        return False


# -------------------------
# URL helpers (ABS back_url)
# -------------------------
def _base_url() -> str:
    """
    Devuelve URL base absoluta para construir back_url.
    Recomendado en Render:
      APP_BASE_URL=https://www.alerttrail.com
    Fallbacks: PUBLIC_URL, RENDER_EXTERNAL_URL, https://www.alerttrail.com
    """
    base = (
        (os.getenv("APP_BASE_URL") or "").strip()
        or (os.getenv("PUBLIC_URL") or "").strip()
        or (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
        or "https://www.alerttrail.com"
    )
    return base[:-1] if base.endswith("/") else base


def _abs_url(path: str) -> str:
    if not path:
        path = "/"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return _base_url() + path


# -------------------------
# User helpers (dict or ORM)
# -------------------------
def _user_get(user, key: str, default=None):
    """Soporta user como dict (cookie) o como ORM object."""
    if user is None:
        return default
    try:
        if isinstance(user, dict):
            return user.get(key, default)
        return getattr(user, key, default)
    except Exception:
        return default


def _user_id(user) -> Optional[int]:
    """Intenta resolver id desde dict u objeto."""
    uid = _user_get(user, "id", None)
    if uid is not None:
        try:
            return int(str(uid))
        except Exception:
            return None

    # fallback: en JWT suele venir sub
    sub = _user_get(user, "sub", None)
    try:
        return int(str(sub)) if sub is not None else None
    except Exception:
        return None


def _user_email(user) -> Optional[str]:
    email = _user_get(user, "email", None)
    return str(email).strip() if email else None


# ====== Precio / moneda ======
def _amount_currency(plan: str, seats: int) -> Tuple[float, str]:
    """
    Define el monto y moneda para el preapproval.
    Variables soportadas (todas opcionales, con defaults razonables):
      - PLAN_CURRENCY (default USD)
      - PRO_PRICE_USD (default 10.0)
      - BIZ_PRICE_USD (default 25.0)
      - BIZ_EXTRA_SEAT_USD (default 5.0)  # por asiento adicional
      - BIZ_INCLUDED_SEATS (default 25)   # asientos incluidos en EMPRESAS
    """
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    pro_price = float(os.getenv("PRO_PRICE_USD") or os.getenv("PLAN_PRICE") or 10.0)
    biz_base = float(os.getenv("BIZ_PRICE_USD") or 25.0)
    biz_extra = float(os.getenv("BIZ_EXTRA_SEAT_USD") or 5.0)
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
    status = Column(String, index=True)  # authorized/paused/cancelled/pending
    plan = Column(String)  # PRO / BIZ
    seats = Column(Integer, default=1)
    currency = Column(String, default="USD")
    amount = Column(Integer)  # monto por periodo (entero por simplicidad)
    next_payment_date = Column(String)
    external_reference = Column(String, index=True)
    raw = Column(Text)  # JSON crudo de MP
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Crear tabla si no existe (idempotente)
try:
    SubBase.metadata.create_all(_engine)
except Exception:
    pass


# ====== Helpers Mercado Pago ======
def _preapproval_payload(*, payer_email: str, amount: float, currency: str, reason: str, external_ref: str):
    """
    Crea el payload para /preapproval (suscripción).
    MercadoPago exige back_url ABSOLUTA.
    """
    back = (os.getenv("MP_BACK_URL") or "").strip()
    back_url = _abs_url(back or "/billing/return")

    return {
        "payer_email": payer_email,
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(amount),
            "currency_id": currency,
        },
        "reason": reason,
        "external_reference": external_ref,
        "back_url": back_url,
    }


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


# ====== Persistencia local y activación de plan ======
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

    if "BIZ" in plan_final.upper():
        plan_final = "BIZ"
    elif "PRO" in plan_final.upper():
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
    """
    Si la sub está 'authorized', activar plan del usuario.
    Mejora mínima: setea pro_expires_at (si existe en el modelo) usando next_payment_date.
    """
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


# ====== Endpoints ======
@router.get("/payments/subscribe", response_class=RedirectResponse)
def payments_subscribe(
    request: Request,
    plan: str = Query(..., description="Plan a suscribirse: PRO o BIZ"),
    seats: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """
    Crea un preapproval en MP y redirige a la URL de autorización del cliente.
    - plan: PRO o BIZ
    - seats: usado sólo para BIZ.
    """
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
    external_ref = f"sub-{plan_norm}-{uid}-{uuid.uuid4().hex[:8]}"
    reason = f"AlertTrail {plan_norm} ({currency} {amount})"

    payload = _preapproval_payload(
        payer_email=email,
        amount=amount,
        currency=currency,
        reason=reason,
        external_ref=external_ref,
    )
    url = "https://api.mercadopago.com/preapproval"
    try:
        r = requests.post(url, headers=_mp_headers(), data=json.dumps(payload), timeout=REQ_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"MP preapproval error: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP preapproval error {r.status_code}: {r.text}")

    data = r.json()
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
    """Consulta estado en MP y sincroniza localmente + activa plan si procede."""
    _require_mp_token()
    result = _sync_preapproval(db, preapproval_id=preapproval_id)
    return result


@router.post("/payments/cancel", response_class=JSONResponse)
def payments_cancel(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """Cancela/pausa una suscripción en MP (si tu cuenta lo permite)."""
    _require_mp_token()
    payload = {"status": "paused"}
    detail = _mp_update_preapproval(preapproval_id, payload)
    _upsert_subscription(db, user_id=_user_id(user), preapproval_id=preapproval_id, data=detail)
    return {"ok": True, "status": (detail.get("status") or "").lower()}


# ====== Webhook (notificación de MP) ======
@router.post("/payments/webhook", response_class=JSONResponse)
async def payments_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook para notificaciones de Mercado Pago.
    MP envía típicamente:
      - body: {"type":"preapproval", "action":"status", "data":{"id":"<preapproval_id>"}, ...}
    o query params: ?type=preapproval&id=<preapproval_id>&topic=preapproval
    Este endpoint sincroniza la suscripción local y activa el plan si corresponde.
    Si seteaste MP_WEBHOOK_SECRET, se valida contra el header `X-Webhook-Secret`.
    """
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


# ====== Retorno de billing (opcionalmente sincroniza) ======
@router.get("/billing/return", response_class=HTMLResponse)
def billing_return(preapproval_id: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Página de retorno para el usuario luego de autorizar en MP.
    Si viene preapproval_id, sincroniza y, si está 'authorized', activa el plan.
    """
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


# ====== Utilidad opcional: sincronizar la última sub del usuario ======
@router.get("/payments/sync_latest", response_class=JSONResponse)
def payments_sync_latest(db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    """Sincroniza rápidamente la suscripción más reciente del usuario logueado (si existe)."""
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

    res = _sync_preapproval(db, preapproval_id=sub.preapproval_id)
    return res
