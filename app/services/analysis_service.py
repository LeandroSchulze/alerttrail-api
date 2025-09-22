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
        if SSH_FAIL_RE.search(ln):
            stats["ssh_failed"] += 1
            m = SSH_FAIL_RE.search(ln)
            if m:
                fail_by_ip[m.group("ip")] += 1
        if SSH_OK_RE.search(ln):
            stats["ssh_accepted"] += 1
        if SQLI_RE.search(ln):
            stats["sqli"] += 1
            findings.append({"type": "SQLi", "line": ln})
        if XSS_RE.search(ln):
            stats["xss"] += 1
            findings.append({"type": "XSS", "line": ln})

    summary = {
        "ssh_failed": stats["ssh_failed"],
        "ssh_accepted": stats["ssh_accepted"],
        "sqli": stats["sqli"],
        "xss": stats["xss"],
        "bruteforce_ips": sum(1 for c in fail_by_ip.values() if c >= 5),
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
    return "low"
