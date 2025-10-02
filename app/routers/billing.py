# app/routers/billing.py
import os
from typing import Optional, Tuple
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import mercadopago

from app.database import get_db
from app import models
from app.security import get_current_user_cookie

# Modelo y sync interno desde payments.py
from .payments import Subscription, _sync_preapproval  # usamos el helper interno

router = APIRouter(prefix="/billing", tags=["billing"])

# ======== ENV & templates ========
BASE_URL = (os.getenv("BASE_URL") or "https://www.alerttrail.com").rstrip("/")
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()

APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---------- Helpers ----------
def _parse_float(v: Optional[str], default: float) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _is_pro(u) -> bool:
    return bool(getattr(u, "is_pro", False)) or (getattr(u, "plan", "free") or "free").lower() in {"pro", "biz"}

def _set_plan(u: models.User, plan: str):
    p = (plan or "free").lower()
    if hasattr(u, "plan"):
        u.plan = p.upper() if p in ("free", "pro", "biz") else p
    if hasattr(u, "is_pro"):
        u.is_pro = (p in {"pro", "biz"})

def _sdk() -> mercadopago.SDK:
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN en variables de entorno")
    return mercadopago.SDK(MP_ACCESS_TOKEN)

def _as_user_attr(obj):
    """Convierte dict en objeto con attrs (id/role) para evitar AttributeError en plantillas."""
    if isinstance(obj, dict):
        d = dict(obj)
        if "id" not in d:
            d["id"] = d.get("user_id") or d.get("uid")
        if "role" not in d and d.get("is_admin"):
            d["role"] = "admin"
        return SimpleNamespace(**d)
    return obj

def _ensure_subscriptions_table(db: Session):
    """Crea la tabla subscriptions si no existe (sqlite/postgres)."""
    eng = db.get_bind()
    dialect = getattr(eng.dialect, "name", "sqlite")
    if dialect == "sqlite":
        ddl = """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            preapproval_id VARCHAR UNIQUE,
            status VARCHAR,
            "plan" VARCHAR,
            seats INTEGER DEFAULT 1,
            currency VARCHAR DEFAULT 'USD',
            amount INTEGER,
            next_payment_date VARCHAR,
            external_reference VARCHAR,
            raw TEXT,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_preapproval_id ON subscriptions(preapproval_id);
        CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions(status);
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            preapproval_id VARCHAR UNIQUE,
            status VARCHAR,
            "plan" VARCHAR,
            seats INTEGER DEFAULT 1,
            currency VARCHAR DEFAULT 'USD',
            amount INTEGER,
            next_payment_date VARCHAR,
            external_reference VARCHAR,
            raw TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_preapproval_id ON subscriptions(preapproval_id);
        CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions(status);
        """
    for stmt in ddl.split(";"):
        s = stmt.strip()
        if s:
            db.execute(text(s))
    db.commit()

def _compute_price_pro() -> Tuple[str, float, str]:
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    price = _parse_float(os.getenv("PLAN_PRICE"), 10.0)
    usd_ars = _parse_float(os.getenv("USD_ARS"), 600.0)
    override_mp = os.getenv("MP_PRICE_ARS") or os.getenv("PRO_PRICE_ARS")
    if currency == "USD":
        mp_amount_ars = _parse_float(override_mp, round(price * usd_ars))
        label = f"Mejorar a PRO (USD {price:.2f}/mes · ~${mp_amount_ars:,.0f} ARS)".replace(",", ".")
    else:
        mp_amount_ars = _parse_float(override_mp, price)
        label = f"Mejorar a PRO (${mp_amount_ars:,.0f}/mes)".replace(",", ".")
    title = "AlertTrail PRO - 1 mes"
    return label, float(mp_amount_ars), title

def _compute_price_biz() -> Tuple[str, float, str, int, float, float]:
    seats = int(os.getenv("BIZ_INCLUDED_SEATS") or 25)
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    price_usd = _parse_float(os.getenv("BIZ_PRICE_USD"), 99.0)
    usd_ars = _parse_float(os.getenv("USD_ARS"), 600.0)
    extra_usd = _parse_float(os.getenv("BIZ_EXTRA_SEAT_USD"), 3.0)
    extra_ars_override = os.getenv("BIZ_EXTRA_SEAT_ARS")
    override_biz_ars = os.getenv("BIZ_PRICE_ARS")
    if currency == "USD":
        mp_amount_ars = _parse_float(override_biz_ars, round(price_usd * usd_ars))
        extra_ars = _parse_float(extra_ars_override, round(extra_usd * usd_ars))
        label = (
            f"Plan EMPRESAS (USD {price_usd:.2f}/mes · ~${mp_amount_ars:,.0f} ARS · {seats} asientos, "
            f"adicional USD {extra_usd:.2f}/asiento)".replace(",", ".")
        )
    else:
        base_ars = _parse_float(os.getenv("PLAN_PRICE"), price_usd * usd_ars)
        mp_amount_ars = _parse_float(override_biz_ars, base_ars)
        extra_ars = _parse_float(extra_ars_override, round(extra_usd * usd_ars))
        label = (
            f"Plan EMPRESAS (${mp_amount_ars:,.0f}/mes · {seats} asientos, "
            f"adicional ~${extra_ars:,.0f}/asiento)".replace(",", ".")
        )
    title = "AlertTrail EMPRESAS - 1 mes"
    return label, float(mp_amount_ars), title, seats, float(extra_usd), float(extra_ars)

# ---------- UI ----------
@router.get("", response_class=HTMLResponse, name="billing_page")
def billing_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_cookie(request, db=db)
    except Exception:
        return RedirectResponse(url="/auth/login", status_code=303)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    user = _as_user_attr(user)

    plan = (getattr(user, "plan", "FREE") or "FREE").upper()
    is_pro = _is_pro(user)
    is_biz = (plan == "BIZ")
    is_plan_pro = (plan == "PRO")
    is_free = (plan == "FREE")

    pro_label, _, _ = _compute_price_pro()
    biz_label, _, _, seats, extra_usd, extra_ars = _compute_price_biz()
    current_title = plan

    pro_cta = (
        "<span style='display:inline-block;padding:8px 10px;border-radius:10px;background:#083344;color:#a7f3d0;font-weight:700'>Plan activo</span>"
        if is_plan_pro else
        f"<form method='post' action='/billing/checkout?plan=PRO'>"
        f"<button style='padding:10px 14px;border:0;border-radius:10px;background:#10b981;color:#06241f;font-weight:700;cursor:pointer'>{pro_label}</button></form>"
    )
    biz_cta = (
        "<span style='display:inline-block;padding:8px 10px;border-radius:10px;background:#082f49;color:#bae6fd;font-weight:700'>Plan activo</span>"
        if is_biz else
        f"<form method='post' action='/billing/checkout?plan=BIZ&seats={seats}'>"
        f"<button style='padding:10px 14px;border:0;border-radius:10px;background:#0ea5e9;color:#03131c;font-weight:700;cursor:pointer'>{biz_label}</button></form>"
    )
    downgrade_btn = (
        "<form method='post' action='/billing/downgrade'>"
        "<button style='padding:10px 14px;border:0;border-radius:10px;background:#fbbf24;color:#3a2a00;font-weight:700;cursor:pointer'>Bajar a FREE</button></form>
