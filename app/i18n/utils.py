from fastapi import Request
from typing import Optional, Any, Callable, Union

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, Callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key).
    Prioridad: ?lang= > cookie > user_pref > header/default.
    """
    # Import local dinámico para romper la importación circular con app.i18n
    try:
        from app.i18n import get_lang, t as translator_func
    except ImportError:
        # Fallback de seguridad por si el módulo i18n falla al cargar
        def translator_func(l, k, **kwargs): return k
        def get_lang(r): return "es"
    
    lang = get_lang(request)
    
    # Si el usuario tiene una preferencia guardada en DB, la respetamos
    if user and hasattr(user, "language") and user.language:
        lang = user.language

    # Creamos una función parcial para el contexto del template
    def t(key: str, **kwargs):
        return translator_func(lang, key, **kwargs)

    # Guardamos en request.state para acceso rápido
    request.state.lang = lang
    request.state.t = t

    return lang, t
