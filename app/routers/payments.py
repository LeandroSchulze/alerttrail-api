# app/routers/payments.py
import os, json, requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import get_current_user_cookie

router = APIRouter(tags=["payments"])

MP_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
BASE_URL = (...)  # la que ya tenés con PUBLIC_BASE_URL / SITE_URL
WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "change-me")
PLAN_PRICE    = float(os.getenv("PRO_PRICE_MONTH") or os.getenv("PLAN_PRICE", "10"))
PLAN_CURRENCY = os.getenv("PLAN_CURRENCY", "USD")

def _uid_email_from(user):
    # Soporta User ORM o dict con claims
    uid = getattr(user, "id", None)
    email = getattr(user, "email", None)

    if isinstance(user, dict):
        uid = user.get("user_id") or user.get("id") or user.get("uid") or uid
        email = user.get("email") or email

    # normaliza tipos
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
        return {
            "plan": "EMPRESAS",
            "title": "AlertTrail EMPRESAS (mensual)",
            "unit_price": EMPRESAS_PRICE,
        }
    return {
        "plan": "PRO",
        "title": "AlertTrail PRO (mensual)",
        "unit_price": PLAN_PRICE,
    }
    
def _create_preference(user: "User|dict", plan: str = "PRO", seats: int = 1) -> dict:
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
        # Quitar "purpose": "wallet_purchase" para evitar bloqueos innecesarios
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

    r = requests.post(
        "https://api.mercadopago.com/checkout/preferences",
        headers={"Authorization": f"Bearer {MP_TOKEN}",
                 "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=20
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Error creando preferencia MP: {r.status_code} {r.text}")
    return r.json()

    r = requests.post(
        "https://api.mercadopago.com/checkout/preferences",
        headers={"Authorization": f"Bearer {MP_TOKEN}",
                 "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=20
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Error creando preferencia MP: {r.status_code} {r.text}")
    return r.json()

# ---------- CHECKOUT ----------
@router.get("/billing/checkout")
def _checkout_redirect(user, db, plan: str = "PRO", seats: int = 1):
    pref = _create_preference(user, plan=plan, seats=seats)
    url = pref.get("init_point") or pref.get("sandbox_init_point") or ""
    if not url:
        raise HTTPException(status_code=500, detail="No se obtuvo URL de checkout")
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

@router.get("/billing/checkout")
def billing_checkout_get(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    return _checkout_redirect(user, db, plan=plan, seats=seats)

# Alias cómodo para el botón “Plan Empresas”
@router.get("/billing/checkout/empresas")
def billing_checkout_empresas(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    return _checkout_redirect(user, db, plan="EMPRESAS", seats=1)

@router.post("/billing/checkout")
def billing_checkout_post(
    plan: str = "PRO",
    seats: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    pref = _create_preference(user, plan=plan, seats=seats)
    url = pref.get("init_point") or pref.get("sandbox_init_point") or ""
    return {"checkout_url": url}

# ---------- PÁGINAS DE RETORNO ----------
@router.get("/billing/success", response_class=HTMLResponse)
def billing_success():
    return """
    <h2>¡Pago iniciado con éxito!</h2>
    <p>Si tu pago fue aprobado, activaremos tu plan PRO en segundos (al llegar el webhook).</p>
    <p>Si no se activó automáticamente, actualiza el dashboard en unos instantes.</p>
    """

@router.get("/billing/pending", response_class=HTMLResponse)
def billing_pending():
    return "<h2>Pago pendiente</h2><p>Cuando se acredite, tu plan PRO se activará automáticamente.</p>"

@router.get("/billing/failure", response_class=HTMLResponse)
def billing_failure():
    return "<h2>Pago cancelado o fallido</h2><p>Podés intentar nuevamente desde tu dashboard.</p>"

# ---------- WEBHOOK ----------
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

    # Solo procesamos pagos con id válido
    if topic != "payment" or not payment_id:
        return JSONResponse({"ok": True, "skip": "not a payment or no id"}, status_code=200)

    # 3) Consulta el pago en MP (necesitamos status y metadata)
    pr = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {MP_TOKEN}"},
        timeout=20
    )
    if pr.status_code != 200:
        return JSONResponse({"ok": False, "error": "payment lookup failed"}, status_code=200)

    p = pr.json()
    status_mp = (p.get("status") or "").lower()            # approved / rejected / pending / ...
    metadata  = p.get("metadata") or {}
    user_id   = metadata.get("user_id")

    # 4) Plan según metadata (default PRO); aceptamos sinónimos
    plan_meta = (metadata.get("plan") or "PRO").upper()
    if plan_meta in {"BUSINESS", "ENTERPRISE", "EMPRESA"}:
        plan_meta = "EMPRESAS"
    if plan_meta not in {"PRO", "EMPRESAS"}:
        plan_meta = "PRO"

    # (opcional) seats por si lo usás más adelante
    try:
        seats = int(metadata.get("seats") or 1)
    except Exception:
        seats = 1

    # 5) Si el pago quedó aprobado, activamos plan para ese user_id
    if status_mp == "approved" and user_id:
        from ..models import User  # import local para no romper arranque si cambia el modelo
        user = db.query(User).get(user_id)
        if user:
            try:
                user.plan = plan_meta
                # si en el futuro guardás seats: user.plan_seats = seats
                db.commit()
            except Exception as e:
                db.rollback()
                print("DB error setting plan:", e)
        return {"ok": True, "user_id": user_id, "plan": plan_meta, "seats": seats}

    # 6) Para otros estados respondemos 200 para que MP no reintente indefinidamente
    return {"ok": True, "status": status_mp, "user_id": user_id}
