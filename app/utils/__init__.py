# app/utils/__init__.py
import re
import json
import logging
import requests
from pathlib import Path
from urllib.parse import urlparse
from fastapi import Request
from app.i18n import get_lang  # Reutiliza tu lógica base de i18n

logger = logging.getLogger("alerttrail.utils")

# 🏛️ MATRIZ DE INTELIGENCIA DE AMENAZAS DICHAS (Bancos, pasarelas y servicios financieros)
DOMINIOS_CRITICOS = [
    "mercadopago.com", "mercadopago.com.ar", "visa.com", "mastercard.com",
    "santander.com.ar", "galicia.com.ar", "bbva.com.ar", "banconacion.com.ar",
    "gmail.com", "outlook.com", "yahoo.com", "paypal.com", "stripe.com"
]

# --- 🌐 SISTEMA DE INTERNACIONALIZACIÓN GLOBAL (UI + BACKEND + NOTIFICACIONES) ---

def get_lang_and_translator(request: Request = None, user=None):
    """
    Detecta el idioma dinámicamente y devuelve la función 't'.
    Soporta ejecuciones sin 'request' para background tasks o notificaciones push.
    """
    lang = "es"
    
    # 1. Prioridad 1: Preferencia explícita del usuario guardada en DB
    if user:
        if hasattr(user, "lang") and user.lang:
            lang = user.lang
        elif hasattr(user, "language") and user.language:
            lang = user.language
            
    # 2. Prioridad 2: Si no hay usuario pero hay request activo (Cookies/Sesión del navegador)
    elif request:
        try:
            lang = get_lang(request)
        except Exception:
            pass

    if lang not in ("es", "en"):
        lang = "es"

    # Cargar el archivo de idioma correspondiente (es.json o en.json)
    translations = {}
    try:
        base_dir = Path(__file__).resolve().parent.parent
        locale_file = base_dir / "i18n" / "locales" / f"{lang}.json"
        
        if locale_file.exists():
            with open(locale_file, "r", encoding="utf-8") as f:
                translations = json.load(f)
    except Exception as e:
        logger.error(f"Error cargando locales para {lang}: {e}")

    def t(key: str, default: str = None) -> str:
        """Busca la traducción exacta del backend o notificaciones."""
        return translations.get(key, default or key)

    return lang, t


# --- 🧠 MINI IA THREAT HEURISTIC ENGINE (Detección y Aprendizaje de Amenazas) ---

def calcular_distancia_levenshtein(s1: str, s2: str) -> int:
    """Algoritmo de distancia de texto para identificar Typosquatting (Engaños visuales)."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

def analizar_correo_avanzado(remitente: str, asunto: str, cuerpo_html: str) -> dict:
    """
    Mini IA Predictiva Heurística de AlertTrail.
    Analiza vectores maliciosos bilingües y retorna el score matemático de riesgo (0-100).
    """
    score_amenaza = 0
    razones = []
    
    remitente = (remitente or "").lower().strip()
    asunto = (asunto or "").strip()
    cuerpo_html = (cuerpo_html or "").strip()
    
    dominio_remitente = ""
    if "@" in remitente:
        try:
            dominio_remitente = remitente.split("@")[-1].strip()
        except Exception:
            pass

    # Capa 1: IA de Suplantación Visual (Anti-Typosquatting)
    if dominio_remitente:
        for dom_real in DOMINIOS_CRITICOS:
            if dominio_remitente != dom_real:
                distancia = calcular_distancia_levenshtein(dominio_remitente, dom_real)
                if 1 <= distancia <= 2:
                    score_amenaza += 55
                    razones.append(f"Typosquatting detectado: Dominio remitente sospechosamente similar a corporativo seguro '{dom_real}'")
                    break

    # Capa 2: Matriz Lingüística Neural Bilingüe (Urgencia, Pánico Financiero y Phishing)
    patrones_ia_bilingue = [
        # Español
        r"urgente", r"suspensio?n", r"bloqueo", r"venci?miento", r"actualizar datos", 
        r"verificar cuenta", r"token", r"debito inmediato", r"acceso no autorizado", 
        r"tarjeta suspendida", r"clonacion", r"evite multas",
        # Inglés
        r"urgent", r"suspended", r"blocked", r"expiration", r"update account", 
        r"verify identity", r"security alert", r"action required", r"unauthorized login",
        r"immediate attention", r"restricted account"
    ]
    texto_combinado = f"{asunto} {cuerpo_html}".lower()
    
    coincidencias = sum(1 for patron in patrones_ia_bilingue if re.search(patron, texto_combinado))
    if coincidencias >= 2:
        score_amenaza += 30
        razones.append("Ingeniería social detectada: Estructura psicológica de alta urgencia o coacción")

    # Capa 3: Rastreador de Redirecciones Profundas (Enlaces Ocultos)
    enlaces = re.findall(r'href=["\'](https?://[^"\']+)["\']', cuerpo_html, re.IGNORECASE)
    for url in enlaces:
        try:
            response = requests.head(url, allow_redirects=True, timeout=2.0)
            dominio_final = urlparse(response.url).netloc.lower()
            if dominio_final.startswith("www."):
                dominio_final = dominio_final[4:]
                
            if dominio_remitente in DOMINIOS_CRITICOS and dominio_final != dominio_remitente:
                score_amenaza += 40
                razones.append(f"Incoherencia estructural: El mail dice ser de '{dominio_remitente}' pero redirige a '{dominio_final}'")
                break
        except Exception:
            score_amenaza += 15
            razones.append("Enlace ofuscado, acortado o protegido contra inspección automatizada")
            break

    score_final = min(score_amenaza, 100)
    
    if score_final >= 75:
        estado = "CRÍTICO"
    elif score_final >= 35:
        estado = "SOSPECHOSO"
    else:
        estado = "SEGURO"

    return {
        "status": estado,
        "score": score_final,
        "alerts": razones
    }

def sanitizar_y_escanear_logs(log_line: str) -> bool:
    patrones_ataque = [r"UNION SELECT", r"<script>", r"\.\./\.\./", r"sudo "]
    for patron in patrones_ataque:
        if re.search(patron, log_line, re.IGNORECASE):
            return True
    return False
