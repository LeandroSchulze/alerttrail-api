# app/payments/mp_client.py
from __future__ import annotations

import os
import hmac
import hashlib
from typing import Dict, Any, Optional

import httpx

class MPClient:
    """Cliente HTTP mínimo para Mercado Pago (suficiente para webhooks)."""
    def __init__(self, access_token: str):
        self.base = "https://api.mercadopago.com"
        self._token = (access_token or "").strip()

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base + path
        with httpx.Client(timeout=30) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            r.raise_for_status()
            return r.json()

    # ---------- Firma webhook (opcional) ----------
    @staticmethod
    def verify_signature(raw_body: bytes, provided: str, secret: str) -> bool:
        """Valida firma HMAC-SHA256 si está disponible. Si no, devuelve True."""
        if not secret:
            return True
        if not provided:
            return False
        try:
            # Soporta formatos "sha256=abcd..."
            if "=" in provided:
                algo, sig_hex = provided.split("=", 1)
                algo = algo.strip().lower()
                if algo not in ("sha256", "hmac-sha256"):
                    return True
            else:
                sig_hex = provided.strip()
            mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(mac, sig_hex)
        except Exception:
            return False

class _PaymentAPI:
    def __init__(self, client: MPClient):
        self._c = client

    def get(self, payment_id: str) -> Dict[str, Any]:
        # Formato compatible con SDK oficial: {"response": {...}}
        resp = self._c.get(f"/v1/payments/{payment_id}")
        return {"response": resp}

class _SDK:
    """Shim simple para compatibilidad: sdk.payment().get(id)."""
    def __init__(self):
        token = os.getenv("MP_ACCESS_TOKEN") or os.getenv("MERCADOPAGO_ACCESS_TOKEN") or ""
        self._client = MPClient(token)

    def payment(self) -> _PaymentAPI:
        return _PaymentAPI(self._client)

# Export esperado por app/routers/webhooks.py
sdk = _SDK()
