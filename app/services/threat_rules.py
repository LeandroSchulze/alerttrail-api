# app/services/threat_rules.py
from __future__ import annotations

import re
from typing import Any, Dict, List

_SUSPICIOUS_KEYWORDS = [
    "verify", "verification", "password", "reset", "login", "account",
    "urgent", "immediately", "invoice", "payment", "wire", "bank",
    "suspended", "locked", "security alert",
    "confirm", "update", "billing", "refund",
]
_SUSPICIOUS_DOMAINS = [
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly",
]

def analyze_email_quick(subject: str = "", sender: str = "", body: str = "") -> Dict[str, Any]:
    """
    Analiza rápido un email y devuelve un dict consistente.
    IMPORTANTE:
      - mantiene 'risk' (legacy)
      - agrega 'danger_level' (lo usa mail_scan.py / alertas)
    """
    text = f"{subject}\n{sender}\n{body}".lower()
    reasons: List[str] = []
    score = 0

    # Links
    urls = re.findall(r"https?://[^\s)>\]]+", text)
    if urls:
        score += 10
        reasons.append(f"Contiene {len(urls)} link(s).")

    # Acortadores comunes
    if any(d in text for d in _SUSPICIOUS_DOMAINS):
        score += 15
        reasons.append("Usa acortadores de URL (posible phishing).")

    # Keywords
    hits = [k for k in _SUSPICIOUS_KEYWORDS if k in text]
    if hits:
        score += min(30, 5 * len(hits))
        reasons.append(
            "Palabras típicas de phishing: "
            + ", ".join(sorted(set(hits))[:10])
            + ("..." if len(hits) > 10 else "")
        )

    # Pedido de credenciales (muy básico)
    if "password" in text and ("enter" in text or "update" in text or "reset" in text):
        score += 20
        reasons.append("Menciona contraseña + acción (reset/update).")

    # “Urgencia” / presión
    if any(w in text for w in ["urgent", "immediately", "asap", "within 24", "24 hours"]):
        score += 10
        reasons.append("Lenguaje de urgencia/presión.")

    # Ajuste final
    score = max(0, min(100, score))
    if score >= 60:
        risk = "high"
    elif score >= 30:
        risk = "medium"
    else:
        risk = "low"

    if not reasons:
        reasons.append("Sin señales obvias (análisis rápido).")

    # ✅ CLAVE: agregar danger_level para que mail_scan.py no lo ponga en low siempre
    return {
        "risk": risk,
        "danger_level": risk,
        "score": score,
        "reasons": reasons,
    }
