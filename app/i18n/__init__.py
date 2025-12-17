# app/i18n/__init__.py
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from fastapi import Request

SUPPORTED_LANGS = ("es", "en")
DEFAULT_LANG = (os.getenv("DEFAULT_LANG", "es") or "es").lower()[:2]
if DEFAULT_LANG not in SUPPORTED_LANGS:
    DEFAULT_LANG = "es"

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"


def get_lang(request: Request, default: str | None = None) -> str:
    """
    Idioma efectivo:
    1) query ?lang=
    2) cookie "lang"
    3) Accept-Language
    4) DEFAULT_LANG
    """
    fallback = (default or DEFAULT_LANG).lower()[:2]
    if fallback not in SUPPORTED_LANGS:
        fallback = DEFAULT_LANG

    # 1) query
    try:
        q = (request.query_params.get("lang") or "").strip().lower()[:2]
        if q in SUPPORTED_LANGS:
            return q
    except Exception:
        pass

    # 2) cookie
    try:
        ck = (request.cookies.get("lang") or "").strip().lower()[:2]
        if ck in SUPPORTED_LANGS:
            return ck
    except Exception:
        pass

    # 3) accept-language
    try:
        al = (request.headers.get("accept-language") or "").lower()
        for part in al.split(","):
            code = part.strip().split(";")[0].split("-")[0][:2]
            if code in SUPPORTED_LANGS:
                return code
    except Exception:
        pass

    return fallback


def _load_json(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out: Dict[str, str] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    out[k] = v
            return out
    except Exception:
        # si el JSON está roto, no rompemos la app
        return {}
    return {}


@lru_cache(maxsize=8)
def _load_translations() -> Dict[str, Dict[str, str]]:
    """
    Carga diccionarios desde:
      app/i18n/locales/es.json
      app/i18n/locales/en.json
    """
    es = _load_json(_LOCALES_DIR / "es.json")
    en = _load_json(_LOCALES_DIR / "en.json")
    return {"es": es, "en": en}


def t(lang: Any, key: str, **fmt: Any) -> str:
    """
    Traducción por KEY.
    - fallback a DEFAULT_LANG
    - si falta la key, devuelve la key (así detectás faltantes rápido)
    """
    try:
        lang2 = str(lang or DEFAULT_LANG).lower()[:2]
    except Exception:
        lang2 = DEFAULT_LANG
    if lang2 not in SUPPORTED_LANGS:
        lang2 = DEFAULT_LANG

    tr = _load_translations()
    text = tr.get(lang2, {}).get(key) or tr.get(DEFAULT_LANG, {}).get(key) or key

    if fmt:
        try:
            return text.format(**fmt)
        except Exception:
            return text
    return text


def get_i18n_bundle(lang: str, prefix: str | None = None) -> Dict[str, str]:
    """
    Útil para pasar a JS: devuelve {key: value} para un prefijo (ej: "tools.qr.")
    """
    lang2 = (lang or DEFAULT_LANG).lower()[:2]
    if lang2 not in SUPPORTED_LANGS:
        lang2 = DEFAULT_LANG

    tr = _load_translations().get(lang2, {})
    if not prefix:
        return dict(tr)
    return {k: v for k, v in tr.items() if k.startswith(prefix)}
