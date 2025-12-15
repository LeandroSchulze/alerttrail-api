# app/i18n/__init__.py
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from fastapi import Request

SUPPORTED_LANGS = ("es", "en")
DEFAULT_LANG = "es"

BASE_DIR = Path(__file__).parent
LOCALES_DIR = BASE_DIR / "locales"


@lru_cache(maxsize=8)
def _load_lang(lang: str) -> dict:
    """
    Carga app/i18n/locales/<lang>.json
    Cacheado para no leer disco en cada request.
    """
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Si el JSON está mal formado, no rompemos el deploy
        return {}


def get_lang(request: Request, default: str = DEFAULT_LANG) -> str:
    """
    Idioma efectivo:
    1) cookie "lang"
    2) Accept-Language
    3) default
    """
    # 1) cookie
    try:
        ck = (request.cookies.get("lang") or "").strip().lower()[:2]
        if ck in SUPPORTED_LANGS:
            return ck
    except Exception:
        pass

    # 2) Accept-Language
    try:
        al = (request.headers.get("accept-language") or "").lower()
        for code in SUPPORTED_LANGS:
            if al.startswith(code):
                return code
    except Exception:
        pass

    return default


def t(lang: str, key: str, **kwargs) -> str:
    """
    Traducción por clave.
    Fallback: idioma actual -> DEFAULT_LANG -> key
    """
    lang = (lang or DEFAULT_LANG).strip().lower()[:2]
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG

    text = _load_lang(lang).get(key)

    if text is None and lang != DEFAULT_LANG:
        text = _load_lang(DEFAULT_LANG).get(key)

    if text is None:
        text = key

    try:
        return text.format(**kwargs)
    except Exception:
        return text


def translate_html(lang: str, html: str) -> str:
    """
    Compatibilidad con tu main.py (middleware actual).
    En el enfoque definitivo NO traducimos HTML con replace().

    Por ahora lo dejamos como NO-OP para que no rompa deploy.
    """
    return html
