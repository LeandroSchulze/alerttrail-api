# app/services/analysis_service.py
import re
from collections import defaultdict
from typing import Optional
from app.services.notify import notify_all

# Regex mejorados y nuevos
SSH_FAIL_RE = re.compile(
    r"Failed password for (invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2"
)
SSH_OK_RE = re.compile(
    r"Accepted password for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2"
)

# SQLi: Ahora detecta con o sin comillas, y más palabras clave
SQLI_RE = re.compile(r"('|\"|%27|%22)\s*(OR|SELECT|UNION|INSERT|DELETE|DROP|UPDATE).*", re.I)
# XSS: Más completo
XSS_RE = re.compile(r"<script.*?>|onerror=|onload=|alert\(", re.I)
# NUEVO: Path Traversal (../)
TRAVERSAL_RE = re.compile(r"\.\.\/|\.\.\\", re.I)
# NUEVO: Phishing y dominios sospechosos
PHISHING_RE = re.compile(r"(alerttrail|google|mercadopago).*(secure|verify|login|update).*\.(net|org|xyz|info)", re.I)
# NUEVO: Shells y comandos (nc, bash, base64)
SHELL_RE = re.compile(r"(nc\s+-e|bash\s+-i|/bin/sh|base64:)", re.I)

def analyze_log(
    text: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    findings = []
    stats = defaultdict(int)
    fail_by_ip = defaultdict(int)

    for ln in lines:
        # SSH
        if m := SSH_FAIL_RE.search(ln):
            stats["ssh_failed"] += 1
            fail_by_ip[m.group("ip")] += 1
        
        if SSH_OK_RE.search(ln):
            stats["ssh_accepted"] += 1

        # Amenazas Web / Inyecciones
        if SQLI_RE.search(ln):
            stats["sqli"] += 1
            findings.append({"type": "SQLi", "line": ln})

        if XSS_RE.search(ln):
            stats["xss"] += 1
            findings.append({"type": "XSS", "line": ln})

        if TRAVERSAL_RE.search(ln):
            stats["traversal"] += 1
            findings.append({"type": "Path Traversal", "line": ln})
            
        if PHISHING_RE.search(ln):
            stats["phishing"] += 1
            findings.append({"type": "Phishing Link", "line": ln})

        if SHELL_RE.search(ln):
            stats["shell"] += 1
            findings.append({"type": "Malicious Payload", "line": ln})

    stats["bruteforce_ips"] = sum(1 for c in fail_by_ip.values() if c >= 5)
    risk = _compute_risk(stats)

    summary = {
        "ssh_failed": stats["ssh_failed"],
        "ssh_accepted": stats["ssh_accepted"],
        "sqli": stats["sqli"],
        "xss": stats["xss"],
        "traversal": stats.get("traversal", 0),
        "phishing": stats.get("phishing", 0),
        "shell": stats.get("shell", 0),
        "bruteforce_ips": stats["bruteforce_ips"],
        "risk": risk,
    }

    if risk in ("medium", "high") and user_id:
        notify_all(
            user_id=user_id,
            to_email=user_email,
            subject="⚠️ Alerta de seguridad",
            body=f"Se detectó actividad sospechosa (Riesgo: {risk.upper()}).",
            extra={"risk": risk, "stats": summary},
        )

    return {"summary": summary, "findings": findings}

def _compute_risk(s):
    score = 0
    score += s["ssh_failed"] * 1
    score += s["bruteforce_ips"] * 5
    score += s["sqli"] * 5
    score += s.get("traversal", 0) * 5 # Riesgo alto
    score += s.get("shell", 0) * 8     # Riesgo crítico
    score += s["xss"] * 2
    score += s.get("phishing", 0) * 3
    
    if score >= 10: return "high"
    if score >= 4: return "medium"
    return "low"
