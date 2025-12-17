# app/ui.py
from __future__ import annotations

from pathlib import Path
from fastapi.templating import Jinja2Templates

from app.i18n import get_lang, t


class TemplatesWithDefaults(Jinja2Templates):
    """TemplateResponse() que SIEMPRE agrega lang y expone t() en contexto."""

    def TemplateResponse(self, name: str, context: dict, *args, **kwargs):
        try:
            request = context.get("request")
            if request and "lang" not in context:
                context["lang"] = get_lang(request)
        except Exception:
            pass

        context.setdefault("t", t)
        return super().TemplateResponse(name, context, *args, **kwargs)


TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = TemplatesWithDefaults(directory=TEMPLATES_DIR)

try:
    templates.env.globals["t"] = t
except Exception:
    pass
