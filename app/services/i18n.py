STRINGS = {
    "es": {
        "app_title": "AlertTrail",
        "welcome": "Bienvenido",
        "login": "Iniciar sesión",
        "logout": "Cerrar sesión",
        "analyze": "Analizar logs",
        "history": "Historial",
    },
    "en": {
        "app_title": "AlertTrail",
        "welcome": "Welcome",
        "login": "Log in",
        "logout": "Log out",
        "analyze": "Analyze logs",
        "history": "History",
    },
}
def t(key: str, lang: str = "es") -> str:
    return STRINGS.get(lang, STRINGS["es"]).get(key, key)
