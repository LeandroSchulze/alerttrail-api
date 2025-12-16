# app/i18n/__init__.py
from __future__ import annotations

from typing import Dict
from fastapi import Request

SUPPORTED_LANGS = ("es", "en")


def get_lang(request: Request, default: str = "es") -> str:
    """
    Idioma efectivo:
    1) query param ?lang=en|es   (opcional)
    2) cookie "lang"
    3) Accept-Language (si empieza con en/es)
    4) default
    """
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

    # 3) header
    try:
        al = (request.headers.get("accept-language") or "").lower()
        if al.startswith("en"):
            return "en"
        if al.startswith("es"):
            return "es"
    except Exception:
        pass

    return default


# Traducciones por clave (para futuro). Hoy la UI está hardcodeada en ES.
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "es": {},
    "en": {},
}


def t(lang: str, key: str, **fmt) -> str:
    """
    Traducción por clave (para templates futuros).
    Si no existe la clave, devuelve la propia key.
    """
    lang = (lang or "es").lower()[:2]
    if lang not in SUPPORTED_LANGS:
        lang = "es"
    txt = TRANSLATIONS.get(lang, {}).get(key, key)
    try:
        return txt.format(**fmt)
    except Exception:
        return txt


# ====== MODO RÁPIDO (HOY): traducir HTML final por reemplazos controlados ======
# Esto permite que TODA la app cambie a EN aunque muchas pantallas estén hardcodeadas en ES.

_ES_EN_REPLACEMENTS: Dict[str, str] = {
    # --- Dashboard ---
    "Hola, ": "Hi, ",
    "Tu cockpit de seguridad para correos, accesos y reportes.": "Your security cockpit for emails, access, and reports.",
    "Plan": "Plan",
    "Estado de tu cuenta": "Account status",
    "Atajos a los módulos que más vas a usar en el día a día.": "Shortcuts to the modules you’ll use most day to day.",
    "Inicio rápido": "Quick start",
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
    "QR Scan Seguro": "Safe QR Scan",
    "Analizador de Tickets": "Receipt analyzer",
    "Planes y facturación": "Plans & billing",
    "Consultá tu suscripción, prueba PRO y gestión de organización.": "Check your subscription, PRO trial, and organization management.",
    "Ver mi suscripción": "View my subscription",
    "Panel de organización": "Organization panel",
    "Cambiá de plan, actualizá tarjeta y mirá tu próximo ciclo.": "Change plan, update card, and see your next cycle.",
    "Invitá miembros de tu equipo y gestioná accesos.": "Invite team members and manage access.",
    "Últimos pagos": "Recent payments",
    "Ver historial de pagos": "View payment history",
    "Si todavía no tenés pagos registrados, esta sección va a estar vacía.": "If you don’t have any payments yet, this section will be empty.",
    "Salud de tu seguridad": "Security health",
    "Próximamente": "Coming soon",

    # --- Mail (templates) ---
    "Scanner de Emails": "Email Scanner",
    "Configurar IMAP": "Configure IMAP",
    "Analizar ahora": "Scan now",
    "Estado": "Status",
    "Conectado": "Connected",
    "No conectado": "Not connected",
    "Servidor IMAP": "IMAP Server",
    "Puerto": "Port",
    "Usuario": "Username",
    "Carpeta": "Folder",
    "Guardar configuración": "Save configuration",
    "Marcar como leído al escanear": "Mark as read when scanning",
    "Usar SSL": "Use SSL",
    "No se encontraron alertas.": "No alerts found.",
    "Volver": "Back",

    # --- Analysis (router devuelve HTML hardcodeado) ---
    "Analizar logs": "Analyze logs",
    "Analizar logs y generar reporte": "Analyze logs and generate report",
    "Archivo de log (Nginx/Apache combined):": "Log file (Nginx/Apache combined):",
    "Descargar como PDF": "Download as PDF",
    "Procesar": "Process",
    "¿Necesitás un archivo de prueba?": "Need a sample file?",
    "Resultado de análisis": "Analysis result",
    "Total de requests:": "Total requests:",
    "Clases": "Classes",
    "Estados": "Status codes",
    "Top paths": "Top paths",
    "Top IPs": "Top IPs",
    "Intentos de login fallidos (401) por IP": "Failed login attempts (401) by IP",
    "Accesos a /admin con 403 por IP": "Access to /admin with 403 by IP",
    "Errores": "Errors",
    "Posibles SQLi": "Possible SQLi",
    "Probes de archivos sensibles": "Sensitive file probes",

    # --- Reports ---
    "Reportes guardados": "Saved reports",
    "Abrir": "Open",
    "Descargar": "Download",
    "Eliminar": "Delete",
    "No hay reportes aún.": "No reports yet.",
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

    # Ajustar atributo lang del documento si viene hardcodeado en "es"
    out = out.replace('<html lang="es"', '<html lang="en"')
    out = out.replace("<html lang='es'", "<html lang='en'")

    for es, en in _ES_EN_REPLACEMENTS.items():
        out = out.replace(es, en)

    return out
