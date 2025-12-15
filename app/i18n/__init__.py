# app/i18n/__init__.py
from __future__ import annotations

from typing import Dict
from fastapi import Request

SUPPORTED_LANGS = ("es", "en")


def get_lang(request: Request, default: str = "es") -> str:
    """
    Idioma efectivo:
    1) cookie "lang"
    2) query ?lang= (por si querés forzar para debug)
    3) Accept-Language (si empieza con en/es)
    4) default
    """
    # 1) cookie
    try:
        ck = (request.cookies.get("lang") or "").strip().lower()[:2]
        if ck in SUPPORTED_LANGS:
            return ck
    except Exception:
        pass

    # 2) query
    try:
        q = (request.query_params.get("lang") or "").strip().lower()[:2]
        if q in SUPPORTED_LANGS:
            return q
    except Exception:
        pass

    # 3) Accept-Language
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


# ============================================================
# MODO RÁPIDO (HOY): traducir HTML final por reemplazos exactos
# ============================================================

_ES_EN_REPLACEMENTS: Dict[str, str] = {
    # FIX CLAVE: el template tiene "<span>Hola, {{...}}"
    # entonces hay que matchear el prefijo exacto antes de la variable.
    "<span>Hola, ": "<span>Hello, ",

    "Tu cockpit de seguridad para correos, accesos y reportes.": "Your security cockpit for emails, access, and reports.",

    # Banner trial
    "Estás en tu periodo de prueba PRO.": "You're in your PRO trial period.",
    "Vas a mantener las funciones avanzadas de AlertTrail hasta que termine la prueba. Desde \"Planes y facturación\" podés pasar a PRO o volver al plan Free sin sorpresas.": (
        "You'll keep AlertTrail's advanced features until your trial ends. "
        "From “Plans & billing” you can upgrade to PRO or return to Free anytime."
    ),
    "Gestionar mi prueba": "Manage my trial",

    "Tu prueba PRO terminó.": "Your PRO trial has ended.",
    "Seguís usando AlertTrail en plan Free. Cuando quieras recuperar las funciones avanzadas, podés pasar a PRO o un plan de empresas.": (
        "You're still using AlertTrail on the Free plan. "
        "Whenever you want, you can upgrade to PRO or a Business plan to restore advanced features."
    ),
    "Ver opciones de PRO": "See PRO options",

    "Tenés una prueba PRO gratuita disponible.": "You have a free PRO trial available.",
    "Probá las alertas automáticas, reglas personalizadas y reportes avanzados pensados para pymes sin equipo de IT.": (
        "Try automated alerts, custom rules, and advanced reports built for small businesses without an IT team."
    ),
    "Activar prueba PRO": "Activate PRO trial",

    # Secciones
    "Estado de tu cuenta": "Account status",
    "Atajos a los módulos que más vas a usar en el día a día.": "Shortcuts to the modules you’ll use most day to day.",
    "Inicio rápido": "Quick start",

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
    "Reportes": "Reports",
    "Auditoría de ciberseguridad": "Cybersecurity audit",
    "Auditoría manual asistida (solo PRO / Empresas).": "Assisted manual audit (PRO / Business only).",
    "Te contactamos por mail con un checklist concreto de mejoras.": "We’ll contact you by email with an actionable improvement checklist.",

    "Herramientas nuevas": "New tools",
    "Experimentos de AlertTrail para simplificar tu día a día.": "AlertTrail experiments to simplify your day.",
    "QR Scan Seguro": "Safe QR Scan",
    "Analizador de Tickets": "Receipt Analyzer",
    "Verificá links de códigos QR antes de abrirlos.": "Check QR links before opening them.",
    "Extraé info básica de tickets / comprobantes.": "Extract basic info from receipts / invoices.",

    "Planes y facturación": "Plans & billing",
    "Consultá tu suscripción, prueba PRO y gestión de organización.": "Check your subscription, PRO trial and organization management.",
    "Ver mi suscripción": "View my subscription",
    "Panel de organización": "Organization panel",
    "Cambiá de plan, actualizá tarjeta y mirá tu próximo ciclo.": "Change plan, update card and see your next cycle.",
    "Invitá miembros de tu equipo y gestioná accesos.": "Invite team members and manage access.",

    "Últimos pagos": "Recent payments",
    "Historial de cobros y facturas asociadas a tu cuenta.": "History of charges and invoices associated with your account.",
    "Ver historial de pagos": "View payment history",
    "Si todavía no tenés pagos registrados, esta sección va a estar vacía.": "If you don't have any payments yet, this section will be empty.",

    "Salud de tu seguridad": "Security health",
    "Próximamente vas a ver un resumen de cuentas, alertas y accesos.": "Soon you'll see a summary of accounts, alerts, and access.",
    "Próximamente": "Coming soon",
    "Resumen de alertas críticas de la semana.": "Summary of critical alerts for the week.",
    "Recomendaciones rápidas para bajar el riesgo.": "Quick recommendations to reduce risk.",
    "Indicadores visuales para ver si vas mejorando.": "Visual indicators to track improvements.",

    "AlertTrail · Protección de correos y accesos, sin complicarte la vida.": "AlertTrail · Email and access protection, without the hassle.",
}


TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "es": {},
    "en": {},
}


def translate_html(lang: str, html: str) -> str:
    """
    Traduce HTML final por reemplazos controlados.
    Solo actúa si lang == 'en'. Base ES.
    """
    lang = (lang or "es").lower()[:2]
    if lang != "en":
        return html

    out = html
    for es, en in _ES_EN_REPLACEMENTS.items():
        out = out.replace(es, en)

    return out
