# app/utils/__init__.py
import re
import json
import logging
import requests
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from fastapi import Request
from app.i18n import get_lang

logger = logging.getLogger("alerttrail.utils")

# 🏛️ MATRIZ DE INTELIGENCIA DE AMENAZAS DICHAS
DOMINIOS_CRITICOS = [
    "mercadopago.com", "mercadopago.com.ar", "visa.com", "mastercard.com",
    "santander.com.ar", "galicia.com.ar", "bbva.com.ar", "banconacion.com.ar",
    "gmail.com", "outlook.com", "yahoo.com", "paypal.com", "stripe.com", 
    "netflix.com", "amazon.com", "apple.com", "microsoft.com"
]

# Diccionario para cazar a quienes fingen ser una marca sin usar su dominio oficial
MARCAS_CLAVE = {
    "mercado pago": "mercadopago", "mercadopago": "mercadopago", 
    "visa": "visa", "mastercard": "mastercard", 
    "bbva": "bbva", "santander": "santander", 
    "galicia": "galicia", "banco nacion": "bna", "banconacion": "bna",
    "paypal": "paypal", "netflix": "netflix", "amazon": "amazon"
}

# Acortadores que los bancos NO usan pero los hackers sí
ACORTADORES = ["bit.ly", "t.co", "tinyurl.com", "is.gd", "cutt.ly", "shorturl.at", "ow.ly", "buff.ly"]

# --- 🌐 SISTEMA DE INTERNACIONALIZACIÓN GLOBAL ---
def get_lang_and_translator(request: Request = None, user=None):
    lang = "es"
    if user:
        if hasattr(user, "lang") and user.lang: lang = user.lang
        elif hasattr(user, "language") and user.language: lang = user.language
    elif request:
        try: lang = get_lang(request)
        except Exception: pass

    if lang not in ("es", "en"): lang = "es"

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
        return translations.get(key, default or key)
    return lang, t

# --- 🧠 MINI IA THREAT HEURISTIC ENGINE (VERSIÓN BLINDADA) ---

