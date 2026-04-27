from fastapi import Request
from typing import Optional, Any, Callable

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, Callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key).
    Prioridad: ?lang= > cookie > user_pref > header/default.
    """
    # Import local para evitar importación circular con app.i18n.__init__
    from app.i18n import get_lang, t as translator_func
    
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
