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

# --- 🧠 MINI IA THREAT HEURISTIC ENGINE (VERSIÓN MAXIMIZADA) ---

def _limpiar_texto_ofuscado(texto: str) -> str:
    """Elimina caracteres invisibles, ceros por 'o', y símbolos usados para evadir filtros."""
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    texto = texto.lower()
    # Reemplazos comunes de hackers (Ej: m3rcad0pag0 -> mercadopago)
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
    
    # Normalizamos acentos para que los tildes no engañen a las expresiones regulares
    texto_combinado = f"{asunto} {cuerpo_html}".lower()
    texto_combinado_sin_tildes = unicodedata.normalize('NFKD', texto_combinado).encode('ASCII', 'ignore').decode('utf-8')
    
    dominio_remitente = ""
    if "@" in remitente:
        try: dominio_remitente = remitente.split("@")[-1].strip()
        except Exception: pass

    # 1. Capa Anti-Typosquatting Extrema (Analizando dominio crudo y ofuscado)
    if dominio_remitente:
        dominio_limpio = _limpiar_texto_ofuscado(dominio_remitente.split('.')[0])
        for dom_real in DOMINIOS_CRITICOS:
            dom_real_base = dom_real.split('.')[0]
            if dominio_remitente != dom_real:
                # Comparamos distancias de la raíz (ej: mercadopago)
                dist = calcular_distancia_levenshtein(dominio_limpio, dom_real_base)
                if dist == 1 or dist == 2:
                    score_amenaza += 60  # Castigo altísimo
                    razones.append(f"Typosquatting Severo: Remitente intenta suplantar a '{dom_real}'")
                    break

    # 2. Matriz de Urgencia y Extorsión Compuesta (Patrones combinados)
    patrones_extorsion = [
        r"(cuenta|tarjeta).{0,20}(suspendida|bloqueada|restringida)",
        r"(actividad|inicio de sesion).{0,20}(inusual|sospechos[oa])",
        r"(verificar|actualizar|confirmar).{0,20}(identidad|datos|cuenta)",
        r"(pago|transferencia).{0,20}(rechazad[oa]|retenid[oa]|pendiente)",
        r"(evite|evitar).{0,20}(multas|cargos|suspension)"
    ]
    
    # Evaluamos contra el texto sin tildes para mayor efectividad
    coincidencias_compuestas = sum(1 for p in patrones_extorsion if re.search(p, texto_combinado_sin_tildes))
    if coincidencias_compuestas > 0:
        score_amenaza += 35 * coincidencias_compuestas
        razones.append("Ingeniería Social: Tácticas de extorsión o pánico financiero detectadas.")

    # 3. Análisis de Enlaces y Redirecciones Ocultas (Más rápido y tolerante a fallos)
    enlaces = set(re.findall(r'href=["\'](https?://[^"\']+)["\']', cuerpo_html, re.IGNORECASE))
    enlaces_sospechosos = 0
    
    for url in list(enlaces)[:5]: # Límite de 5 enlaces para no ralentizar el escáner
        try:
            # Usamos un timeout estricto de 1.5s. Si el server demora, es mala señal.
            res = requests.head(url, allow_redirects=True, timeout=1.5)
            dominio_final = urlparse(res.url).netloc.lower()
            if dominio_final.startswith("www."): dominio_final = dominio_final[4:]
            
            # 🛡️ CORRECCIÓN CLAVE: Usamos endswith para aceptar subdominios legítimos (ej: pagos.mercadopago.com)
            if dominio_remitente in DOMINIOS_CRITICOS and not dominio_final.endswith(dominio_remitente):
                score_amenaza += 50
                enlaces_sospechosos += 1
                razones.append(f"Phishing Link: Finge ser {dominio_remitente} pero redirige a {dominio_final}")
                break # Con uno falso alcanza para condenarlo
        except requests.RequestException:
            # Sitios caídos o que bloquean HEAD suelen ser infraestructura de atacantes efímera
            score_amenaza += 10
            razones.append(f"Enlace Irrastreable: Contiene URLs ocultas o de infraestructura maliciosa.")

    # 4. Veredicto Final Normalizado
    score_final = min(score_amenaza, 100)
    
    if score_final >= 50: estado = "CRÍTICO"
    elif score_final >= 20: estado = "SOSPECHOSO"
    else: estado = "SEGURO"

    return {"status": estado, "score": score_final, "alerts": list(set(razones))}

def sanitizar_y_escanear_logs(log_line: str) -> bool:
    patrones_ataque = [r"UNION SELECT", r"<script>", r"\.\./\.\./", r"sudo "]
    return any(re.search(p, log_line, re.IGNORECASE) for p in patrones_ataque)
