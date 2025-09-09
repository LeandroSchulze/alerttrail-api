# app/services/analysis_service.py
import re
from collections import defaultdict

SSH_FAIL_RE = re.compile(r"Failed password for (invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2")
SSH_OK_RE   = re.compile(r"Accepted password for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3}) .*ssh2")
SQLI_RE     = re.compile(r"('|\")\s*or\s*1=1|union\s+select|--\s", re.I)
XSS_RE      = re.compile(r"<script>|onerror=|onload=", re.I)

def analyze_log(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    findings = []
    stats = defaultdict(int)
    fail_by_ip = defaultdict(int)

    for ln in lines:
        m = SSH_FAIL_RE.search(ln)
        if m:
            ip = m.group("ip"); user = m.group("user")
            stats["ssh_failed"] += 1
            fail_by_ip[ip] += 1
            findings.append({"severity":"medium","type":"ssh_failed_login","ip":ip,"user":user,"line":ln})
            continue
        m = SSH_OK_RE.search(ln)
        if m:
            ip = m.group("ip"); user = m.group("user")
            stats["ssh_accepted"] += 1
            sev = "high" if user == "root" else "low"
            findings.append({"severity":sev,"type":"ssh_success","ip":ip,"user":user,"line":ln,
                             "note":"Acceso a root" if user=="root" else ""})

        if SQLI_RE.search(ln):
            stats["sqli"] += 1
            findings.append({"severity":"high","type":"sql_injection_pattern","line":ln})
        if XSS_RE.search(ln):
            stats["xss"] += 1
            findings.append({"severity":"medium","type":"xss_pattern","line":ln})

    brute_ips = [ip for ip,c in fail_by_ip.items() if c >= 3]
    for ip in brute_ips:
        findings.append({"severity":"high","type":"ssh_bruteforce_suspected","ip":ip,"count":fail_by_ip[ip],
                         "note":"3+ intentos fallidos desde misma IP"})
    stats["bruteforce_ips"] = len(brute_ips)

    summary = {
        "total_lines": len(lines),
        "ssh_failed": stats["ssh_failed"],
        "ssh_accepted": stats["ssh_accepted"],
        "sqli": stats["sqli"],
        "xss": stats["xss"],
        "bruteforce_ips": stats["bruteforce_ips"],
        "risk": _compute_risk(stats),
    }
    return {"summary": summary, "findings": findings}

def _compute_risk(s):
    score = 0
    score += s["ssh_failed"] * 1
    score += s["bruteforce_ips"] * 5
    score += s["sqli"] * 5
    score += s["xss"] * 2
    score += s["ssh_accepted"] * 1
    if score >= 10: return "high"
    if score >= 4:  return "medium"
    return "low
