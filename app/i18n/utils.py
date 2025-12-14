from fastapi import Request
from typing import Optional

from app.i18n import get_translator, sanitize_lang, DEFAULT_LANG


def get_lang_and_translator(
    request: Request,
    user: Optional["User"] = None,  # type: ignore
) -> tuple[str, callable]:
    """
    Prioridad:
    1) ?lang=xx en la URL
    2) cookie alerttrail_lang
    3) (más adelante) user.language
    4) DEFAULT_LANG
    """
    # 1) query param
    lang = request.query_params.get("lang")
    if lang:
        lang = sanitize_lang(lang)
    else:
        # 2) cookie
        lang = request.cookies.get("alerttrail_lang")
        if lang:
            lang = sanitize_lang(lang)
        else:
            # 3) user.language (si lo agregamos en el futuro)
            if user is not None and getattr(user, "language", None):
                lang = sanitize_lang(user.language)
            else:
                # 4) por defecto
                lang = DEFAULT_LANG

    t = get_translator(lang)

    # guardamos en request.state por si querés usarlo en middlewares/otros sitios
    request.state.lang = lang
    request.state.t = t

    return lang, t
