# app/i18n/utils.py
from fastapi import Request
from typing import Optional, Any, Callable

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, Callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key).
    Versión unificada: soporta variables en templates y preferencia de usuario.
    """
    try:
        # Intentamos importar el motor de traducción base
        from app.i18n import get_lang, t as translator_func
    except ImportError:
        # Fallback de seguridad si no encuentra los módulos
        def translator_func(l, k): return k
        def get_lang(r): return "es"
    
    # 1. Prioridad de idioma: Usuario > Sesión/Request[cite: 2]
    lang = get_lang(request)
    if user and hasattr(user, "language") and user.language:
        lang = user.language

    # 2. Función 't' que el HTML llama (blindada contra errores)
    def t(key: str, **kwargs):
        try:
            # Obtenemos la cadena de texto desde el JSON[cite: 2]
            text = translator_func(lang, key)
            
            # Si pasamos variables (como count=5), las inyectamos en el texto[cite: 1]
            if kwargs and isinstance(text, str):
                return text.format(**kwargs)
            return text
        except Exception:
            # Si algo falla (ej. el JSON no tiene el formato {count}), devolvemos la key[cite: 1]
            return key

    # 3. Guardamos en el estado para que otros middlewares lo usen[cite: 2]
    request.state.lang = lang
    request.state.t = t

    return lang, t
