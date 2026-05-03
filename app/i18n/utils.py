from fastapi import Request
from typing import Optional, Any, Callable

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, Callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key).
    Esta versión está blindada contra errores de argumentos inesperados.
    """
    try:
        from app.i18n import get_lang, t as translator_func
    except ImportError:
        def translator_func(l, k, **kwargs): return k
        def get_lang(r): return "es"
    
    lang = get_lang(request)
    
    if user and hasattr(user, "language") and user.language:
        lang = user.language

    # La función 't' que el HTML llama. Acepta **kwargs para 'count', 'name', etc.
    def t(key: str, **kwargs):
        try:
            # Pasa el idioma y cualquier variable extra al traductor base[cite: 1]
            return translator_func(lang, key, **kwargs)
        except Exception:
            # Si falla la traducción, devuelve la clave para no romper la página
            return key

    request.state.lang = lang
    request.state.t = t

    return lang, t
