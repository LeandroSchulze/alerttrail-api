import json
from pathlib import Path
from functools import lru_cache

BASE_DIR = Path(__file__).resolve().parent
LOCALES_DIR = BASE_DIR / "locales"

DEFAULT_LANG = "en"
SUPPORTED_LANGS = {"en", "es"}


@lru_cache
def _load_locale(lang: str) -> dict:
    """
    Carga y cachea el JSON de idioma.
    """
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        # por si falta algún archivo, no rompe
        lang = DEFAULT_LANG
        path = LOCALES_DIR / f"{lang}.json"

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_translator(lang: str):
    """
    Devuelve una función t(key, **kwargs) para traducir.
    Usa fallback al idioma por defecto si falta la key.
    """
    data = _load_locale(lang)
    fallback = _load_locale(DEFAULT_LANG)

    def t(key: str, **kwargs) -> str:
        text = data.get(key) or fallback.get(key) or key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                # si falla el format no rompemos la app
                pass
        return text

    return t


def sanitize_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    if lang not in SUPPORTED_LANGS:
        return DEFAULT_LANG
    return lang
