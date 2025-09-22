# app/routers/payments.py
import os, json, requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import get_current_user_cookie

router = APIRouter(tags=["payments"])

# ====== ENV ======
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")

# Usa PUBLIC_BASE_URL o (SITE_URL/site_url). Debe ser https y sin slash final.
BASE_URL = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("SITE_URL")
    or os.getenv("site_url")
    or "https://www.alerttrail.com"
).rstrip("/")

WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "change-me")

# PRO
PLAN_PRICE    = float(os.getenv("PRO_PRICE_MONTH") or os.getenv("PLAN_PRICE", "10"))
PLAN_CURRENCY = os.getenv("PLAN_CURRENCY", "USD")   # ARS o USD

# EMPRESAS (acepta varios nombres)
EMPRESAS_PRICE = float(
    os.getenv("EMPRESAS_PRICE_MONTH")
    or os.getenv("BUSINESS_PRICE_MONTH")
    or os.getenv("ENTERPRISE_PRICE_MONTH")
    or "49"
)

# ====== Helpers ======
def _uid_email_from(user):
    """Acepta ORM User o dict con claims."""
    uid = getattr(user, "id", None)
    email = getattr(user, "email", None)
    if isinstance(user, dict):
        uid = user.get("user_id") or user.get("id") or user.get("uid") or uid
        email = user.get("email") or email
    try:
        uid = int(uid) if uid is not None else None
    except Exception:
        pass
    return uid, email

def _norm_plan(plan: str) -> str:
    p = (plan or "PRO").strip().upper()
    if p in {"EMPRESAS", "BUSINESS", "ENTERPRISE", "EMPRESA"}:
        return "EMPRESAS"
    return "PRO"

def _plan_config(plan: str):
    p = _norm_plan(plan)
    if p == "EMPRESAS":
        return {"plan": "EMPRESAS", "title": "AlertTrail EMPRESAS (mensual)", "unit_price": EMPRESAS_PRICE}
    return {"plan": "PRO", "title": "AlertTrail PRO (mensual)", "unit_price": PLAN_PRICE}

def _create_preference(user, plan: str = "PRO", seats: int = 1) -> dict:
    if not MP_TOKEN:
        raise RuntimeError("MP_ACCESS_TOKEN no configurado")

    uid, email = _uid_email_from(user)
    cfg = _plan_config(plan)
    qty = max(1, int(seats or 1))

    body = {
        "items": [{
            "title": cfg["title"],
            "quantity": qty,
            "unit_price": cfg["unit_price"],
            "currency_id": PLAN_CURRENCY
        }],
        "payer": ({"email": email} if email else {}),
        "metadata": {
            "user_id": uid,
            "user_email": email,
            "plan": cfg["plan"],
            "seats": qty
        },
        "back_urls": {
            "success": f"{BASE_URL}/billing/success",
            "pending": f"{BASE_URL}/billing/pending",
            "failure": f"{BASE_URL}/billing/failure"
        },
        "auto_return": "approved",
        "notification_url": f"{BASE_URL}/mp/webhook?secret={WEBHOOK_SECRET}",
        # Importante: NO usamos "purpose": "wallet_purchase" para no bloquear el botón de pagar.
    }

    r = requests.post(
        "https://api.mercadopago.com/checkout/preferences",
        headers={"Authorization": f"Bearer {MP_TOKEN}", "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=20
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Error creando preferencia MP: {r.status_code} {r.text}")
    return r.json()

def _checkout_redirect(user, db, plan: str = "PRO", seats: int = 1):
    pref = _create_preference(user, plan=plan, seats=seats)
    url = pref.get("init_point") or pref.get("sandbox_init_point") or ""
    if not url:
        raise HTTPException(status_code=500, detail="No se obtuvo URL de checkout")
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

# ====== Endpoints ======
@router.get("/billing/checkout")
def billing_checkout_get(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    return _checkout_redirect(user, db, plan=plan, seats=seats)

@router.get("/billing/checkout/empresas")
def billing_checkout_empresas(
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    return _checkout_redirect(user, db, plan="EMPRESAS", seats=1)

@router.post("/billing/checkout")
def billing_checkout_post(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    pref = _create_preference(user, plan=plan, seats=seats)
    url = pref.get("init_point") or pref.get("sandbox_init_point") or ""
    return {"checkout_url": url}

@router.get("/billing/success", response_class=HTMLResponse)
def billing_success():
    return """
    <h2>¡Pago iniciado con éxito!</h2>
    <p>Si tu pago fue aprobado, activaremos tu plan en segundos cuando llegue el webhook.</p>
    <p>Si no se activó automáticamente, refrescá el dashboard en unos instantes.</p>
    """

@router.get("/billing/pending", response_class=HTMLResponse)
def billing_pending():
    return "<h2>Pago pendiente</h2><p>Cuando se acredite, tu plan se activará automáticamente.</p>"

@router.get("/billing/failure", response_class=HTMLResponse)
def billing_failure():
    return "<h2>Pago cancelado o fallido</h2><p>Podés intentar nuevamente desde tu dashboard.</p>"

@router.post("/mp/webhook")
async def mp_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Valida secret simple
    secret = request.query_params.get("secret")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # 2) Lee el evento
    data = await request.json()
    topic = data.get("type") or data.get("topic")
    payment_id = data.get("data", {}).get("id") or data.get("id")

    if topic != "payment" or not payment_id:
        return JSONResponse({"ok": True, "skip": "not a payment or no id"}, status_code=200)

    # 3) Consulta el pago en MP
    pr = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {MP_TOKEN}"},
        timeout=20
    )
    if pr.status_code != 200:
        return JSONResponse({"ok": False, "error": "payment lookup failed"}, status_code=200)

    p = pr.json()
    status_mp = (p.get("status") or "").lower()
    metadata  = p.get("metadata") or {}
    user_id   = metadata.get("user_id")

    # 4) Plan desde metadata (default PRO; normaliza sinónimos)
    plan_meta = (metadata.get("plan") or "PRO").upper()
    if plan_meta in {"BUSINESS", "ENTERPRISE", "EMPRESA"}:
        plan_meta = "EMPRESAS"
    if plan_meta not in {"PRO", "EMPRESAS"}:
        plan_meta = "PRO"

    try:
        seats = int(metadata.get("seats") or 1)
    except Exception:
        seats = 1

    # 5) Activar plan si está aprobado
    if status_mp == "approved" and user_id:
        from ..models import User  # import local para evitar problemas en el arranque
        user = db.query(User).get(user_id)
        if user:
            try:
                user.plan = plan_meta
                # si luego guardás seats: user.plan_seats = seats
                db.commit()
            except Exception as e:
                db.rollback()
                print("DB error setting plan:", e)
        return {"ok": True, "user_id": user_id, "plan": plan_meta, "seats": seats}

    return {"ok": True, "status": status_mp, "user_id": user_id}
