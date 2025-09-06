from typing import Dict
import re

COMMON_ATTACKS = {
    "sql_injection": re.compile(r"(union\s+select|or\s+1=1|--|;\s*drop\s+table)", re.I),
    "xss": re.compile(r"(<script|onerror=|javascript:)", re.I),
    "path_traversal": re.compile(r"(\.\./|/etc/passwd)", re.I),
    "auth_fail": re.compile(r"(failed\s+login|invalid\s+password)", re.I),
}

def analyze_log(raw_log: str, use_ai: bool = False) -> Dict:
    findings = []
    score = 0

    for name, pattern in COMMON_ATTACKS.items():
        if pattern.search(raw_log):
            findings.append(f"Posible {name.replace('_',' ').title()}")
            score += 20

    if "error" in raw_log.lower():
        findings.append("Errores detectados en el sistema")
        score += 10

    if use_ai:
        findings.append("Análisis IA: No se detectan amenazas avanzadas.")
        score = min(100, score + 10)

    summary = "; ".join(findings) if findings else "Sin hallazgos críticos."
    return {"summary": summary, "score": score}
