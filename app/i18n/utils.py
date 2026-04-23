from fastapi import Request
from typing import Optional
from app.i18n import get_lang, t as translator_func

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key).
    Prioridad: ?lang= > cookie > user_pref > header/default.
    """
    # Usamos la lógica centralizada que ya escribimos en i18n/__init__.py
    lang = get_lang(request)
    
    # Si en el futuro agregas user.language, el get_lang ya debería manejarlo
    # o puedes sobreescribirlo aquí:
    if user and getattr(user, "language", None):
        lang = user.language

    # Creamos una función parcial para no tener que pasar 'lang' cada vez en el HTML
    def t(key: str, **kwargs):
        return translator_func(lang, key, **kwargs)

    # Guardamos en request.state para middlewares
    request.state.lang = lang
    request.state.t = t

    return lang, t
