# app/routers/analysis.py
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, Optional
import re
from datetime import datetime

from app.security import get_current_user_cookie_optional
from app.i18n.utils import get_lang_and_translator
from app.ui import templates
from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf

router = APIRouter(prefix="/analysis", tags=["Analysis"])

@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def analysis_index():
    return RedirectResponse(url="/analysis/generate", status_code=302)

def _tr(lang: str, es: str, en: str) -> str:
    return en if (lang or "").lower().startswith("en") else es

# --- UI DE RESULTADOS (DASHBOARD OSCURO) ---
def _render_html(results: Dict[str, Any], lang: str = "es", pdf_url: str = None) -> str:
    summary = results.get("summary", {})
    sqli_hits = results.get("sqli_hits", [])
    probe_hits = results.get("probe_hits", [])

    download_btn = ""
    if pdf_url:
        download_btn = f"""
        <a href="{pdf_url}" download class="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-lg shadow-emerald-500/20">
            <span class="text-base">⬇</span> DESCARGAR REPORTE PDF
        </a>
        """

    def row(k, v): 
        return f'<tr class="border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors"><td class="py-2 text-slate-400">{k}</td><td class="py-2 text-right font-mono font-bold text-sky-400">{v}</td></tr>'

    stats_rows = row(_tr(lang, "Total Registros", "Total Records"), summary.get("total", 0))
    stats_rows += row(_tr(lang, "Nivel de Riesgo", "Risk Level"), summary.get("risk", "low").upper())
    stats_rows += row(_tr(lang, "IPs en Fuerza Bruta", "Brute Force IPs"), summary.get("bruteforce_ips", 0))

    sqli_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-red-500/10 border border-red-500/20 rounded text-red-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in sqli_hits)
    probe_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-yellow-500/10 border border-yellow-500/20 rounded text-yellow-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in probe_hits)

    return f"""<!doctype html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Análisis | AlertTrail</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b1620] text-[#eaf2f7] font-sans p-4 md:p-8">
    <div class="max-w-6xl mx-auto">
        <header class="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
            <div>
                <h1 class="text-3xl font-black tracking-tighter uppercase italic text-white">AlertTrail <span class="text-sky-500 text-sm not-italic tracking-widest ml-2">LOG_SCANNER</span></h1>
                <p class="text-slate-500 text-sm italic">Deep traffic security analysis</p>
            </div>
            <div class="flex items-center gap-4">
                {download_btn}
                <div class="bg-sky-500/10 border border-sky-500/20 px-6 py-3 rounded-2xl flex items-center gap-4">
                    <span class="text-xs font-bold uppercase tracking-widest text-sky-500">Total Lines:</span>
                    <span class="text-2xl font-mono font-black text-white">{summary.get("total", 0)}</span>
                </div>
            </div>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
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
    </div>
</body>
</html>"""

# --- UI DE CARGA (FORMULARIO LINDO) ---
@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not current: return RedirectResponse("/auth/login", status_code=302)
    lang, _ = get_lang_and_translator(request, user=current)
    
    title = _tr(lang, "Analizar Logs", "Analyze Logs")
    file_lbl = _tr(lang, "Seleccionar archivo de log", "Select log file")
    pdf_lbl = _tr(lang, "Generar Reporte PDF", "Generate PDF Report")
    btn_text = _tr(lang, "Procesar Ahora", "Process Now")

    return HTMLResponse(f"""<!doctype html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} | AlertTrail</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b1620] text-[#eaf2f7] min-h-screen flex items-center justify-center p-4 font-sans">
    <div class="max-w-md w-full">
        <div class="text-center mb-8">
            <h1 class="text-3xl font-black tracking-tight text-white italic uppercase italic">AlertTrail <span class="text-sky-500 not-italic">Scanner</span></h1>
            <p class="text-slate-400 text-xs mt-2 uppercase tracking-widest">Análisis de seguridad profundo</p>
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
                    {btn_text}
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

    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    results = analyze_log(text, user_id=getattr(current, "id", None))

    pdf_url = None
    if pdf:
        pdf_rel_path = generate_pdf(results, filename_prefix="security_report")
        pdf_url = f"/{pdf_rel_path}"

    return HTMLResponse(_render_html(results, lang=get_lang(request), pdf_url=pdf_url))
