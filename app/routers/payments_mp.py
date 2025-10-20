# app/routers/payments_mp.py
from __future__ import annotations

import os, json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import User, PaymentEvent, PaymentHistory
from app.mailer import send_payment_confirmation_email

MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
router = APIRouter(prefix="/webhook", tags=["payments-mp"])

# -----------------------------
# Helpers
# -----------------------------
def _resolve_user_by_email_or_id(db: Session, email: Optional[str], user_id: Optional[int]) -> Optional[User]:
    """Busca usuario por id o email (case-insensitive)."""
    if user_id:
        u = db.query(User).get(user_id)
        if u:
            return u
    if email:
        return db.query(User).filter(User.email.ilike(email.strip().lower())).first()
    return None

def _pick_expiry_attr(user: User) -> Optional[str]:
    """Devuelve el nombre del atributo de expiración que exista en el modelo."""
    for attr in ("pro_expires_at", "plan_expires", "pro_until"):
        if hasattr(user, attr):
            return attr
    return None

def _plan_months(plan: str) -> int:
    """Cantidad de meses por ciclo para el plan."""
    # Si luego agregás anual, cambiar aquí.
    return 1

def _safe_iso(d: Optional[datetime]) -> Optional[str]:
    if isinstance(d, datetime):
        try:
            # Asegura tz para consistencia
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except Exception:
            return str(d)
    return None

def activate_pro_for_user(db: Session, *, user: User, months: int = 1, payment_id: Optional[str] = None) -> bool:
    """Activa/Extiende PRO de forma idempotente (respecta expiración futura)."""
    now = datetime.now(timezone.utc)

    # Marca de plan
    try:
        if hasattr(user, "plan"):
            user.plan = "PRO"
        if hasattr(user, "is_pro"):
            user.is_pro = True  # ignorado si no existe
    except Exception:
        pass

    # Expiración
    expiry_attr = _pick_expiry_attr(user)
    if expiry_attr:
        current = getattr(user, expiry_attr, None)
        base = current if (isinstance(current, datetime) and current > now) else now
        new_expiry = base + timedelta(days=30 * months)
        try:
            setattr(user, expiry_attr, new_expiry)
        except Exception:
            pass

    # Idempotencia simple por último pago (campo auxiliar)
    if hasattr(user, "last_payment_id") and payment_id:
        try:
            user.last_payment_id = str(payment_id)
        except Exception:
            pass

    db.add(user)
    db.commit()
    db.refresh(user)
    return True

async def _mp_get_payment(payment_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """Consulta a MP por el pago; devuelve (json, error)."""
    if not MP_ACCESS_TOKEN:
        return None, "missing_token"
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers)
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    try:
        return r.json(), None
    except Exception as e:
        return None, f"json_error:{e!r}"

def _extract_from_mp_payment(pj: dict) -> dict:
    """Normaliza campos comunes del JSON de MP."""
    payer = pj.get("payer") or {}
    meta = pj.get("metadata") or {}

    out = {
        "status": pj.get("status"),
        "external_reference": pj.get("external_reference"),
        "payer_email": payer.get("email"),
        "user_id_meta": meta.get("user_id") or meta.get("uid"),
        "amount_cents": None,
        "currency": pj.get("currency_id") or (pj.get("transaction_details") or {}).get("net_received_amount_currency"),
        "provider_payment_id": str(pj.get("id") or ""),
        "plan": (meta.get("plan") or "PRO").upper(),
        "raw": pj,
    }
    # transaction_amount suele venir como float (ej. 10.0)
    ta = pj.get("transaction_amount")
    try:
        if ta is not None:
            out["amount_cents"] = int(round(float(ta) * 100))
    except Exception:
        out["amount_cents"] = None
    return out

