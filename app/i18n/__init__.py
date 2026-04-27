import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
from fastapi import Request

_LOCALES_DIR = Path(__file__).parent / "locales"

# Definimos las constantes
SUPPORTED_LANGS = {"es", "en"}
DEFAULT_LANG = "es"

@lru_cache(maxsize=8)
def _load_locale(lang: str) -> Dict[str, str]:
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    
    p = _LOCALES_DIR / f"{lang}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def t(lang: str, key: str, **kwargs: Any) -> str:
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    
    data = _load_locale(lang)
    s = data.get(key)
    if s is None and lang != DEFAULT_LANG:
        s = _load_locale(DEFAULT_LANG).get(key, key)
    elif s is None:
        s = key

    try:
        return s.format(**kwargs)
    except Exception:
        return s

def get_lang(request: Request) -> str:
    lang = request.query_params.get("lang")
    if lang and lang.lower() in SUPPORTED_LANGS:
        return lang.lower()
    
    lang = request.cookies.get("lang") or request.cookies.get("alerttrail_lang")
    if lang and lang.lower() in SUPPORTED_LANGS:
        return lang.lower()
    
    al = request.headers.get("accept-language", "")
    if al.startswith("en"): return "en"
    return DEFAULT_LANG

# --- ALIAS PARA COMPATIBILIDAD CON REPORTS.PY ---

# Esto resuelve el ImportError: cannot import name 'get_lang_from_request'
get_lang_from_request = get_lang

# Esto resuelve el ImportError: cannot import name 'jinja_t'
def jinja_t(lang: str, key: str, **kwargs: Any) -> str:
    """Alias de la función de traducción para coherencia en imports"""
    return t(lang, key, **kwargs)
