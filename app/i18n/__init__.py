# app/i18n/__init__.py
from __future__ import annotations
from typing import Any, Dict

SUPPORTED_LANGS = {"es", "en"}
DEFAULT_LANG = "es"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "es": {
        "app.name": "AlertTrail",
        "nav.dashboard": "Dashboard",
        "nav.logout": "Cerrar sesión",
        "nav.login": "Iniciar sesión",
        "nav.language": "Idioma",
        "lang.es": "ES",
        "lang.en": "EN",
    },
    "en": {
        "app.name": "AlertTrail",
        "nav.dashboard": "Dashboard",
        "nav.logout": "Log out",
        "nav.login": "Log in",
        "nav.language": "Language",
        "lang.es": "ES",
        "lang.en": "EN",
    },
}


def get_lang(request: Any = None) -> str:
    """
    Obtiene idioma desde cookie 'alerttrail_lang'
    """
    try:
        if request is not None:
            lang = request.cookies.get("alerttrail_lang")
            if lang in SUPPORTED_LANGS:
                return lang
    except Exception:
        pass
    return DEFAULT_LANG


def translate(key: str, lang: str | None = None, **kwargs: Any) -> str:
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG

    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get(DEFAULT_LANG, {}).get(key, key)

    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass

    return text


# 👇 ESTA ES LA FUNCIÓN QUE USA JINJA
def t(lang: str, key: str, **kwargs: Any) -> str:
    return translate(key, lang, **kwargs)


__all__ = [
    "SUPPORTED_LANGS",
    "DEFAULT_LANG",
    "TRANSLATIONS",
    "get_lang",
    "translate",
    "t",
]
