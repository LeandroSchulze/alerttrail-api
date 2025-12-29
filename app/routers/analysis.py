# app/routers/analysis.py
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from typing import Dict, Any, Optional
import io, re
from collections import Counter, defaultdict
from datetime import datetime

from app.security import get_current_user_cookie_optional
from app.i18n import get_lang_from_request

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


def _parse_time(s: str) -> datetime | None:
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
        if not m:
            continue
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

        if status >= 500:
            errors_5xx += 1
        if status == 429:
            rate_429 += 1
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
    def row(k, v): return f"<tr><td>{k}</td><td style='text-align:right'>{v}</td></tr>"

    classes = "".join(row(k, v) for k, v in summary["classes"].items())
    status = "".join(row(k, v) for k, v in summary["by_status"].items())
    top_paths = "".join(f"<tr><td>{p}</td><td style='text-align:right'>{c}</td></tr>" for p, c in summary["top_paths"])
    top_ips = "".join(f"<tr><td>{ip}</td><td style='text-align:right'>{c}</td></tr>" for ip, c in summary["top_ips"])
    sqli = "".join(f"<li><code>{line}</code></li>" for line in summary["sqli_hits"])
    probes = "".join(f"<li><code>{line}</code></li>" for line in summary["probe_hits"])
    unauth = "".join(f"<tr><td>{ip}</td><td style='text-align:right'>{c}</td></tr>" for ip, c in summary["unauth_401"])
    admin403 = "".join(f"<tr><td>{ip}</td><td style='text-align:right'>{c}</td></tr>" for ip, c in summary["admin_403"])

    title = _tr(lang, "Resultado de análisis", "Analysis result")
    badge = _tr(lang, "Análisis", "Analysis")
    total_lbl = _tr(lang, "Total de requests", "Total requests")
    classes_lbl = _tr(lang, "Clases", "Classes")
    status_lbl = _tr(lang, "Estados", "Status codes")
    top_paths_lbl = _tr(lang, "Top paths", "Top paths")
    top_ips_lbl = _tr(lang, "Top IPs", "Top IPs")
    unauth_lbl = _tr(lang, "Intentos de login fallidos (401) por IP", "Failed logins (401) per IP")
    admin_lbl = _tr(lang, "Accesos a /admin con 403 por IP", "403 hits to /admin per IP")
    errors_lbl = _tr(lang, "Errores", "Errors")
    sqli_lbl = _tr(lang, "Posibles SQLi", "Possible SQLi")
    probes_lbl = _tr(lang, "Probes de archivos sensibles", "Sensitive file probes")

    return f"""<!doctype html>
<html lang="{lang}">
<meta charset="utf-8">
<title>{title}</title>
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Arial;background:#0b1620;color:#eaf2f7;margin:0}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px}}
h1,h2{{margin:.2rem 0}}
.card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:16px;margin:12px 0}}
table{{width:100%;border-collapse:collapse}}
td,th{{padding:6px;border-bottom:1px solid rgba(255,255,255,.08)}}
code{{white-space:pre-wrap}}
.badge{{display:inline-block;padding:4px 8px;border-radius:10px;background:#0ea5e9;color:#03131c;font-weight:700}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
</style>
<div class="wrap">
  <h1>AlertTrail <span class="badge">{badge}</span></h1>
  <div class="card">
    <div class="mono">{total_lbl}: <b>{summary["total"]}</b></div>
  </div>

  <div class="card"><h2>{classes_lbl}</h2><table>{classes}</table></div>
  <div class="card"><h2>{status_lbl}</h2><table>{status}</table></div>
  <div class="card"><h2>{top_paths_lbl}</h2><table>{top_paths}</table></div>
  <div class="card"><h2>{top_ips_lbl}</h2><table>{top_ips}</table></div>

  <div class="card"><h2>{unauth_lbl}</h2>
    <table>{unauth or "<tr><td colspan=2>—</td></tr>"}</table>
  </div>

  <div class="card"><h2>{admin_lbl}</h2>
    <table>{admin403 or "<tr><td colspan=2>—</td></tr>"}</table>
  </div>

  <div class="card"><h2>{errors_lbl}</h2>
    <div>5xx: <b>{summary["errors_5xx"]}</b> &nbsp; • &nbsp; 429: <b>{summary["rate_429"]}</b></div>
  </div>

  <div class="card"><h2>{sqli_lbl}</h2><ul>{sqli or "<li>—</li>"}</ul></div>
  <div class="card"><h2>{probes_lbl}</h2><ul>{probes or "<li>—</li>"}</ul></div>
</div>
</html>"""


def _is_authed(payload: Optional[Dict[str, Any]]) -> bool:
    """Auth robusto: no alcanza con 'truthy', necesitamos sub."""
    return bool(payload) and bool(payload.get("sub"))


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def analysis_index():
    return RedirectResponse(url="/analysis/generate", status_code=307)


@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not _is_authed(current):
        return RedirectResponse("/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    title = _tr(lang, "Analizar logs", "Analyze logs")
    h1 = _tr(lang, "Analizar logs y generar reporte", "Analyze logs and generate report")
    file_lbl = _tr(lang, "Archivo de log (Nginx/Apache combined)", "Log file (Nginx/Apache combined)")
    pdf_lbl = _tr(lang, "Descargar como PDF", "Download as PDF")
    btn = _tr(lang, "Procesar", "Process")
    hint = _tr(
        lang,
        "¿Necesitás un archivo de prueba? Podés usar el que te compartí en el chat.",
        "Need a sample file? You can use the one shared in the chat.",
    )

    html = f"""<!doctype html><meta charset="utf-8">
    <title>{title}</title>
    <style>
      body{{font-family:system-ui;background:#0b1620;color:#eaf2f7;margin:0}}
      .wrap{{max-width:800px;margin:0 auto;padding:24px}}
      .card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:16px}}
      .btn{{background:#0ea5e9;color:#03131c;padding:10px 14px;border:0;border-radius:10px;font-weight:700;cursor:pointer}}
      input[type=file]{{padding:10px;background:#0e1c27;border:1px solid rgba(255,255,255,.2);border-radius:10px;color:#eaf2f7;width:100%}}
      label{{display:block;margin:10px 0}}
      .hint{{opacity:.85;margin-top:10px}}
    </style>
    <div class="wrap">
      <h1>{h1}</h1>
      <div class="card">
        <form method="post" action="/analysis/analyze" enctype="multipart/form-data">
          <label>{file_lbl}</label>
          <input type="file" name="file" required>
          <label style="margin-top:10px">
            <input type="checkbox" name="pdf" value="1"> {pdf_lbl}
          </label>
          <button class="btn" type="submit">{btn}</button>
          <div class="hint">{hint}</div>
        </form>
      </div>
    </div>
    """
    return HTMLResponse(html)


@router.post("/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    pdf: Optional[str] = Form(None),
    current=Depends(get_current_user_cookie_optional),
):
    if not _is_authed(current):
        return RedirectResponse("/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    summary = analyze_log(text)

    want_pdf = bool(pdf) and str(pdf).strip() in ("1", "true", "on", "yes")

    if want_pdf:
        # PDF simple inline (mantengo el comportamiento actual)
        html = _render_html(summary, lang=lang)
        return HTMLResponse(html)

    return HTMLResponse(_render_html(summary, lang=lang))
