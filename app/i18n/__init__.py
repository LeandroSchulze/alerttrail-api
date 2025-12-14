# app/i18n/__init__.py
from __future__ import annotations

from typing import Dict
from fastapi import Request

SUPPORTED_LANGS = ("es", "en")


def get_lang(request: Request, default: str = "es") -> str:
    """
    Idioma efectivo:
    1) cookie "lang"
    2) Accept-Language (si empieza con en/es)
    3) default
    """
    try:
        ck = (request.cookies.get("lang") or "").strip().lower()[:2]
        if ck in SUPPORTED_LANGS:
            return ck
    except Exception:
        pass

    try:
        al = (request.headers.get("accept-language") or "").lower()
        if al.startswith("en"):
            return "en"
        if al.startswith("es"):
            return "es"
    except Exception:
        pass

    return default


def t(lang: str, key: str) -> str:
    """
    Traducción por clave (para templates futuros).
    Si no existe la clave, devuelve la propia key.
    """
    lang = (lang or "es").lower()[:2]
    if lang not in SUPPORTED_LANGS:
        lang = "es"

    table = TRANSLATIONS.get(lang, {})
    return table.get(key, key)


# --- (modo rápido) traducción del HTML renderizado ---
# Esto permite cambiar idioma sin reescribir todos los templates hoy.
_ES_EN_REPLACEMENTS: Dict[str, str] = {
    # Dashboard / UI (según tu screenshot)
    "Hola, Admin": "Hi, Admin",
    "Tu cockpit de seguridad para correos, accesos y reportes.": "Your security cockpit for emails, access, and reports.",

    "Tenés una prueba PRO gratuita disponible.": "You have a free PRO trial available.",
    "Probá las alertas automáticas, reglas personalizadas y reportes avanzados pensados para pymes sin equipo de IT.": "Try automated alerts, custom rules, and advanced reports built for small businesses without an IT team.",
    "Activar prueba PRO": "Activate PRO trial",

    "Estado de tu cuenta": "Account status",
    "Atajos a los módulos que más vas a usar en el día a día.": "Shortcuts to the modules you’ll use most day to day.",
    "Inicio rápido": "Quick start",

    "Log scanner": "Log scanner",
    "Mail scanner": "Mail scanner",
    "Reportes PDF": "PDF reports",
    "Alertas automáticas": "Automated alerts",

    "Ir al Log Scanner": "Go to Log Scanner",
    "Scanner de correos": "Email scanner",
    "Reportes guardados": "Saved reports",

    "Subí archivos de logs y generá reportes en segundos.": "Upload log files and generate reports in seconds.",
    "Conectá una casilla IMAP para revisar correos sospechosos.": "Connect an IMAP inbox to review suspicious emails.",

    "Funciones PRO / Empresas": "PRO / Business features",
    "Extras pensados para reducir el riesgo y sumar visibilidad.": "Extras designed to reduce risk and increase visibility.",
    "Ver planes": "See plans",
    "Ver alertas": "View alerts",
    "Reglas personalizadas": "Custom rules",
    "Reportes": "Reports",
    "Auditoría de ciberseguridad": "Cybersecurity audit",
    "Auditoría manual asistida (solo PRO / Empresas).": "Assisted manual audit (PRO / Business only).",
    "Te contactamos por mail con un checklist concreto de mejoras.": "We’ll contact you by email with an actionable improvement checklist.",

    "Herramientas nuevas": "New tools",
    "Experimentos de AlertTrail para simplificar tu día a día.": "AlertTrail experiments to simplify your day.",
    "Analizador de Tickets": "Receipt Analyzer",
    "QR Scan Seguro": "Safe QR Scan",

    "Planes y facturación": "Plans & billing",
    "Consultá tu suscripción, prueba PRO y gestión de organización.": "Check your subscription, PRO trial and organization management.",
    "Ver mi suscripción": "View my subscription",
    "Panel de organización": "Organization panel",
    "Cambiá de plan, actualizá tarjeta y mirá tu próximo ciclo.": "Change plan, update card and see your next cycle.",
    "Invitá miembros de tu equipo y gestioná accesos.": "Invite team members and manage access.",
}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "es": {
        # (opcional, para futuro uso por keys)
    },
    "en": {
        # (opcional, para futuro uso por keys)
    },
}


def translate_html(lang: str, html: str) -> str:
    """
    Traduce HTML final por reemplazos controlados.
    Solo actúa si lang == 'en'.
    """
    lang = (lang or "es").lower()[:2]
    if lang != "en":
        return html

    out = html
    for es, en in _ES_EN_REPLACEMENTS.items():
        out = out.replace(es, en)

    return out
