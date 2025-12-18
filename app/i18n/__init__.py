# app/i18n/__init__.py
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple

from fastapi import Request
from starlette.responses import Response

SUPPORTED_LANGS: Tuple[str, ...] = ("es", "en")
DEFAULT_LANG = (os.getenv("DEFAULT_LANG", "es") or "es").lower()[:2]
if DEFAULT_LANG not in SUPPORTED_LANGS:
    DEFAULT_LANG = "es"


def get_lang(request: Request, default: str | None = None) -> str:
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


# --- Compat: nombres viejos usados por main.py / templates antiguos ---
def get_lang_from_request(request: Request, default: str | None = None) -> str:
    return get_lang(request, default=default)


def set_lang_cookie(resp: Response, lang: str) -> Response:
    lang2 = (lang or "").lower()[:2]
    if lang2 in SUPPORTED_LANGS:
        resp.set_cookie(
            "lang",
            lang2,
            httponly=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,
        )
    return resp


def jinja_t(lang: Any, key: str, **fmt: Any) -> str:
    # wrapper amigable para Jinja
    return t(lang, key, **fmt)


def _candidate_locale_dirs() -> list[Path]:
    here = Path(__file__).resolve().parent
    project_root_guess = here.parent.parent  # app/
    return [
        here / "locales",                         # app/i18n/locales
        project_root_guess / "i18n" / "locales",  # app/i18n/locales (alternativa)
        project_root_guess / "locales",           # app/locales
        Path("app/i18n/locales"),                 # relativo
        Path("app/locales"),                      # relativo
    ]


def _read_json_file(path: Path) -> Dict[str, str]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
        return out
    except Exception:
        return {}


@lru_cache(maxsize=8)
def _load_translations() -> Dict[str, Dict[str, str]]:
    for d in _candidate_locale_dirs():
        es_path = d / "es.json"
        en_path = d / "en.json"
        if es_path.exists() or en_path.exists():
            es = _read_json_file(es_path)
            en = _read_json_file(en_path)
            return {"es": es, "en": en}
    return {"es": {}, "en": {}}


def t(lang: Any, key: str, **fmt: Any) -> str:
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


def i18n_debug() -> Dict[str, Any]:
    tr = _load_translations()
    return {
        "default_lang": DEFAULT_LANG,
        "langs": list(SUPPORTED_LANGS),
        "counts": {k: len(v or {}) for k, v in tr.items()},
        "sample_es": {k: tr["es"].get(k) for k in list(tr["es"].keys())[:5]},
        "sample_en": {k: tr["en"].get(k) for k in list(tr["en"].keys())[:5]},
        "searched_dirs": [str(p) for p in _candidate_locale_dirs()],
    }
