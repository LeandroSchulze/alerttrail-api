# app/services/analysis_service.py
import re
from collections import defaultdict
from typing import Optional
from app.services.notify import notify_all

# Regex de alta precisión
SSH_FAIL_RE = re.compile(r"Failed password for (invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2")
SSH_OK_RE = re.compile(r"Accepted password for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2")

# Detectores Web
SQLI_RE = re.compile(r"('|\"|%27|%22)\s*(OR|SELECT|UNION|INSERT|DELETE|DROP|UPDATE).*", re.I)
XSS_RE = re.compile(r"<script.*?>|onerror=|onload=|alert\(", re.I)
TRAVERSAL_RE = re.compile(r"\.\.\/|\.\.\\|etc/passwd|boot\.ini|/.env", re.I)
PHISHING_RE = re.compile(r"(alerttrail|google|mercadopago).*(secure|verify|login|update).*\.(net|org|xyz|info)", re.I)
SHELL_RE = re.compile(r"(nc\s+-e|bash\s+-i|/bin/sh|base64:)", re.I)

def analyze_log(text: str, *, user_id: Optional[str] = None, user_email: Optional[str] = None) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    
    # Listas para el Dashboard
    sqli_hits = []
    probe_hits = []
    
    stats = defaultdict(int)
    fail_by_ip = defaultdict(int)

    for ln in lines:
        # 1. Fuerza Bruta SSH
        if m := SSH_FAIL_RE.search(ln):
            stats["ssh_failed"] += 1
            fail_by_ip[m.group("ip")] += 1
        
        # 2. Inyecciones SQL
        if SQLI_RE.search(ln):
            stats["sqli"] += 1
            sqli_hits.append(ln)

        # 3. Archivos Sensibles / Traversal
        if TRAVERSAL_RE.search(ln):
            stats["traversal"] += 1
            probe_hits.append(ln)

        # 4. Otras amenazas
        if XSS_RE.search(ln): stats["xss"] += 1
        if PHISHING_RE.search(ln): stats["phishing"] += 1
        if SHELL_RE.search(ln): stats["shell"] += 1

    stats["bruteforce_ips"] = sum(1 for c in fail_by_ip.values() if c >= 5)
    
    # Cálculo de riesgo
    score = (stats["sqli"] * 5) + (stats["traversal"] * 5) + (stats["shell"] * 8) + (stats["ssh_failed"] * 0.5)
    risk = "high" if score >= 10 else "medium" if score >= 4 else "low"

    # Resumen compatible con el Dashboard y el PDF
    summary = {
        "total": len(lines),
        "sqli": stats["sqli"],
        "traversal": stats["traversal"],
        "ssh_failed": stats["ssh_failed"],
        "bruteforce_ips": stats["bruteforce_ips"],
        "risk": risk,
    }

    # Disparar alerta si es necesario
    if risk in ("medium", "high") and user_id:
        notify_all(
            user_id=user_id,
            to_email=user_email,
            subject="⚠️ Alerta de seguridad detectada",
            body=f"Se detectó actividad de riesgo {risk.upper()} en los logs analizados.",
            extra={"risk": risk, "stats": summary},
        )

    return {
        "summary": summary, 
        "findings": sqli_hits + probe_hits, # Para uso general
        "sqli_hits": sqli_hits[:20],        # Específico para tu HTML
        "probe_hits": probe_hits[:20]       # Específico para tu HTML
    }
