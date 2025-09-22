# app/routers/payments.py
import os, json, requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import get_current_user_cookie

router = APIRouter(tags=["payments"])

MP_TOKEN         = os.getenv("MP_ACCESS_TOKEN", "")
BASE_URL         = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
WEBHOOK_SECRET   = os.getenv("MP_WEBHOOK_SECRET", "change-me")
PLAN_PRICE       = float(os.getenv("PLAN_PRICE", "10"))
PLAN_CURRENCY    = os.getenv("PLAN_CURRENCY", "USD")

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
def billing_checkout_get(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    """
    Soporta GET para que el botón/anchor funcione.
    Crea la preferencia y redirige al init_point de MP.
    """
    pref = _create_preference(user)
    url = pref.get("init_point") or pref.get("sandbox_init_point") or pref.get("init_point", "")
    if not url:
        raise HTTPException(status_code=500, detail="No se obtuvo URL de checkout")
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

@router.post("/billing/checkout")
def billing_checkout_post(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    """
    Variante POST por si querés llamarla vía fetch y luego redirigir desde el front.
    Devuelve la URL de checkout.
    """
    pref = _create_preference(user)
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
    # Validación simple del secret
    secret = request.query_params.get("secret")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    data = await request.json()
    # MP puede mandar varios formatos; cubrimos casos comunes
    topic = data.get("type") or data.get("topic")
    payment_id = None

    if topic == "payment":
        payment_id = data.get("data", {}).get("id") or data.get("id")
    elif topic == "merchant_order":
        # Podrías manejar merchant_order si lo configuraste así
        pass

    if not payment_id:
        return JSONResponse({"ok": True, "skip": "no payment id"}, status_code=200)

    # Consultar detalle del pago
    pr = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {MP_TOKEN}"},
        timeout=20
    )
    if pr.status_code != 200:
        return JSONResponse({"ok": False, "error": "payment lookup failed"}, status_code=200)

    p = pr.json()
    status_mp = p.get("status")                   # approved, rejected, pending, in_process...
    metadata  = p.get("metadata") or {}
    user_id   = metadata.get("user_id")

    if status_mp == "approved" and user_id:
        user = db.query(User).get(user_id)
        if user:
            # activar PRO
            try:
                user.plan = "PRO"
                db.commit()
            except Exception as e:
                db.rollback()
                print("DB error setting PRO:", e)
        return {"ok": True, "user_id": user_id, "plan": "PRO"}

    return {"ok": True, "status": status_mp, "user_id": user_id}
