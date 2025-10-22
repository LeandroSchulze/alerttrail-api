# app/routers/webhooks.py
from __future__ import annotations

import os
import json
import hmac
import hashlib
import re
import datetime as dt
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.payments.mp_client import sdk
from app.services.subscription import activate_pro
from app.models import User

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# HMAC compartido opcional (si lo configurás en tu proxy o MP)
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
PLAN_PRO_DAYS = int(os.getenv("PLAN_PRO_DAYS", "30") or "30")


def _ok(payload: dict) -> JSONResponse:
    return JSONResponse(payload, status_code=200)


# ---------- Payments table helpers ----------
def _ensure_payments_table(db: Session) -> None:
    """
    Crea la tabla 'payments' si no existe, compatible con SQLite y Postgres.
    Evita fallar si ya existe (idempotente).
    """
    eng = db.get_bind()
    dialect = getattr(eng.dialect, "name", "sqlite")
    if dialect == "sqlite":
        ddl = """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            payment_id VARCHAR UNIQUE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            email VARCHAR,
            status VARCHAR,
            currency VARCHAR,
            amount NUMERIC,
            external_reference VARCHAR,
            paid_at DATETIME,
            raw TEXT,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_payment_id ON payments(payment_id);
        CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status);
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            payment_id VARCHAR UNIQUE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            email VARCHAR,
            status VARCHAR,
            currency VARCHAR,
            amount NUMERIC,
            external_reference VARCHAR,
            paid_at TIMESTAMPTZ,
            raw TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_payment_id ON payments(payment_id);
        CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status);
        """
    for stmt in ddl.split(";"):
        s = stmt.strip()
        if s:
            db.execute(text(s))
    db.commit()


def _upsert_payment(
    db: Session,
    *,
    payment_id: str,
    user_id: Optional[int],
    email: Optional[str],
    status: Optional[str],
    currency: Optional[str],
    amount: Optional[float],
    external_reference: Optional[str],
    paid_at: Optional[str],
    raw: dict,
) -> None:
    _ensure_payments_table(db)
    now = dt.datetime.utcnow().isoformat()
    raw_json = json.dumps(raw, ensure_ascii=False)

    upd = db.execute(
        text(
            """
            UPDATE payments SET
                user_id = COALESCE(:user_id, user_id),
                email = COALESCE(:email, email),
                status = :status,
                currency = COALESCE(:currency, currency),
                amount = COALESCE(:amount, amount),
                external_reference = COALESCE(:external_reference, external_reference),
                paid_at = COALESCE(:paid_at, paid_at),
                raw = :raw,
                updated_at = :now
            WHERE payment_id = :payment_id
            """
        ),
        {
            "payment_id": payment_id,
            "user_id": user_id,
            "email": email,
            "status": status,
            "currency": currency,
            "amount": amount,
            "external_reference": external_reference,
            "paid_at": paid_at,
            "raw": raw_json,
            "now": now,
        },
    )
    if getattr(upd, "rowcount", 0) and upd.rowcount > 0:
        db.commit()
        return

    db.execute(
        text(
            """
            INSERT INTO payments
                (payment_id, user_id, email, status, currency, amount, external_reference, paid_at, raw, created_at, updated_at)
            VALUES
                (:payment_id, :user_id, :email, :status, :currency, :amount, :external_reference, :paid_at, :raw, :now, :now)
            """
        ),
        {
            "payment_id": payment_id,
            "user_id": user_id,
            "email": email,
            "status": status,
            "currency": currency,
            "amount": amount,
            "external_reference": external_reference,
            "paid_at": paid_at,
            "raw": raw_json,
            "now": now,
        },
    )
    db.commit()


