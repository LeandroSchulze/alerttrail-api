# app/i18n.py
import os
from functools import lru_cache

SUPPORTED = {"es", "en"}
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "es")

# Diccionario simple (puedes moverlo a JSON luego)
TR = {
    "es": {
        "AlertTrail": "AlertTrail",
        "Welcome, {name}": "Bienvenido, {name}",
        "Your email: {email}": "Tu email: {email}",
        "Account status": "Estado de tu cuenta",
        "Current plan: {plan}": "Plan actual: {plan}",
        "Administrator": "Administrador",
        "User": "Usuario",
        "Change plan": "Cambiar plan",
        "What’s in each plan?": "¿Qué incluye cada plan?",
        "Enable notifications": "Activar notificaciones",
        "Org admin": "Admin de organización",
        "Quick access": "Acceso rápido",
        "Analysis": "Análisis",
        "Emails": "Emails",
        "Organization admin": "Admin de organización",
        "Statistics": "Estadísticas",
        "Subscriptions": "Suscripciones",
        "PRO features": "Funciones PRO / EMPRESAS",
        "View alerts": "Ver alertas",
        "Custom rules": "Reglas personalizadas",
        "Reports": "Reportes",
        "Plans": "Planes",
        "Choose PRO": "Elegir PRO",
        "Choose Enterprises": "Elegir EMPRESAS",
        "Recent payments": "Últimos pagos",
        "See full history": "Ver todo el historial",
        "Login": "Iniciar sesión",
        "Logout": "Cerrar sesión",
        "Mailboxes": "Casillas de correo",
        "Open Scanner": "Abrir Scanner",
        "Save configuration": "Guardar configuración",
        "Mark as read when scanning": "Marcar como leído al escanear",
        "Use SSL": "Usar SSL",
        "IMAP Server": "Servidor IMAP",
        "Port": "Puerto",
        "Username": "Usuario",
        "Password / App Password": "Contraseña / App Password",
        "Folder": "Carpeta",
        "Defaults": "Por defecto",
        "Language": "Idioma",
        "Spanish": "Español",
        "English": "Inglés",
    },
    "en": {
        "AlertTrail": "AlertTrail",
        "Welcome, {name}": "Welcome, {name}",
        "Your email: {email}": "Your email: {email}",
        "Account status": "Account status",
        "Current plan: {plan}": "Current plan: {plan}",
        "Administrator": "Administrator",
        "User": "User",
        "Change plan": "Change plan",
        "What’s in each plan?": "What’s in each plan?",
        "Enable notifications": "Enable notifications",
        "Org admin": "Org admin",
        "Quick access": "Quick access",
        "Analysis": "Analysis",
        "Emails": "Emails",
        "Organization admin": "Organization admin",
        "Statistics": "Statistics",
        "Subscriptions": "Subscriptions",
        "PRO features": "PRO / ENTERPRISE features",
        "View alerts": "View alerts",
        "Custom rules": "Custom rules",
        "Reports": "Reports",
        "Plans": "Plans",
        "Choose PRO": "Choose PRO",
        "Choose Enterprises": "Choose Enterprises",
        "Recent payments": "Recent payments",
        "See full history": "See full history",
        "Login": "Login",
        "Logout": "Logout",
        "Mailboxes": "Mailboxes",
        "Open Scanner": "Open Scanner",
        "Save configuration": "Save configuration",
        "Mark as read when scanning": "Mark as read when scanning",
        "Use SSL": "Use SSL",
        "IMAP Server": "IMAP Server",
        "Port": "Port",
        "Username": "Username",
        "Password / App Password": "Password / App Password",
        "Folder": "Folder",
        "Defaults": "Defaults",
        "Language": "Language",
        "Spanish": "Spanish",
        "English": "English",
    },
}

@lru_cache(maxsize=1024)
def _translate(lang: str, key: str) -> str:
    return TR.get(lang, {}).get(key, TR[DEFAULT_LANG].get(key, key))

def pick_lang(cookie: str | None, query: str | None, accept: str | None) -> str:
    # prioridad: ?lang=  > cookie > Accept-Language > default
    if query and query in SUPPORTED: return query
    if cookie and cookie in SUPPORTED: return cookie
    if accept:
        for part in accept.split(","):
            code = part.strip().split(";")[0].split("-")[0]
            if code in SUPPORTED: return code
    return DEFAULT_LANG

def t(lang: str, key: str, **fmt):
    return _translate(lang, key).format(**fmt)
