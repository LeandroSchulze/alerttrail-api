import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import mercadopago

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "changeme")

PRO_MONTHLY = float(os.getenv("PRO_MONTHLY_USD", "10"))
PRO_ANNUAL  = float(os.getenv("PRO_ANNUAL_USD", "108"))

def _host_url(request: Request) -> str:
    return (PUBLIC_URL or str(request.base_url)).rstrip("/")

def _sdk() -> mercadopago.SDK:
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN")
    return mercadopago.SDK(MP_ACCESS_TOKEN)

@router.get("/checkout")
def checkout(request: Request, plan: str, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    if plan not in {"pro-monthly", "pro-annual"}:
        return JSONResponse({"error": "plan inválido"}, status_code=400)

    price = PRO_MONTHLY if plan == "pro-monthly" else PRO_ANNUAL
    period = "monthly" if plan == "pro-monthly" else "annual"

    base = _host_url(request)
    back = {"success": f"{base}/billing/success",
            "failure": f"{base}/billing/failure",
            "pending": f"{base}/billing/pending"}
    notification_url = f"{base}/billing/webhook?secret={WEBHOOK_SECRET}"

    pref = _sdk().preference().create({
        "items": [{"title": f"AlertTrail PRO ({period})", "quantity": 1,
                   "unit_price": price, "currency_id": os.getenv("MP_CURRENCY","USD")}],
        "payer": {"email": user.email},
        "back_urls": back,
        "auto_return": "approved",
        "notification_url": notification_url,
        "metadata": {"user_email": user.email, "plan": "PRO", "period": period},
    })
    init_point = pref["response"].get("init_point") or pref["response"].get("sandbox_init_point")
    return RedirectResponse(url=init_point, status_code=302)

@router.post("/webhook")
@router.get("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("secret") != WEBHOOK_SECRET:
        return JSONResponse({"status": "forbidden"}, status_code=403)

    sdk = _sdk()
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    topic = request.query_params.get("type") or payload.get("type")
    payment_id = request.query_params.get("data.id") or (payload.get("data") or {}).get("id")
    if (topic or "").lower() != "payment" or not payment_id:
        return JSONResponse({"status": "ignored"})

    resp = sdk.payment().get(payment_id).get("response", {})
    if resp.get("status") == "approved":
        email = (resp.get("metadata") or {}).get("user_email") or (resp.get("payer") or {}).get("email")
        if email:
            user = db.query(User).filter(User.email == email).first()
            if user:
                user.plan = "PRO"; db.add(user); db.commit()
                return JSONResponse({"status": "ok", "user": email, "plan": "PRO"})
    return JSONResponse({"status": "ok"})

@router.get("/success")
def success():  return RedirectResponse(url="/dashboard", status_code=302)
@router.get("/failure")
def failure():  return RedirectResponse(url="/dashboard", status_code=302)
@router.get("/pending")
def pending():  return RedirectResponse(url="/dashboard", status_code=302)
