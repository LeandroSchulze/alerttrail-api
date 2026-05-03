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
        # Fallback total si falla la importación
        def translator_func(l, k, **kwargs): return k
        def get_lang(r): return "es"
    
    lang = get_lang(request)
    
    if user and hasattr(user, "language") and user.language:
        lang = user.language

    # Definimos la función con un nombre único y atrapando TODO (*args y **kwargs)
    def t_final(key: str, *args, **kwargs):
        try:
            # Le pasamos el idioma, la clave y cualquier variable como 'count'
            return translator_func(lang, key, **kwargs)
        except Exception:
            return key # Si algo falla, devolvemos la clave original para no romper la app

    request.state.lang = lang
    request.state.t = t_final

    return lang, t_final
