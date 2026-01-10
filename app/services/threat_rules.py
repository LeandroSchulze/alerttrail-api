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
      - NO traduce texto (i18n se hace en el template)
      - reasons se devuelven como objetos estructurados
      - mantiene compatibilidad con mail_scan.py
    """
    text = f"{subject}\n{sender}\n{body}".lower()
    reasons: List[Dict[str, Any]] = []
    score = 0

    # Links
    urls = re.findall(r"https?://[^\s)>\]]+", text)
    if urls:
        score += 10
        reasons.append({
            "key": "links_count",
            "count": len(urls),
        })

    # Acortadores de URL
    if any(d in text for d in _SUSPICIOUS_DOMAINS):
        score += 15
        reasons.append({
            "key": "url_shortener",
        })

    # Keywords típicas de phishing
    hits = [k for k in _SUSPICIOUS_KEYWORDS if k in text]
    if hits:
        score += min(30, 5 * len(hits))
        reasons.append({
            "key": "phishing_words",
            "words": sorted(set(hits))[:10],
        })

    # Pedido de credenciales (muy básico)
    if "password" in text and any(w in text for w in ("enter", "update", "reset")):
        score += 20
        reasons.append({
            "key": "password_action",
        })

    # Lenguaje de urgencia / presión
    if any(w in text for w in ["urgent", "immediately", "asap", "within 24", "24 hours"]):
        score += 10
        reasons.append({
            "key": "urgency_language",
        })

    # Ajuste final
    score = max(0, min(100, score))
    if score >= 60:
        risk = "high"
    elif score >= 30:
        risk = "medium"
    else:
        risk = "low"

    if not reasons:
        reasons.append({
            "key": "no_signals",
        })

    return {
        "risk": risk,
        "danger_level": risk,
        "score": score,
        "reasons": reasons,
    }
