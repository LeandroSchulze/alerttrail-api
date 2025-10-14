import os
import mercadopago

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
if not MP_ACCESS_TOKEN:
    raise RuntimeError("MP_ACCESS_TOKEN no configurado")

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
