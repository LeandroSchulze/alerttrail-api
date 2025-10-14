# app/payments/mp_client.py
import os
import mercadopago

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
if not MP_ACCESS_TOKEN:
    raise RuntimeError("MP_ACCESS_TOKEN no configurado")

# SDK oficial de Mercado Pago
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
