# app/utils/__init__.py
import re
import json
import logging
import requests
from pathlib import Path
from urllib.parse import urlparse
from fastapi import Request
from app.i18n import get_lang  # Reutilizamos tu lógica de i18n

logger = logging.getLogger("alerttrail.utils")

# 🏛️ LISTA BLANCA DE DOMINIOS CRÍTICOS (Monitoreados para evitar Typosquatting / Suplantación)
DOMINIOS_CRITICOS = [
    "mercadopago.com",
    "mercadopago.com.ar",
    "visa.com",
    "mastercard.com",
    "santander.com.ar",
    "galicia.com.ar",
    "bbva.com.ar",
    "banconacion.com.ar",
    "gmail.com",
    "outlook.com",
    "yahoo.com"
]

# --- 🌐 CAPA DE TRADUCCIÓN E INTERNACIONALIZACIÓN ---

def get_lang_and_translator(request: Request, user=None):
    """
    Determina el idioma actual y devuelve una función de traducción 't'.
    Indispensable para el dashboard y la internacionalización de AlertTrail.
    """
    # 1. Determinar el idioma (Prioridad: Usuario > Cookie > Header)
    lang = get_lang(request)
    if user and hasattr(user, "lang") and user.lang:
        lang = user.lang
    
    # Aseguramos que sea un idioma soportado por tus archivos locales
    if lang not in ("es", "en"):
        lang = "es"

    # 2. Cargar el diccionario de traducciones desde app/i18n/locales/
    translations = {}
    try:
        # Localización de los archivos JSON relativa a este archivo
        base_dir = Path(__file__).resolve().parent.parent
        locale_file = base_dir / "i18n" / "locales" / f"{lang}.json"
        
        if locale_file.exists():
            with open(locale_file, "r", encoding="utf-8") as f:
                translations = json.load(f)
    except Exception:
        # Si hay error al cargar, la función t simplemente devolverá la clave original
        pass

    # 3. Definir la función de traducción 't' que esperan tus templates
    def t(key: str, default: str = None) -> str:
        """Busca la clave en el JSON; si no existe, devuelve la clave misma."""
        return translations.get(key, default or key)

    return lang, t


# --- 🛡️ MOTOR DE SEGURIDAD Y ESCANEO AVANZADO ---

def calcular_distancia_levenshtein(s1: str, s2: str) -> int:
    """
    Calcula cuántos caracteres de diferencia hay entre dos textos.
    Detecta si usan letras parecidas para engañar (ej: mercad0pago, v1sa).
    """
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
    Motor Heurístico Reforzado de AlertTrail.
    Analiza un correo en 4 capas de seguridad y devuelve un Score de Amenaza (0-100).
    """
    score_amenaza = 0
    razones = []
    
    # Limpieza básica de datos de entrada
    remitente = (remitente or "").lower().strip()
    asunto = (asunto or "").strip()
    cuerpo_html = (cuerpo_html or "").strip()
    
    # 📥 EXTRAER DOMINIO REAL DEL REMITENTE
    dominio_remitente = ""
    if "@" in remitente:
        try:
            dominio_remitente = remitente.split("@")[-1].strip()
        except Exception:
            pass

    # 1️⃣ CAPA ANTI-TYPOSQUATTING: ¿Está intentando imitar a una entidad financiera?
    if dominio_remitente:
        for dom_real in DOMINIOS_CRITICOS:
            if dominio_remitente != dom_real:
                distancia = calcular_distancia_levenshtein(dominio_remitente, dom_real)
                # Si la diferencia es de apenas 1 o 2 letras, es un engaño visual casi seguro
                if 1 <= distancia <= 2:
                    score_amenaza += 50
                    razones.append(f"Suplantación de identidad detectada: El remitente de este correo es dangerously similar a '{dom_real}'")
                    break

    # 2️⃣ CAPA HEURÍSTICA DE CONTENIDO: Palabras gatillo de pánico o urgencia económica
    palabras_peligrosas = [
        r"urgente", r"suspensio?n", r"bloqueo", r"venci?miento", 
        r"actualizar datos", r"verificar cuenta", r"token", r"debito inmediato",
        r"acceso no autorizado", r"tarjeta suspendida", r"clonacion"
    ]
    texto_combinado = f"{asunto} {cuerpo_html}".lower()
    
    coincidencias = 0
    for patron in palabras_peligrosas:
        if re.search(patron, texto_combinado):
            coincidencias += 1
            
    if coincidencias >= 2:
        score_amenaza += 25
        razones.append("Patrón psicológico de urgencia o manipulación financiera detectado en el mensaje")

    # 3️⃣ CAPA DE ANÁLISIS DE ENLACES (Desenmascarar Redirecciones)
    enlaces = re.findall(r'href=["\'](https?://[^"\']+)["\']', cuerpo_html, re.IGNORECASE)
    
    for url in enlaces:
        try:
            # Hacemos una petición ligera (HEAD) siguiendo redirecciones para ver a dónde va realmente el usuario
            response = requests.head(url, allow_redirects=True, timeout=2.5)
            url_final = response.url
            dominio_final = urlparse(url_final).netloc.lower()
            
            # Quitar subdominios comunes (ej: www.) para comparar limpio
            if dominio_final.startswith("www."):
                dominio_final = dominio_final[4:]
                
            # Incoherencia crítica: Dice ser de MercadoPago o un Banco, pero el botón te lleva a otra web externa rara
            if dominio_remitente in DOMINIOS_CRITICOS and dominio_final != dominio_remitente:
                score_amenaza += 35
                razones.append(f"Incoherencia de enlace crítica: El correo dice provenir de '{dominio_remitente}' pero sus botones redirigen al dominio sospechoso '{dominio_final}'")
                break
        except Exception:
            # Si el enlace está oculto tras scripts bloqueados o servidores caídos intencionalmente
            score_amenaza += 10
            razones.append("Contiene hipervínculos enmascarados, acortados o con destinos inaccesibles")
            break

    # 📊 CAPA 4: VERDICTO MATEMÁTICO FINAL
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
    """Detecta intentos comunes de inyección de código dentro de archivos log."""
    patrones_ataque = [r"UNION SELECT", r"<script>", r"\.\./\.\./", r"sudo "]
    for patron in patrones_ataque:
        if re.search(patron, log_line, re.IGNORECASE):
            return True
    return False
