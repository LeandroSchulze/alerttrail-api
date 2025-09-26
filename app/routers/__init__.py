# app/routers/__init__.py
"""
Paquete de routers de AlertTrail.

Este __init__ exporta los submódulos más comunes y soporta importaciones
como:  from app.routers import reports
sin inicializar nada pesado en tiempo de import.
"""

from importlib import import_module

__all__ = [
    "auth",
    "analysis",
    "admin",
    "admin_metrics",
    "alerts",
    "alerts_pro",
    "billing",
    "mail",
    "payments",
    "profile",
    "push",
    "reports",
    "rules",
    "stats",
]

def __getattr__(name):
    # Carga perezosa de submódulos: app.routers.<name>
    if name in __all__:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