# ---------- User resolution helpers ----------
def _parse_user_from_external_reference(ext_ref: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Admite:
      - "user:<id>"
      - "email:<addr>"
      - "<id>" (solo números)
      - "user:<id>:ts:<timestamp>"
    """
    if not ext_ref:
        return (None, None)
    ref = str(ext_ref).strip()
    m = re.match(r"^user:(\d+)(:.*)?$", ref)
    if m:
        try:
            return (int(m.group(1)), None)
        except Exception:
            pass
    m = re.match(r"^email:([^:]+)$", ref)
    if m:
        return (None, m.group(1).strip())
    if ref.isdigit():
        try:
            return (int(ref), None)
        except Exception:
            pass
    return (None, None)


def _resolve_user(db: Session, user_id: Optional[int], email: Optional[str]) -> Optional[User]:
    if user_id:
        u = db.get(User, user_id)  # SQLAlchemy 2.x-friendly
        if u:
            return u
    if email:
        return db.query(User).filter(User.email.ilike(email)).first()
    return None


def _secure_compare(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except Exception:
        return False


# ---------- Webhook ----------
@router.post("/mercadopago", response_class=JSONResponse)
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook Mercado Pago (idempotente):
    - Verifica HMAC si MP_WEBHOOK_SECRET (header 'x-signature' o 'X-Webhook-Secret').
    - Tolera múltiples formatos de MP: 'type/topic', 'action' (payment.*), query (?topic=payment&id=...).
    - Lee el pago con SDK; si 'approved' → activate_pro(user, PLAN_PRO_DAYS).
    - Registra/actualiza el pago en 'payments'.
    - Siempre responde 200 (para evitar reintentos agresivos).
    """
    # 1) payload crudo
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        payload = {}

    # 2) firma opcional
    if MP_WEBHOOK_SECRET:
        # Aceptamos dos variantes: firma directa del body o header compartido simple
        signed = request.headers.get("x-signature") or ""
        shared = request.headers.get("X-Webhook-Secret") or ""
        if signed:
            expected = hmac.new(MP_WEBHOOK_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            if not _secure_compare(expected, signed):
                return _ok({"status": "invalid-signature"})
        elif shared:
            if not _secure_compare(MP_WEBHOOK_SECRET, shared):
                return _ok({"status": "invalid-shared-secret"})
        else:
            return _ok({"status": "missing-signature"})

    # 3) detectar tipo e id
    ntype = payload.get("type") or payload.get("topic") or ""
    action = payload.get("action") or ""  # ej: "payment.created"
    data = payload.get("data") or {}
    payment_id = data.get("id") or payload.get("resource")

    # fallbacks por querystring (?topic=payment&id=...)
    if not ntype:
        ntype = request.query_params.get("topic") or ""
    if not payment_id:
        payment_id = request.query_params.get("id")

    # Algunas integraciones envían 'action' sin 'type'
    if not ntype and action.startswith("payment."):
        ntype = "payment"

    if ntype in {"payment", "merchant_order"} and payment_id:
        # 4) obtener pago desde MP
        try:
            pinfo = sdk.payment().get(payment_id)
        except Exception as e:
            return _ok({"status": "mp-api-error", "error": repr(e), "step": "payment.get"})

        resp = (pinfo.get("response") or {})
        status = (resp.get("status") or "").lower()
        ext_ref = resp.get("external_reference")
        metadata = resp.get("metadata") or {}
        payer = resp.get("payer") or {}

        # datos útiles
        currency = resp.get("currency_id")
        amount = resp.get("transaction_amount") or (resp.get("order") or {}).get("total_amount")
        paid_at = resp.get("date_approved") or resp.get("money_release_date")
        email = metadata.get("email") or payer.get("email")

        # user hints
        meta_uid = metadata.get("user_id")
        try:
            meta_uid = int(meta_uid) if meta_uid is not None else None
        except Exception:
            meta_uid = None

        uid_ext, email_ext = _parse_user_from_external_reference(ext_ref)
        candidate_email = email or email_ext
        candidate_uid = meta_uid or uid_ext
        user = _resolve_user(db, user_id=candidate_uid, email=candidate_email)

        # 5) activar PRO si aprobado
        approved = (status == "approved")
        if approved and user:
            try:
                activate_pro(db, user_id=user.id, payment_id=str(payment_id), days=PLAN_PRO_DAYS)
            except Exception as e:
                # Log suave; igual registramos el pago
                print("[webhooks] activate_pro error:", e)

        # 6) registrar/actualizar pago
        try:
            _upsert_payment(
                db,
                payment_id=str(payment_id),
                user_id=(user.id if user else None),
                email=(getattr(user, "email", None) or candidate_email),
                status=status,
                currency=currency,
                amount=amount,
                external_reference=ext_ref,
                paid_at=paid_at,
                raw=resp,
            )
        except Exception as e:
            print("[webhooks] upsert_payment error:", e)

        return _ok(
            {
                "status": "ok",
                "approved": approved,
                "user_found": bool(user),
                "user_id": (user.id if user else None),
                "email": (user.email if user else candidate_email),
                "payment_id": str(payment_id),
            }
        )

    return _ok({"status": "ignored"})
