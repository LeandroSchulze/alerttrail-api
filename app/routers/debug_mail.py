# app/routers/debug_mail.py
from fastapi import APIRouter, HTTPException, Query
from app.mailer import send_email

router = APIRouter(prefix="/debug", tags=["debug"])

@router.get("/send-test-email")
def send_test_email(to: str = Query(..., description="Destino de prueba")):
    try:
        send_email(
            to=to,
            subject="Prueba SMTP — AlertTrail",
            body="¡Hola! Esto es una prueba de envío SMTP desde AlertTrail.",
            html="<p>¡Hola! Esto es una <b>prueba</b> de envío SMTP desde AlertTrail.</p>",
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