def _limpiar_texto_ofuscado(texto: str) -> str:
    """Elimina caracteres invisibles, ceros por 'o', y símbolos usados para evadir filtros."""
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    texto = texto.lower()
    reemplazos = {'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '@': 'a', '.': '', '-': '', '_': '', ' ': ''}
    texto_limpio = "".join(reemplazos.get(c, c) for c in texto)
    return texto_limpio

def calcular_distancia_levenshtein(s1: str, s2: str) -> int:
    if len(s1) > len(s2): s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2: distances_.append(distances[i1])
            else: distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

def analizar_correo_avanzado(remitente: str, asunto: str, cuerpo_html: str) -> dict:
    score_amenaza = 0
    razones = []
    
    remitente = (remitente or "").lower().strip()
    asunto = (asunto or "").strip()
    cuerpo_html = (cuerpo_html or "").strip()
    
    # 🧹 1. LIMPIEZA EXTREMA: Quitamos HTML y saltos de línea que rompen a la IA
    cuerpo_texto = re.sub(r'<[^>]+>', ' ', cuerpo_html)
    texto_combinado = f"{asunto} {cuerpo_texto}".lower()
    # Aplanamos el texto a una sola línea continua para que el regex no se corte
    texto_combinado = re.sub(r'\s+', ' ', texto_combinado) 
    
    texto_combinado_sin_tildes = unicodedata.normalize('NFKD', texto_combinado).encode('ASCII', 'ignore').decode('utf-8')
    
    dominio_remitente = ""
    if "@" in remitente:
        try: dominio_remitente = remitente.split("@")[-1].strip()
        except Exception: pass

    # --- Capa 0: Suplantación de Marca por Contexto (NUEVA) ---
    if dominio_remitente:
        for marca, dominio_base in MARCAS_CLAVE.items():
            # Si nombra al banco en el mail, pero el mail no viene del banco...
            if marca in texto_combinado_sin_tildes and dominio_base not in dominio_remitente:
                # Perdonamos cuentas de correo masivas estándar (quizás te lo reenviaste vos mismo)
                if dominio_remitente not in ["gmail.com", "hotmail.com", "yahoo.com", "outlook.com"]:
                    score_amenaza += 45
                    razones.append(f"Suplantación de Marca: El correo se hace pasar por '{marca.title()}' pero viene de ({dominio_remitente}).")
                    break

    # --- Capa 1: Anti-Typosquatting Extrema ---
    if dominio_remitente:
        dominio_limpio = _limpiar_texto_ofuscado(dominio_remitente.split('.')[0])
        for dom_real in DOMINIOS_CRITICOS:
            dom_real_base = dom_real.split('.')[0]
            if dominio_remitente != dom_real:
                dist = calcular_distancia_levenshtein(dominio_limpio, dom_real_base)
                if dist == 1 or dist == 2:
                    score_amenaza += 60  
                    razones.append(f"Typosquatting Severo: Remitente intenta suplantar a '{dom_real}'")
                    break

    # --- Capa 2: Matriz de Urgencia y Extorsión Compuesta (Corregida) ---
    # Ampliamos la ventana .{0,40} y usamos raíces de palabras para atrapar más variantes
    patrones_extorsion = [
        r"(cuenta|tarjeta|servicio).{0,40}(suspendi|bloquea|restringi|inhabilit)",
        r"(actividad|inicio de sesion|acceso).{0,40}(inusual|sospechos|no reconocid|desconocid)",
        r"(verific|actualiz|confirm|valid).{0,40}(identidad|datos|cuenta)",
        r"(pago|transferencia|fondos).{0,40}(rechazad|retenid|pendient)",
        r"(evit).{0,40}(multa|cargo|suspension|bloqueo|cierre)"
    ]
    
    coincidencias_compuestas = sum(1 for p in patrones_extorsion if re.search(p, texto_combinado_sin_tildes))
    if coincidencias_compuestas > 0:
        score_amenaza += 35 * coincidencias_compuestas # Con solo 2 patrones ya da 70 puntos (CRÍTICO)
        razones.append("Ingeniería Social: Tácticas de extorsión o pánico financiero detectadas.")

    # --- Capa 3: Análisis de Enlaces y Acortadores (Mejorada) ---
    enlaces = set(re.findall(r'href=["\'](https?://[^"\']+)["\']', cuerpo_html, re.IGNORECASE))
    
    # Si te mandaron el mail en texto plano sin etiquetas <a>, igual extrae la URL:
    if not enlaces:
        enlaces = set(re.findall(r'(https?://[^\s]+)', texto_combinado, re.IGNORECASE))
        
    for url in list(enlaces)[:5]:
        dominio_inicial = urlparse(url).netloc.lower()
        
        # Penalizamos acortadores automáticamente
        if any(acortador in dominio_inicial for acortador in ACORTADORES):
            score_amenaza += 40
            razones.append(f"Enlace Peligroso: Usa un acortador oculto ({dominio_inicial}) muy frecuente en fraudes.")
            break
            
        try:
            res = requests.head(url, allow_redirects=True, timeout=1.5)
            dominio_final = urlparse(res.url).netloc.lower()
            if dominio_final.startswith("www."): dominio_final = dominio_final[4:]
            
            if dominio_remitente in DOMINIOS_CRITICOS and not dominio_final.endswith(dominio_remitente):
                score_amenaza += 50
                razones.append(f"Phishing Link: Finge ser {dominio_remitente} pero redirige a {dominio_final}")
                break 
        except requests.RequestException:
            score_amenaza += 10
            razones.append(f"Enlace Irrastreable: Contiene URLs ocultas o protegidas.")

    # --- 4. Veredicto Final Normalizado ---
    score_final = min(score_amenaza, 100)
    
    if score_final >= 50: estado = "CRÍTICO"
    elif score_final >= 20: estado = "SOSPECHOSO"
    else: estado = "SEGURO"

    return {"status": estado, "score": score_final, "alerts": list(set(razones))}

def sanitizar_y_escanear_logs(log_line: str) -> bool:
    patrones_ataque = [r"UNION SELECT", r"<script>", r"\.\./\.\./", r"sudo "]
    return any(re.search(p, log_line, re.IGNORECASE) for p in patrones_ataque)
