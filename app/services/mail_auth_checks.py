# app/services/mail_auth_checks.py
# Semáforo SPF / DKIM / DMARC (best-effort)
# - SPF: busca registros TXT del dominio y detecta "v=spf1". Devuelve: pass|none|error
# - DMARC: busca TXT en _dmarc.<dominio> con "v=DMARC1". Devuelve: pass|none|error y política p=
# - DKIM: sin selector confiable en headers es "unknown". Si llega "dkim=pass" en Authentication-Results => pass

from __future__ import annotations

import time
from typing import Dict, Optional

try:
    import dns.resolver  # type: ignore
    _HAS_DNSPY = True
except Exception:  # pragma: no cover - entorno sin dnspython
    _HAS_DNSPY = False

_CACHE_TTL = 600  # segundos
_CACHE: Dict[str, Dict[str, object]] = {}


def _get_txt_records(domain: str) -> list[str]:
    if not domain or not _HAS_DNSPY:
        return []
    try:
        answers = dns.resolver.resolve(domain, "TXT", lifetime=5.0)  # type: ignore[attr-defined]
        txt_records: list[str] = []
        for rdata in answers:
            try:
                txt = b"".join(rdata.strings).decode("utf-8", errors="ignore")  # type: ignore[attr-defined]
            except Exception:
                txt = str(rdata)
            txt_records.append(txt)
        return txt_records
    except Exception:
        return []


def check_spf(domain: str) -> Dict[str, object]:
    """
    Devuelve {"status": "pass|none|error", "raw": [TXT...]}.
    """
    if not domain:
        return {"status": "unknown", "raw": []}

    txts = _get_txt_records(domain)
    if not txts:
        # Puede ser none porque no hay DNS o porque no hay librería
        return {"status": "none", "raw": []}

    has_spf = any("v=spf1" in (t or "").lower() for t in txts)
    return {"status": "pass" if has_spf else "none", "raw": txts}


def check_dmarc(domain: str) -> Dict[str, object]:
    """
    Devuelve {"status": "pass|none|error", "policy": "...", "raw": [TXT...]}.
    """
    if not domain:
        return {"status": "unknown", "policy": None, "raw": []}

    dmarc_domain = f"_dmarc.{domain}"
    txts = _get_txt_records(dmarc_domain)
    if not txts:
        return {"status": "none", "policy": None, "raw": []}

    txt = " ".join(txts).lower()
    if "v=dmarc1" not in txt:
        return {"status": "none", "policy": None, "raw": txts}

    policy = None
    for part in txt.replace(";", " ").split():
        if part.startswith("p="):
            policy = part.split("=", 1)[1]
            break

    return {"status": "pass", "policy": policy, "raw": txts}


def check_dkim_from_auth_results(auth_results_header: Optional[str]) -> Dict[str, object]:
    """
    Mira el header Authentication-Results (si existe) para inferir DKIM.
    No hace consultas DNS ni necesita selector.
    """
    if not auth_results_header:
        return {"status": "unknown"}

    hdr = auth_results_header.lower()
    if "dkim=pass" in hdr:
        return {"status": "pass"}
    if "dkim=fail" in hdr or "dkim=permerror" in hdr or "dkim=temperror" in hdr:
        return {"status": "fail"}
    return {"status": "unknown"}


def check_auth(domain: str, auth_results_header: Optional[str] = None) -> Dict[str, object]:
    """
    Helper principal usado por /alerts para rellenar columnas spf_status/dkim_status/dmarc_status.
    Devuelve un dict con claves "spf", "dkim", "dmarc", "overall".
    """
    domain = (domain or "").strip().lower()
    if not domain:
        return {
            "spf": {"status": "unknown"},
            "dkim": {"status": "unknown"},
            "dmarc": {"status": "unknown"},
            "overall": "unknown",
        }

    now = time.time()
    cached = _CACHE.get(domain)
    if cached and isinstance(cached.get("_ts"), (int, float)) and now - float(cached["_ts"]) < _CACHE_TTL:
        return cached  # type: ignore[return-value]

    spf = check_spf(domain)
    dmarc = check_dmarc(domain)
    dkim = check_dkim_from_auth_results(auth_results_header)

    def _score(status: str) -> int:
        s = (status or "").lower()
        if s == "fail":
            return 2
        if s in ("unknown", "none", "neutral", "error"):
            return 1
        return 0  # pass

    level = max(
        _score(str(spf.get("status", "unknown"))),
        _score(str(dkim.get("status", "unknown"))),
        _score(str(dmarc.get("status", "unknown"))),
    )
    overall = "pass" if level == 0 else ("warn" if level == 1 else "fail")

    result: Dict[str, object] = {"spf": spf, "dkim": dkim, "dmarc": dmarc, "overall": overall, "_ts": now}
    _CACHE[domain] = result
    return result
