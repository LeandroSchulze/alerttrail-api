from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, Optional, Union
import io, re
from collections import Counter, defaultdict
from datetime import datetime

from app.security import get_current_user_cookie_optional
from app.i18n import get_lang

router = APIRouter(prefix="/analysis", tags=["Analysis"])

COMBINED_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"\s]+)(?:\s+HTTP/[0-9.]+)?"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"'
)

SQLI_PATTERNS = [
    r"(?i)\bunion\b.+\bselect\b",
    r"(?i)(\bor\b|\band\b)\s+1=1",
    r"(?i)\binformation_schema\b",
    r"(?i)sqlmap",
]
SENSITIVE_FILES = ["/.env", "/wp-login.php", "/phpmyadmin", "/config.php", ".bak", ".zip", ".tar"]

# CORRECCIÓN: Uso de Union para compatibilidad con versiones de Python < 3.10
def _parse_time(s: str) -> Union[datetime, None]:
    try:
        return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")
    except Exception:
        return None

def analyze_log(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    total = 0
    by_status = Counter()
    by_path = Counter()
    by_ip = Counter()
    sqli = []
    probes = []
    errors_5xx = 0
    rate_429 = 0
    unauthorized_401 = Counter()
    admin_forbidden_403 = Counter()
    timeline = defaultdict(int)

    for raw in lines:
        m = COMBINED_RE.match(raw.strip())
        if not m: continue
        total += 1
        ip = m.group("ip")
        path = m.group("path")
        status = int(m.group("status"))
        dt = _parse_time(m.group("time"))
        if dt:
            key = dt.strftime("%Y-%m-%d %H:%M")
            timeline[key] += 1

        by_status[status] += 1
        by_path[path] += 1
        by_ip[ip] += 1

        if status >= 500: errors_5xx += 1
        if status == 429: rate_429 += 1
        if status == 401 and path.endswith("/api/login"):
            unauthorized_401[ip] += 1
        if status == 403 and path.startswith("/admin"):
            admin_forbidden_403[ip] += 1

        for patt in SQLI_PATTERNS:
            if re.search(patt, raw):
                sqli.append(raw)
                break
        for sf in SENSITIVE_FILES:
            if sf in path:
                probes.append(raw)
                break

    classes = Counter()
    for s, c in by_status.items():
        k = f"{s//100}xx"
        classes[k] += c

    return {
        "total": total,
        "classes": dict(classes),
        "by_status": dict(by_status.most_common()),
        "top_paths": by_path.most_common(10),
        "top_ips": by_ip.most_common(10),
        "errors_5xx": errors_5xx,
        "rate_429": rate_429,
        "unauth_401": unauthorized_401.most_common(),
        "admin_403": admin_forbidden_403.most_common(),
        "sqli_hits": sqli[:20],
        "probe_hits": probes[:20],
        "timeline": dict(sorted(timeline.items())),
    }

def _tr(lang: str, es: str, en: str) -> str:
    return en if (lang or "").lower().startswith("en") else es

def _render_html(summary: Dict[str, Any], lang: str = "es") -> str:
    def row(k, v): 
        return f'<tr class="border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors"><td class="py-2 text-slate-400">{k}</td><td class="py-2 text-right font-mono font-bold text-sky-400">{v}</td></tr>'

    classes_rows = "".join(row(k, v) for k, v in summary["classes"].items())
    status_rows = "".join(row(k, v) for k, v in summary["by_status"].items())
    path_rows = "".join(row(p, c) for p, c in summary["top_paths"])
    ip_rows = "".join(row(ip, c) for ip, c in summary["top_ips"])
    
    sqli_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-red-500/10 border border-red-500/20 rounded text-red-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in summary["sqli_hits"])
    probe_list = "".join(f"<li class='mb-2 last:mb-0'><code class='block p-2 bg-yellow-500/10 border border-yellow-500/20 rounded text-yellow-400 text-[10px] break-all leading-tight'>{line}</code></li>" for line in summary["probe_hits"])

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
                <span class="text-xs font-bold uppercase tracking-widest text-sky-500">Total Requests:</span>
                <span class="text-2xl font-mono font-black text-white">{summary["total"]}</span>
            </div>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div class="bg-white/5 border border-white/10 rounded-2xl p-6 shadow-xl backdrop-blur-sm">
                <h2 class="text-xs font-bold uppercase tracking-widest text-sky-400 mb-4 flex items-center">
                    <span class="w-2 h-2 bg-sky-400 rounded-full mr-2 animate-pulse"></span> Status Codes
                </h2>
                <table class="w-full text-sm">{status_rows}</table>
            </div>

            <div class="bg-white/5 border border-white/10 rounded-2xl p-6 shadow-xl backdrop-blur-sm">
                <h2 class="text-xs font-bold uppercase tracking-widest text-sky-400 mb-4 flex items-center">
                    <span class="w-2 h-2 bg-green-400 rounded-full mr-2"></span> Top Paths
                </h2>
                <table class="w-full text-sm">{path_rows}</table>
            </div>

            <div class="bg-white/5 border border-white/10 rounded-2xl p-6 shadow-xl backdrop-blur-sm">
                <h2 class="text-xs font-bold uppercase tracking-widest text-sky-400 mb-4 flex items-center">
                    <span class="w-2 h-2 bg-purple-400 rounded-full mr-2"></span> Top Sources (IP)
                </h2>
                <table class="w-full text-sm">{ip_rows}</table>
            </div>

            <div class="md:col-span-2 lg:col-span-3 grid grid-cols-1 md:grid-cols-2 gap-6">
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
        <footer class="mt-12 text-center text-slate-600 text-[10px] uppercase tracking-[0.2em]">
            AlertTrail Engine &bull; {datetime.now().year}
        </footer>
    </div>
</body>
</html>"""

def _is_authed(payload: Optional[Dict[str, Any]]) -> bool:
    return bool(payload) and bool(payload.get("sub"))

@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def analysis_index():
    return RedirectResponse(url="/analysis/generate", status_code=307)

@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not _is_authed(current):
        return RedirectResponse("/auth/login", status_code=302)

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
            <div class="mt-6 pt-6 border-t border-white/5 text-center">
                <span class="text-[10px] text-slate-500 italic">{hint}</span>
            </div>
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
    if not _is_authed(current):
        return RedirectResponse("/auth/login", status_code=302)

    lang = get_lang(request)
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    summary = analyze_log(text)

    return HTMLResponse(_render_html(summary, lang=lang))
