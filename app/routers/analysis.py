# app/routers/analysis.py
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, Optional
import re
from datetime import datetime

from app.security import get_current_user_cookie_optional
from app.i18n import get_lang, t
from app.ui import templates
from app.services.analysis_service import analyze_log # <--- CEREBRO UNIFICADO
from app.services.pdf_service import generate_pdf     # <--- GENERADOR PDF

router = APIRouter(prefix="/analysis", tags=["Analysis"])

def _tr(lang: str, es: str, en: str) -> str:
    return en if (lang or "").lower().startswith("en") else es

def _render_html(results: Dict[str, Any], lang: str = "es") -> str:
    # Extraemos los datos del diccionario que devuelve el servicio
    summary = results.get("summary", {})
    sqli_hits = results.get("sqli_hits", [])
    probe_hits = results.get("probe_hits", [])

    def row(k, v): 
        return f'<tr class="border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors"><td class="py-2 text-slate-400">{k}</td><td class="py-2 text-right font-mono font-bold text-sky-400">{v}</td></tr>'

    # Construimos las filas de la tabla de estadísticas
    stats_rows = row(_tr(lang, "Total Registros", "Total Records"), summary.get("total", 0))
    stats_rows += row(_tr(lang, "Nivel de Riesgo", "Risk Level"), summary.get("risk", "low").upper())
    stats_rows += row(_tr(lang, "Intentos SSH", "SSH Failed"), summary.get("ssh_failed", 0))
    stats_rows += row(_tr(lang, "IPs Bloqueadas", "Blocked IPs"), summary.get("bruteforce_ips", 0))

    sqli_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-red-500/10 border border-red-500/20 rounded text-red-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in sqli_hits)
    probe_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-yellow-500/10 border border-yellow-500/20 rounded text-yellow-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in probe_hits)

    title = _tr(lang, "Resultado de análisis", "Analysis Result")
    
    return f"""<!doctype html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} | AlertTrail</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b1620] text-[#eaf2f7] font-sans p-4 md:p-8">
    <div class="max-w-6xl mx-auto">
        <header class="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
            <div>
                <h1 class="text-3xl font-black tracking-tighter uppercase italic text-white">AlertTrail <span class="text-sky-500 text-sm not-italic tracking-widest ml-2">LOG_SCANNER</span></h1>
                <p class="text-slate-500 text-sm italic">Deep traffic security analysis</p>
            </div>
            <div class="bg-sky-500/10 border border-sky-500/20 px-6 py-3 rounded-2xl flex items-center gap-4 shadow-lg shadow-sky-500/5">
                <span class="text-xs font-bold uppercase tracking-widest text-sky-500">Total Lines:</span>
                <span class="text-2xl font-mono font-black text-white">{summary.get("total", 0)}</span>
            </div>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <div class="bg-white/5 border border-white/10 rounded-2xl p-6 shadow-xl backdrop-blur-sm">
                <h2 class="text-xs font-bold uppercase tracking-widest text-sky-400 mb-4 flex items-center">
                    <span class="w-2 h-2 bg-sky-400 rounded-full mr-2 animate-pulse"></span> Metrics Summary
                </h2>
                <table class="w-full text-sm">{stats_rows}</table>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="bg-red-500/5 border border-red-500/10 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <h2 class="text-xs font-bold uppercase tracking-widest text-red-400 mb-4 uppercase">SQL Injection Hits</h2>
                <ul class="space-y-2">{sqli_list or "<li class='text-slate-600 text-sm italic'>No threats detected</li>"}</ul>
            </div>

            <div class="bg-yellow-500/5 border border-yellow-500/10 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <h2 class="text-xs font-bold uppercase tracking-widest text-yellow-400 mb-4 uppercase">Sensitive File Probes</h2>
                <ul class="space-y-2">{probe_list or "<li class='text-slate-600 text-sm italic'>No suspicious probes</li>"}</ul>
            </div>
        </div>
        <footer class="mt-12 text-center text-slate-600 text-[10px] uppercase tracking-[0.2em]">
            AlertTrail Engine &bull; {datetime.now().year}
        </footer>
    </div>
</body>
</html>"""

@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not current: return RedirectResponse("/auth/login", status_code=302)

    lang = get_lang(request)
    title = _tr(lang, "Analizar logs", "Analyze logs")
    h1 = _tr(lang, "Analizar logs y generar reporte", "Analyze logs and report")
    file_lbl = _tr(lang, "Archivo de log (Nginx/Apache combined)", "Log file (Nginx/Apache)")
    pdf_lbl = _tr(lang, "Descargar como PDF", "Download as PDF")
    btn = _tr(lang, "Procesar", "Process Now")
    hint = _tr(lang, "¿Necesitás un archivo de prueba?", "Need a sample file?")

    return HTMLResponse(f"""<!doctype html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b1620] text-[#eaf2f7] min-h-screen flex items-center justify-center p-4 font-sans">
    <div class="max-w-md w-full">
        <div class="text-center mb-8">
            <h1 class="text-2xl font-black tracking-tight text-white italic uppercase italic">AlertTrail <span class="text-sky-500 not-italic">Scanner</span></h1>
            <p class="text-slate-400 text-xs mt-2 uppercase tracking-widest">{h1}</p>
        </div>

        <div class="bg-white/5 border border-white/10 rounded-3xl p-8 backdrop-blur-md shadow-2xl">
            <form method="post" action="/analysis/analyze" enctype="multipart/form-data" class="space-y-6">
                <div>
                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-sky-500 mb-3">{file_lbl}</label>
                    <input type="file" name="file" required 
                        class="block w-full text-xs text-slate-400
                        file:mr-4 file:py-2 file:px-4
                        file:rounded-xl file:border-0
                        file:text-xs file:font-bold
                        file:bg-sky-500 file:text-[#03131c]
                        hover:file:bg-sky-400 transition-all
                        cursor-pointer bg-[#0e1c27] border border-white/10 rounded-xl p-2">
                </div>
                
                <label class="flex items-center space-x-3 cursor-pointer group">
                    <input type="checkbox" name="pdf" value="1" class="w-4 h-4 rounded border-white/20 bg-transparent text-sky-500 focus:ring-sky-500">
                    <span class="text-xs font-medium text-slate-400 group-hover:text-sky-300 transition-colors uppercase tracking-wider">{pdf_lbl}</span>
                </label>

                <button class="w-full bg-sky-500 hover:bg-sky-400 text-[#03131c] py-4 rounded-xl font-black uppercase tracking-widest transition-all transform hover:scale-[1.02] shadow-lg shadow-sky-500/20" type="submit">
                    {btn}
                </button>
            </form>
        </div>
    </div>
</body>
</html>""")

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
    
    # 1. Llamamos al servicio unificado (este sí acepta user_id)
    results = analyze_log(text, user_id=getattr(current, "id", None))
    
    # 2. Lógica para el PDF
    if pdf:
        # Generar PDF usando el diccionario de sumario
        pdf_rel_path = generate_pdf(results["summary"], filename_prefix="security_report")
        
        return templates.TemplateResponse(
            request=request,
            name="pdf_ready.html",
            context={
                "request": request,
                "url": f"/{pdf_rel_path}",
                "lang": lang,
                "t": t,
                "user": current
            }
        )

    # 3. Mostrar Dashboard HTML
    return HTMLResponse(_render_html(results, lang=lang))
