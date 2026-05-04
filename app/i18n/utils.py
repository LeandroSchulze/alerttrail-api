# app/i18n/utils.py
import json
import os
from functools import lru_cache
from fastapi import Request
from typing import Optional, Any, Callable

@lru_cache()
def load_translations(lang: str):
    """Carga los archivos JSON de la carpeta locales"""
    base_path = os.path.dirname(__file__)
    file_path = os.path.join(base_path, "locales", f"{lang}.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_lang_and_translator(
    request: Request,
    user: Optional[Any] = None,
) -> tuple[str, Callable]:
    """
    Detecta el idioma y devuelve la función de traducción t(key, **kwargs).
    Versión blindada: maneja internamente el formateo de variables.
    """
    # 1. Determinar el idioma (Prioridad: Usuario > Sesión > Default)
    lang = "es"
    if user and hasattr(user, "language") and user.language:
        lang = user.language
    else:
        # Intentamos obtener de la sesión si existe el middleware
        try:
            lang = request.session.get("lang", "es")
        except Exception:
            lang = "es"

    translations = load_translations(lang)

    # 2. Definición de la función de traducción t que recibe count, name, etc.
    def t(key: str, **kwargs):
        text = translations.get(key, key)
        
        # Si no hay variables extra, devolvemos el texto directamente
        if not kwargs:
            return text
            
        try:
            # Si hay variables como {count}, las inyectamos aquí
            if isinstance(text, str):
                return text.format(**kwargs)
            return text
        except (KeyError, ValueError, IndexError):
            # Si el JSON no tiene el formato correcto, devolvemos el texto base para no romper la app
            return text

    # Guardamos en el estado del request por si otros componentes lo necesitan[cite: 2]
    request.state.lang = lang
    request.state.t = t

    return lang, t
