# app/services/link_detonation.py
from typing import List, Dict, Any
import re

try:
    import httpx
except Exception:
    httpx = None

SAFE_SCHEMES = ("http://", "https://")
TIMEOUT = 6.0
URL_RE = re.compile(r"^https?://", re.I)
SUSP_TLDS = (".zip", ".mov")
PUNYCODE_RE = re.compile(r"//[^/\s]*xn--", re.I)

def _classify_url(u: str) -> Dict[str, Any]:
    u_low = u.lower()
    return {
        "url": u,
        "punycode": bool(PUNYCODE_RE.search(u)),
        "susp_tld": any(u_low.endswith(t) for t in SUSP_TLDS),
    }

def detonate_urls(urls: List[str], limit: int = 20) -> Dict[str, Any]:
    """
    Hace HEAD/GET rápido con follow_redirects y devuelve reporte por URL.
    Si no hay httpx, devuelve clasificación estática (sin red).
    """
    uniq = []
    seen = set()
    for u in urls:
        if not u or not URL_RE.search(u):
            continue
        if not u.lower().startswith(SAFE_SCHEMES):
            continue
        if u not in seen:
            uniq.append(u); seen.add(u)
        if len(uniq) >= limit:
            break

    results: Dict[str, Any] = {}
    if not uniq:
        return {"ok": True, "results": results, "note": "no urls"}

    if httpx is None:
        # sin httpx: solo clasificación estática
        for u in uniq:
            results[u] = {**_classify_url(u), "status": None, "final_url": None, "network": False}
        return {"ok": True, "results": results, "note": "httpx not available"}

    # con httpx: probamos HEAD y si falla, GET
    for u in uniq:
        info = _classify_url(u)
        info.update({"status": None, "final_url": None, "network": True})
        try:
            with httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers={"User-Agent":"AlertTrail/1.0"}) as cli:
                try:
                    r = cli.head(u)
                    info["status"] = r.status_code
                    info["final_url"] = str(r.url)
                except Exception:
                    r = cli.get(u)
                    info["status"] = r.status_code
                    info["final_url"] = str(r.url)
        except Exception as e:
            info["error"] = str(e)
        results[u] = info

    return {"ok": True, "results": results}
