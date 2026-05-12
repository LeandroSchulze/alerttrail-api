# app/routers/analysis.py
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, Optional, Union
import io, re
from collections import Counter, defaultdict
from datetime import datetime

from app.security import get_current_user_cookie_optional
from app.i18n import get_lang, t # Importamos t para las plantillas
from app.ui import templates
from app.services.pdf_service import generate_pdf # Importamos tu generador

router = APIRouter(prefix="/analysis", tags=["Analysis"])

# Regex de log (ahora es opcional para que no descarte líneas)
COMBINED_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"\s]+)(?:\s+HTTP/[0-9.]+)?"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"'
)

# Patrones mejorados para detectar lo que te pasé ayer
SQLI_PATTERNS = [
    r"(?i)\bunion\b.+\bselect\b",
    r"(?i)(\bor\b|\band\b)\s+['\" ]*1['\" ]*=.*1", # Detecta '1'='1'
    r"(?i)\binformation_schema\b",
    r"(?i)sqlmap",
]
SENSITIVE_FILES = ["/.env", "/wp-login.php", "/etc/passwd", "config.php", ".bak", "boot.ini"]

def _parse_time(s: str) -> Union[datetime, None]:
    try: return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")
    except: return None

def analyze_log(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    summary = {
        "total": 0, "classes": Counter(), "by_status": Counter(),
        "top_paths": Counter(), "top_ips": Counter(),
        "sqli_hits": [], "probe_hits": [], "timeline": defaultdict(int)
    }

    for raw in lines:
        raw_strip = raw.strip()
        if not raw_strip: continue
        
        summary["total"] += 1
        m = COMBINED_RE.match(raw_strip)
        
        # 1. Si matchea el formato, extraemos estadísticas
        if m:
            ip, path = m.group("ip"), m.group("path")
            status = int(m.group("status"))
            summary["by_status"][status] += 1
            summary["classes"][f"{status//100}xx"] += 1
            summary["top_paths"][path] += 1
            summary["top_ips"][ip] += 1
            dt = _parse_time(m.group("time"))
            if dt: summary["timeline"][dt.strftime("%Y-%m-%d %H:%M")] += 1
        else:
            path = raw_strip # Fallback para logs de otros formatos

        # 2. Análisis de Seguridad (SÍ O SÍ para cada línea)
        for patt in SQLI_PATTERNS:
            if re.search(patt, raw_strip):
                summary["sqli_hits"].append(raw_strip)
                break
        
        for sf in SENSITIVE_FILES:
            if sf in raw_strip: # Buscamos en toda la línea, no solo en 'path'
                summary["probe_hits"].append(raw_strip)
                break

    # Formatear para el template
    summary["by_status"] = dict(summary["by_status"].most_common())
    summary["top_paths"] = summary["top_paths"].most_common(10)
    summary["top_ips"] = summary["top_ips"].most_common(10)
    summary["sqli_hits"] = summary["sqli_hits"][:20]
    summary["probe_hits"] = summary["probe_hits"][:20]
    return summary

# ... (Mantenemos _tr y _render_html igual) ...

@router.post("/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    pdf: Optional[str] = Form(None),
    current=Depends(get_current_user_cookie_optional),
):
    if not current: return RedirectResponse("/auth/login", status_code=302)

    lang = get_lang(request)
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    
    # Realizar el análisis
    summary = analyze_log(text)

    # CORRECCIÓN: Si marcó PDF, generar y mostrar pantalla de descarga
    if pdf:
        # report_data para el PDF (puedes pasarle el summary completo o simplificado)
        pdf_rel_path = generate_pdf(summary, filename_prefix="security_report")
        
        return templates.TemplateResponse(
            request=request,
            name="pdf_ready.html",
            context={
                "request": request,
                "lang": lang,
                "t": t,
                "url": f"/{pdf_rel_path}", # Esto irá al botón de descarga
                "user": current
            }
        )

    # Si no, mostrar resultado HTML normal
    return HTMLResponse(_render_html(summary, lang=lang))
