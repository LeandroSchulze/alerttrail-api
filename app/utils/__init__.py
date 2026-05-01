# app/utils/__init__.py
import json
from pathlib import Path
from fastapi import Request
from app.i18n import get_lang  # Reutilizamos tu lógica de i18n

def get_lang_and_translator(request: Request, user=None):
    """
    Determina el idioma actual y devuelve una función de traducción 't'.
    Indispensable para el dashboard y la internacionalización de AlertTrail.
    """
    # 1. Determinar el idioma (Prioridad: Usuario > Cookie > Header)
    lang = get_lang(request)
    if user and hasattr(user, "lang") and user.lang:
        lang = user.lang
    
    # Aseguramos que sea un idioma soportado por tus archivos locales
    if lang not in ("es", "en"):
        lang = "es"

    # 2. Cargar el diccionario de traducciones desde app/i18n/locales/
    translations = {}
    try:
        # Localización de los archivos JSON relativa a este archivo
        base_dir = Path(__file__).resolve().parent.parent
        locale_file = base_dir / "i18n" / "locales" / f"{lang}.json"
        
        if locale_file.exists():
            with open(locale_file, "r", encoding="utf-8") as f:
                translations = json.load(f)
    except Exception:
        # Si hay error al cargar, la función t simplemente devolverá la clave original
        pass

    # 3. Definir la función de traducción 't' que esperan tus templates
    def t(key: str, default: str = None) -> str:
        """Busca la clave en el JSON; si no existe, devuelve la clave misma."""
        return translations.get(key, default or key)

    return lang, t