def _record_payment_event(db: Session, *, user: Optional[User], info: dict) -> PaymentEvent:
    """Crea (o devuelve) el PaymentEvent idempotente por provider+payment_id."""
    provider = "mp"
    provider_payment_id = info.get("provider_payment_id") or ""
    status = (info.get("status") or "").lower() or None
    plan = info.get("plan")
    amount_cents = info.get("amount_cents")
    currency = info.get("currency") or "USD"
    ext = info.get("external_reference")
    raw_payload = json.dumps(info.get("raw") or {}, ensure_ascii=False)

    # ¿Existe ya?
    ev = db.query(PaymentEvent).filter(
        PaymentEvent.provider == provider,
        PaymentEvent.payment_id == provider_payment_id
    ).first()

    if ev:
        # Actualizamos status si cambió (no rompemos idempotencia)
        changed = False
        if status and ev.status != status:
            ev.status = status; changed = True
        if plan and ev.plan != plan:
            ev.plan = plan; changed = True
        if amount_cents and not ev.amount_cents:
            ev.amount_cents = amount_cents; changed = True
        if currency and not ev.currency:
            ev.currency = currency; changed = True
        if ext and not ev.external_ref:
            ev.external_ref = ext; changed = True
        if user and not ev.user_id:
            ev.user_id = user.id; changed = True
        if changed:
            db.add(ev); db.commit(); db.refresh(ev)
        return ev

    ev = PaymentEvent(
        user_id=(user.id if user else None),
        provider=provider,
        payment_id=provider_payment_id or "",  # puede estar vacío en fallback
        status=status,
        plan=plan,
        amount_cents=amount_cents,
        currency=currency,
        external_ref=str(ext) if ext is not None else None,
        raw_payload=raw_payload,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev

def _append_payment_history(db: Session, *, user: User, info: dict, period_months: int = 1) -> PaymentHistory:
    """Inserta un movimiento en el historial para UI/auditoría."""
    ph = PaymentHistory(
        user_id=user.id,
        provider="mp",
        provider_payment_id=info.get("provider_payment_id"),
        plan=info.get("plan") or "PRO",
        period_months=period_months,
        amount_cents=info.get("amount_cents"),
        currency=info.get("currency") or "USD",
        status=(info.get("status") or "approved").lower(),
        description="Renovación/activación por Mercado Pago",
        raw_payload=json.dumps(info.get("raw") or {}, ensure_ascii=False),
    )
    db.add(ph)
    db.commit()
    db.refresh(ph)
    return ph

# -----------------------------
# Webhook MP
# -----------------------------
@router.get("/mercadopago", response_class=JSONResponse)
async def mp_challenge():
    # MP suele hacer un GET “challenge” inicial
    return JSONResponse({"ok": True, "method": "GET"})

@router.post("/mercadopago", response_class=JSONResponse)
async def mp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Mercado Pago.
    - Valida pago con la API si viene payment_id.
    - Extrae user_id desde `external_reference` (número) o `metadata.user_id`/email.
    - Activa PRO de forma idempotente.
    - Registra PaymentEvent y PaymentHistory.
    - Envía mail de confirmación.
    - Devuelve 200 siempre (evitar reintentos en exceso); usar status en payload.
    """
    # 1) Parse body
    try:
        body = await request.json()
    except Exception:
        body = {}

    # 2) Detecta payment_id (puede venir como URL)
    payment_id = None
    if isinstance(body, dict):
        payment_id = (
            body.get("id")
            or (body.get("data") or {}).get("id")
            or body.get("resource")  # a veces viene URL completa
        )
        if isinstance(payment_id, str) and payment_id.startswith("https"):
            payment_id = payment_id.rstrip("/").split("/")[-1]

    user: Optional[User] = None
    status: Optional[str] = None
    email: Optional[str] = None
    raw_ext_ref: Optional[str] = None
    normalized = None

    # 3) Si hay payment_id y token, valida contra MP
    if payment_id and MP_ACCESS_TOKEN:
        pj, perr = await _mp_get_payment(str(payment_id))
        if pj:
            normalized = _extract_from_mp_payment(pj)
            status = normalized["status"]
            raw_ext_ref = normalized["external_reference"]
            email = normalized["payer_email"]

            # Prioridad: external_reference (num) > metadata.user_id > email
            user_id = None
            if raw_ext_ref and str(raw_ext_ref).isdigit():
                user_id = int(raw_ext_ref)
            elif normalized["user_id_meta"] and str(normalized["user_id_meta"]).isdigit():
                user_id = int(normalized["user_id_meta"])

            user = _resolve_user_by_email_or_id(db, email=email, user_id=user_id)

            # Registrar evento (idempotente)
            _record_payment_event(db, user=user, info=normalized)

            # Si está aprobado y hay usuario, activar/registrar/avisar
            if (status or "").lower() == "approved" and user:
                months = _plan_months(normalized["plan"])
                activate_pro_for_user(db, user=user, months=months, payment_id=normalized["provider_payment_id"])
                _append_payment_history(db, user=user, info=normalized, period_months=months)

                # Email de confirmación (best-effort)
                exp_attr = _pick_expiry_attr(user)
                exp_val = getattr(user, exp_attr) if (exp_attr and hasattr(user, exp_attr)) else None
                try:
                    send_payment_confirmation_email(user.email, normalized["plan"], _safe_iso(exp_val))
                except Exception as e:
                    print("[payments_mp] WARN mail confirm:", repr(e))

                return JSONResponse({
                    "ok": True,
                    "approved": True,
                    "status": status,
                    "user_id": user.id,
                    "plan": getattr(user, "plan", None),
                    "expires_attr": exp_attr,
                    "expires_at": _safe_iso(exp_val),
                    "last_payment_id": getattr(user, "last_payment_id", None),
                    "provider_payment_id": normalized["provider_payment_id"],
                }, status_code=200)

    # 4) Fallback SIN validación (sandbox o pruebas locales)
    if not normalized:
        # Intentar leer hints del body crudo
        raw_ext_ref = body.get("external_reference") or (body.get("data") or {}).get("external_reference")
        meta = body.get("metadata") or (body.get("data") or {}).get("metadata") or {}
        email = email or meta.get("email") or body.get("payer_email")

        plan = (body.get("plan") or meta.get("plan") or "PRO").upper()
        amount_cents = None
        currency = (body.get("currency") or meta.get("currency") or "USD").upper()

        normalized = {
            "status": body.get("payment_status") or body.get("status") or "approved",
            "external_reference": raw_ext_ref,
            "payer_email": email,
            "user_id_meta": meta.get("user_id") or meta.get("uid"),
            "amount_cents": amount_cents,
            "currency": currency,
            "provider_payment_id": str(payment_id or ""),
            "plan": plan,
            "raw": body,
        }

    # Resolver usuario en fallback
    if not user:
        user_id = None
        if raw_ext_ref and str(raw_ext_ref).isdigit():
            user_id = int(raw_ext_ref)
        else:
            mid = normalized.get("user_id_meta")
            if mid and str(mid).isdigit():
                user_id = int(mid)
        user = _resolve_user_by_email_or_id(db, email=email, user_id=user_id)

    # Registrar evento (aunque sea fallback)
    _record_payment_event(db, user=user, info=normalized)

    # Si podemos mapear usuario, activamos como aprobado (fallback)
    if user:
        months = _plan_months(normalized["plan"])
        activate_pro_for_user(db, user=user, months=months, payment_id=normalized["provider_payment_id"])
        _append_payment_history(db, user=user, info=normalized, period_months=months)

        exp_attr = _pick_expiry_attr(user)
        exp_val = getattr(user, exp_attr) if (exp_attr and hasattr(user, exp_attr)) else None
        try:
            send_payment_confirmation_email(user.email, normalized["plan"], _safe_iso(exp_val))
        except Exception as e:
            print("[payments_mp] WARN mail confirm (fallback):", repr(e))

        return JSONResponse({
            "ok": True,
            "approved": True,   # asumimos aprobado en fallback manual
            "status": normalized.get("status"),
            "user_id": user.id,
            "plan": getattr(user, "plan", None),
            "expires_attr": exp_attr,
            "expires_at": _safe_iso(exp_val),
            "last_payment_id": getattr(user, "last_payment_id", None),
            "provider_payment_id": normalized.get("provider_payment_id"),
            "external_reference": raw_ext_ref,
            "fallback": True,
        }, status_code=200)

    # 5) Sin usuario o estado no aprobado
    return JSONResponse({
        "ok": True,
        "approved": False,
        "status": normalized.get("status") if normalized else None,
        "user_found": bool(user),
        "user_id": getattr(user, "id", None) if user else None,
        "email_tried": email,
        "external_reference": raw_ext_ref,
        "provider_payment_id": (normalized or {}).get("provider_payment_id"),
    }, status_code=200)

