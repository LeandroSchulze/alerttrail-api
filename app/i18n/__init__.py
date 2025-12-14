# app/i18n/__init__.py
from __future__ import annotations

from typing import Any, Dict, Optional


# Diccionario simple de traducciones.
# Si ya tenías tus textos en otros archivos/módulos, podés moverlos ahí y que esto los importe.
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


def get_lang(request: Any = None, default: str = "es") -> str:
    """
    Intenta obtener el idioma desde:
    - request.cookies['lang']
    - fallback a default
    """
    try:
        if request is not None:
            lang = getattr(request, "cookies", {}).get("lang")
            if lang in TRANSLATIONS:
                return lang
    except Exception:
        pass
    return default


def translate(key: str, lang: str = "es", **kwargs: Any) -> str:
    """
    Traduce una key para un idioma.
    - fallback: si no existe la key en el idioma, intenta en 'en'
    - fallback final: devuelve la key tal cual
    - soporta format con kwargs: "Hola {name}"
    """
    lang = (lang or "es").lower()
    if lang not in TRANSLATIONS:
        lang = "es"

    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get("en", {}).get(key)
    if text is None:
        text = key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            # Si falla el format, devolvemos el texto sin formatear para no romper el render.
            pass

    return text


# ✅ COMPAT: tu main.py hace "from app.i18n import t"
def t(lang: str, key: str, **kwargs: Any) -> str:
    """
    Wrapper compatible para Jinja / uso directo desde main.py.
    Uso esperado: t(lang, "some.key", name="Leandro")
    """
    return translate(key=key, lang=lang, **kwargs)


__all__ = ["TRANSLATIONS", "get_lang", "translate", "t"]
