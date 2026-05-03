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
    try:
        from app.i18n import get_lang, t as translator_func
    except ImportError:
        # Fallback si el módulo i18n falla
        def translator_func(l, k, **kwargs): return k
        def get_lang(r): return "es"
    
    lang = get_lang(request)
    
    if user and hasattr(user, "language") and user.language:
        lang = user.language

    # Esta es la que usa Jinja2 en el HTML
    def t(key: str, **kwargs):
        # IMPORTANTE: Aquí se pasan las variables como 'count'
        return translator_func(lang, key, **kwargs)

    request.state.lang = lang
    request.state.t = t

    return lang, t
