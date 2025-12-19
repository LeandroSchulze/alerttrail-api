"""Simple i18n for Jinja and API.

Loads JSON files from app/i18n/locales.

Compatibility helpers
---------------------
Some parts of the codebase (e.g. ``app.main``) expect these names to exist:

- ``get_lang_from_request``
- ``set_lang_cookie``
- ``jinja_t``

They are provided here as wrappers around the core functions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from fastapi import Request, Response

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = {"es", "en"}


@lru_cache(maxsize=8)
def _load_locale(lang: str) -> Dict[str, str]:
    lang = (lang or "es").lower()
    if lang not in _SUPPORTED:
        lang = "es"
    p = _LOCALES_DIR / f"{lang}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_lang(request: Request, default: str = "es") -> str:
    # Cookie > Accept-Language > default
    try:
        c = request.cookies.get("lang")
        if c and c.lower() in _SUPPORTED:
            return c.lower()
    except Exception:
        pass

    try:
        al = request.headers.get("accept-language", "")
        al = al.lower()
        if al.startswith("en"):
            return "en"
        if al.startswith("es"):
            return "es"
    except Exception:
        pass

    return default


def t(lang: str, key: str, **kwargs: Any) -> str:
    lang = (lang or "es").lower()
    if lang not in _SUPPORTED:
        lang = "es"
    data = _load_locale(lang)
    s = data.get(key, key)
    try:
        return s.format(**kwargs)
    except Exception:
        return s


def set_lang_cookie(response: Response, lang: str) -> None:
    lang = (lang or "es").lower()
    if lang not in _SUPPORTED:
        lang = "es"
    response.set_cookie(
        key="lang",
        value=lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
    )


# ---- Compatibility wrappers ----

def get_lang_from_request(request: Request) -> str:
    return get_lang(request)


def jinja_t(lang: str, key: str, **kwargs: Any) -> str:
    return t(lang, key, **kwargs)
