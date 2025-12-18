# app/ui.py
from pathlib import Path
from starlette.templating import Jinja2Templates

from app.i18n import t, get_lang, SUPPORTED_LANGS, DEFAULT_LANG

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

templates.env.globals["t"] = t
templates.env.globals["get_lang"] = get_lang
templates.env.globals["SUPPORTED_LANGS"] = SUPPORTED_LANGS
templates.env.globals["DEFAULT_LANG"] = DEFAULT_LANG
