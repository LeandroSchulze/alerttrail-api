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


@lru_cache(maxsize=2)
def _load_lang(lang: str) -> dict:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_lang(request: Request, default: str = DEFAULT_LANG) -> str:
    # 1) cookie
    try:
        ck = (request.cookies.get("lang") or "").lower()[:2]
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
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG

    data = _load_lang(lang)
    text = data.get(key)

    # fallback → idioma base → clave
    if text is None and lang != DEFAULT_LANG:
        text = _load_lang(DEFAULT_LANG).get(key)

    if text is None:
        text = key

    try:
        return text.format(**kwargs)
    except Exception:
        return text
