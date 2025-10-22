# app/services/mp_client.py
from __future__ import annotations

import hmac
import hashlib
import json
from typing import Optional, Dict, Any

import httpx

class MPClient:
    def __init__(self, access_token: str):
        self.base = "https://api.mercadopago.com"
        self._token = access_token.strip()

    # ---------- Low-level ----------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base}{path}"
        with httpx.Client(timeout=20) as client:
            r = client.get(url, headers=self._headers(), params=params)
            if r.status_code // 100 == 2:
                try:
                    return r.json()
                except Exception:
                    return None
            return None

    def _post(self, path: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"{self.base}{path}"
        with httpx.Client(timeout=20) as client:
            r = client.post(url, headers=self._headers(), content=json.dumps(data))
            if r.status_code // 100 == 2:
                try:
                    return r.json()
                except Exception:
                    return None
            return None

    # ---------- High-level ----------
    def create_preference(
        self,
        *,
        title: str,
        unit_price: float,
        currency: str = "USD",
        quantity: int = 1,
        external_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        back_urls: Optional[Dict[str, str]] = None,
        auto_return: Optional[str] = "approved",
        payer: Optional[Dict[str, Any]] = None,
        notification_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "items": [
                {
                    "title": title,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "currency_id": currency,
                }
            ],
            "metadata": metadata or {},
            "back_urls": back_urls or {},
            "auto_return": auto_return or "approved",
            "external_reference": external_reference,
            "payer": payer or {},
        }
        if notification_url:
            payload["notification_url"] = notification_url
        return self._post("/checkout/preferences", payload)

    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        if not payment_id:
            return None
        return self._get(f"/v1/payments/{payment_id}")

    def get_merchant_order(self, mo_id: str) -> Optional[Dict[str, Any]]:
        if not mo_id:
            return None
        return self._get(f"/merchant_orders/{mo_id}")

    # ---------- Webhook signature ----------
    @staticmethod
    def verify_webhook_signature(headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """
        Verifica la firma de webhook de forma genérica con HMAC-SHA256 sobre el body.
        Nota: MP tiene variantes de firma; si usas la cabecera 'X-Signature' con formato 'sha256=...'
        esto cubrirá el caso común. Si en tu cuenta MP usas un esquema distinto, ajusta esta función.
        """
        if not secret:
            return True
        provided = headers.get("x-signature") or headers.get("X-Signature")
        if not provided:
            # Algunas cuentas no envían firma; en ese caso devolvemos True para no bloquear
            return True
        try:
            # Soporta formatos "sha256=abcd..."
            if "=" in provided:
                algo, sig_hex = provided.split("=", 1)
                algo = algo.strip().lower()
                if algo not in ("sha256", "hmac-sha256"):
                    # Algoritmo desconocido: mejor no validar
                    return True
            else:
                sig_hex = provided.strip()
            mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(mac, sig_hex)
        except Exception:
            return False
