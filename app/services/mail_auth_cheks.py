# app/services/mail_auth_checks.py
# Semáforo SPF / DKIM / DMARC (best-effort)
# - SPF: busca registros TXT del dominio y detecta "v=spf1". Devuelve: pass|fail|neutral|none|error
# - DMARC: busca TXT en _dmarc.<dominio> con "v=DMARC1". Devuelve: pass|fail|none|error y política p=
# - DKIM: sin selector confiable en headers es "unknown". Si llega "dkim=pass" en Authentication-Results => pass

from __future__ import annotations
import socket
import time
from typing import Dict, Optional

try:
    import dns.resolver  # type: ignore
    _HAS_DNSPY = True
except Exception:
    _HAS_DNSPY = False

# Cache TTL muy corto para no bombardear DNS
_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 120.0  # segundos

def _cache_get(key: str) -> Optional[dict]:
    now = time.time()
    ent = _CACHE.get(key)
    if not ent:
        return None
    ts, val = ent
    if now - ts > _TTL:
        _CACHE.pop(key, None)
        return None
    return val

def _cache_set(key: str, val: dict):
    _CACHE[key] = (time.time(), val)

def _txt_records(name: str) -> list[str]:
    """
    Retorna TXT records. Si no está dnspython, intenta socket.getaddrinfo para validar dominio
    y retorna lista vacía (modo degradado).
    """
    if _HAS_DNSPY:
        try:
            answers = dns.resolver.resolve(name, "TXT", lifetime=3.0)  # type: ignore
            out = []
            for r in answers:
                # cada r.strings puede traer listas de bytes
                try:
                    s = "".join([x.decode("utf-8", "ignore") for x in r.strings])  # type: ignore
                except Exception:
                    s = str(r)
                out.append(s)
            return out
        except Exception:
            return []
    # Sin dnspython: resolvemos A/AAAA para validar existencia y devolvemos vacío
    try:
        socket.getaddrinfo(name, 80)
    except Exception:
        pass
    return []

def check_spf(domain: str) -> dict:
    key = f"spf:{domain}"
    c = _cache_get(key)
    if c is not None:
        return c
    status = "none"
    try:
        txts = _txt_records(domain)
        spf_txt = [t for t in txts if "v=spf1" in t.lower()]
        if not spf_txt:
            status = "none"
        else:
            # No resolvemos IP del remitente aquí; best-effort:
            # si tiene "v=spf1" lo marcamos como 'pass' provisionalmente y dejamos detalle
            status = "pass"
    except Exception:
        status = "error"
    data = {"status": status}
    _cache_set(key, data)
    return data

def check_dmarc(domain: str) -> dict:
    key = f"dmarc:{domain}"
    c = _cache_get(key)
    if c is not None:
        return c
    host = f"_dmarc.{domain}"
    status = "none"
    policy = ""
    try:
        txts = _txt_records(host)
        dmarc_txt = ""
        for t in txts:
            if "v=DMARC1" in t.upper():
                dmarc_txt = t
                break
        if not dmarc_txt:
            status = "none"
        else:
            status = "pass"
            # parseo simple de p= (none|quarantine|reject)
            for part in dmarc_txt.split(";"):
                part = part.strip().lower()
                if part.startswith("p="):
                    policy = part.split("=", 1)[1].strip()
                    break
    except Exception:
        status = "error"
    data = {"status": status, "policy": policy}
    _cache_set(key, data)
    return data

def check_dkim_from_auth_results(auth_results_header: str | None) -> dict:
    """
    Si en Authentication-Results viene 'dkim=pass' -> pass, si 'dkim=fail' -> fail.
    Si no hay info: 'unknown'.
    """
    if not auth_results_header:
        return {"status": "unknown"}
    s = auth_results_header.lower()
    if "dkim=pass" in s:
        return {"status": "pass"}
    if "dkim=fail" in s:
        return {"status": "fail"}
    return {"status": "unknown"}

def check_auth(domain: str, auth_results_header: str | None = None) -> dict:
    """
    Paquete semáforo.
    """
    spf = check_spf(domain)
    dmarc = check_dmarc(domain)
    dkim = check_dkim_from_auth_results(auth_results_header)
    # nivel global para un pill resumido (simple):
    # fail > unknown/none > pass
    def score_one(x: str) -> int:
        if x == "fail":
            return 2
        if x in ("unknown", "none", "neutral", "error"):
            return 1
        return 0  # pass
    level = max(score_one(spf["status"]), score_one(dkim["status"]), score_one(dmarc["status"]))
    overall = "pass" if level == 0 else ("warn" if level == 1 else "fail")
    return {"spf": spf, "dkim": dkim, "dmarc": dmarc, "overall": overall}
