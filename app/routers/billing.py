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

# ⚠️ IMPORT RESILIENTE: si el SDK no está, igual montamos el router
try:
    import mercadopago  # type: ignore
except Exception as _mp_err:
    mercadopago = None
    print("[billing] mercadopago SDK no disponible:", _mp_err)

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

def _sdk():
    """
    Devuelve el SDK de MP o lanza HTTP 503 si falta algo.
    NOTA: hoy este router redirige a /payments/subscribe, pero dejamos
    el helper por si más adelante se usa SDK desde acá.
    """
    if mercadopago is None:
        raise HTTPException(status_code=503, detail="SDK Mercado Pago no instalado")
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="MP_ACCESS_TOKEN no configurado")
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
        "<button style='padding:10px 14px;border:0;border-radius:10px;background:#fbbf24;color:#3a2a00;font-weight:700;cursor:pointer'>Bajar a FREE</button></form>"
    ) if not is_free else ""

    html = f"""
    <!doctype html><html lang="es"><meta charset="utf-8"><title>Plan | AlertTrail</title>
    <body style="font-family:system-ui;background:#0b2133;color:#e5f2ff;margin:0">
      <div style="max-width:980px;margin:40px auto;padding:0 16px">
        <p><a href="/dashboard" style="color:#9ed0ff;text-decoration:none">← Volver al dashboard</a></p>
        <h1 style="margin:0 0 16px">Tu plan</h1>
        <div style="display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">
          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">{current_title}</h2>
            <p style="margin:0 0 12px;color:#bcd7f0">Estado actual: <b>{plan}</b></p>
            {downgrade_btn}
          </div>
          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">PRO</h2>
            <ul style="color:#bcd7f0;margin:6px 0 12px"><li>Funciones avanzadas</li><li>Integraciones clave</li></ul>
            <div style="display:flex;gap:10px;flex-wrap:wrap">{pro_cta}</div>
          </div>
          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">EMPRESAS</h2>
            <ul style="color:#bcd7f0;margin:6px 0 12px">
              <li>Todo PRO + capacidades de equipo</li>
              <li><b>{seats}</b> asientos incluidos</li>
              <li>Asiento adicional: <b>USD {extra_usd:.2f}</b> (~${extra_ars:,.0f} ARS)</li>
            </ul>
            <div style="display:flex;gap:10px;flex-wrap:wrap">{biz_cta}</div>
          </div>
        </div>
        <div style="margin-top:22px"><a href="/billing/subscriptions" style="color:#9ed0ff">Ver mis suscripciones</a></div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

# ---------- Crear/ir a suscripción ----------
@router.post("/checkout")
def billing_checkout(
    request: Request,
    plan: str = Query(..., regex="^(?i)(PRO|BIZ)$"),
    seats: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    # Redirigimos al flujo real en payments.py (este router no llama SDK directo)
    return RedirectResponse(url=f"/payments/subscribe?plan={plan.upper()}&seats={seats}", status_code=303)

# ---------- Downgrade rápido ----------
@router.post("/downgrade")
def billing_downgrade(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    try:
        u = db.query(models.User).get(_as_user_attr(user).id)
        if not u:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        _set_plan(u, "FREE")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return RedirectResponse(url="/billing", status_code=303)

# ---------- Vista de suscripciones ----------
@router.get("/subscriptions", response_class=HTMLResponse, name="billing_subscriptions")
def billing_subscriptions(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    email: Optional[str] = Query(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    user = _as_user_attr(user)

    # asegurar tabla
    try:
        _ = db.query(Subscription).first()
    except OperationalError as e:
        if "no such table: subscriptions" in str(e).lower():
            _ensure_subscriptions_table(db)
        else:
            raise

    # Construir query
    q = db.query(Subscription)
    if getattr(user, "role", "user") != "admin":
        q = q.filter(Subscription.user_id == getattr(user, "id", None))
    else:
        # si viene ?email= filtrar por el user_id de ese email
        if email:
            target = db.query(models.User).filter(models.User.email.ilike(email)).first()
            if target:
                q = q.filter(Subscription.user_id == target.id)
            else:
                q = q.filter(Subscription.user_id == -1)  # no resultados

    rows = q.order_by(Subscription.updated_at.desc()).limit(100).all()

    # Render con template si existe, si no fallback con formularios admin
    try:
        return templates.TemplateResponse(
            "billing_subscriptions.html",
            {"request": request, "user": user, "subs": rows, "email": email or ""},
        )
    except TemplateNotFound:
        th_user = "<th>Usuario</th>" if getattr(user, "role", "user") == "admin" else ""
        def td_user(r):
            return f"<td>{getattr(r, 'user_id', '-') or '-'}</td>" if getattr(user, "role", "user") == "admin" else ""
        body = "".join(
            f"<tr>{td_user(r)}"
            f"<td>{r.preapproval_id}</td>"
            f"<td>{(r.plan or '').upper()}</td>"
            f"<td><span style='background:#103a2f;color:#bfffe5;padding:3px 8px;border-radius:8px'>{(r.status or '').lower()}</span></td>"
            f"<td>{r.currency} {r.amount}</td>"
            f"<td>{r.next_payment_date or '-'}</td>"
            f"<td><a href='/billing/subscriptions/sync?preapproval_id={r.preapproval_id}' style='color:#9ed0ff'>Actualizar</a></td>"
            f"</tr>"
            for r in rows
        )
        admin_tools = ""
        if getattr(user, "role", "user") == "admin":
            admin_tools = """
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">
              <form method="get" action="/billing/subscriptions">
                <input type="email" name="email" placeholder="filtrar por email" style="padding:8px;border-radius:8px;border:1px solid #133954;background:#0b1f2f;color:#eaf3ff" />
                <button style="padding:8px 12px;border-radius:8px;border:0;background:#0ea5e9;color:#03131c;font-weight:700">Filtrar</button>
              </form>
              <form method="get" action="/billing/subscriptions/sync">
                <input type="text" name="preapproval_id" placeholder="preapproval_id" style="padding:8px;border-radius:8px;border:1px solid #133954;background:#0b1f2f;color:#eaf3ff" />
                <button style="padding:8px 12px;border-radius:8px;border:0;background:#10b981;color:#06241f;font-weight:700">Sincronizar</button>
              </form>
            </div>
            """
        html = f"""
        <!doctype html><html lang="es"><meta charset="utf-8"><title>Suscripciones | AlertTrail</title>
        <body style="font-family:system-ui;background:#0b1f2f;color:#eaf3ff;margin:0">
          <div style="max-width:980px;margin:40px auto;padding:0 16px">
            <p><a href="/dashboard" style="color:#9ed0ff;text-decoration:none">← Volver al dashboard</a></p>
            <h1>Suscripciones</h1>
            {admin_tools}
            <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
              {"<p>No hay suscripciones registradas.</p>" if not rows else
              f"<table style='width:100%;border-collapse:collapse'><thead><tr>{th_user}<th>Preapproval ID</th><th>Plan</th><th>Estado</th><th>Monto</th><th>Próximo pago</th><th>Acciones</th></tr></thead><tbody>{body}</tbody></table>"}
            </div>
          </div>
        </body>
        </html>
        """
        return HTMLResponse(html)

# ---------- Acción: sync por preapproval_id y volver a la tabla ----------
@router.get("/subscriptions/sync")
def billing_subscriptions_sync(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    # asegurar tabla
    try:
        _ = db.query(Subscription).first()
    except OperationalError as e:
        if "no such table: subscriptions" in str(e).lower():
            _ensure_subscriptions_table(db)
        else:
            raise
    # hacer sync y volver a la lista
    try:
        _sync_preapproval(db, preapproval_id=preapproval_id)
    except Exception as e:
        # aunque falle, no bloquear la UX: volvemos a la página
        print("[billing] sync fallo:", e)
    return RedirectResponse(url="/billing/subscriptions", status_code=303)
