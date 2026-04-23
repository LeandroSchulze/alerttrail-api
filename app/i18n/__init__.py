import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
from fastapi import Request

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = {"es", "en"}

@lru_cache(maxsize=8)
def _load_locale(lang: str) -> Dict[str, str]:
    lang = (lang or "es").lower()
    if lang not in _SUPPORTED:
        lang = "es"
    
    p = _LOCALES_DIR / f"{lang}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def t(lang: str, key: str, **kwargs: Any) -> str:
    lang = (lang or "es").lower()
    if lang not in _SUPPORTED:
        lang = "es"
    
    data = _load_locale(lang)
    # Si no encuentra la clave, intenta buscarla en el default (es) antes de devolver el key
    s = data.get(key)
    if s is None and lang != "es":
        s = _load_locale("es").get(key, key)
    elif s is None:
        s = key

    try:
        return s.format(**kwargs)
    except Exception:
        return s

def get_lang(request: Request) -> str:
    # Prioridad: Query Param (?lang=) > Cookie > Headers
    lang = request.query_params.get("lang")
    if lang and lang.lower() in _SUPPORTED:
        return lang.lower()
    
    # Buscamos ambas cookies por las dudas (la vieja y la nueva)
    lang = request.cookies.get("lang") or request.cookies.get("alerttrail_lang")
    if lang and lang.lower() in _SUPPORTED:
        return lang.lower()
    
    al = request.headers.get("accept-language", "")
    if al.startswith("en"): return "en"
    return "es"
