import re
from typing import Dict

# Simple, extendable analysis
def analyze_log(raw: str) -> Dict[str, int | bool | str]:
    findings = {
        "failed_logins": len(re.findall(r"failed\s+login|401|unauthorized", raw, flags=re.I)),
        "sql_injection": len(re.findall(r"(union\s+select|or\s+1=1|--\s)", raw, flags=re.I)),
        "xss": len(re.findall(r"<script>|onerror=|javascript:", raw, flags=re.I)),
        "path_traversal": len(re.findall(r"\.\./|/etc/passwd", raw, flags=re.I)),
    }
    risk = "low"
    score = sum(3 if k == "sql_injection" else 2 if k == "xss" else 1 for k,v in findings.items() if isinstance(v,int) and v>0)
    if score >= 6: risk = "high"
    elif score >= 3: risk = "medium"
    findings["risk"] = risk
    return findings

def format_result(findings: Dict[str, int | str]) -> str:
    lines = [f"Riesgo: {findings.get('risk','low').upper()}\n"]
    for k,v in findings.items():
        if k == "risk": continue
        lines.append(f" - {k}: {v}")
    return "\n".join(lines)
