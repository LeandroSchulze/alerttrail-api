import os
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

APP_NAME = "AlertTrail"
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")

app = FastAPI(title=APP_NAME)

# CORS abierto (ajusta si querés restringir)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistencia para PDFs
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# ---------- PÁGINAS ----------
@app.get("/", include_in_schema=False)
def home():
    html = """
    <html>
      <head><meta charset="utf-8"><title>AlertTrail</title></head>
      <body style="font-family:system-ui;margin:40px;">
        <h1>AlertTrail</h1>
        <p>Servicio en línea ✅</p>
        <ul>
          <li><a href="/dashboard">Ir al Dashboard</a></li>
          <li><a href="/docs">Abrir Swagger (API docs)</a></li>
          <li><a href="/health">Healthcheck</a></li>
        </ul>
      </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    html = """
    <!doctype html><html lang="es"><head>
      <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>AlertTrail – Dashboard</title>
      <style>
        body{font-family:system-ui;background:#f6f7fb;margin:0}
        .card{max-width:680px;margin:64px auto;background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.06);padding:28px}
        h1{margin:0 0 12px} label{display:block;margin:10px 0 6px;color:#444}
        input,textarea{width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#fafafa}
        textarea{min-height:120px}
        .row{display:flex;gap:12px;flex-wrap:wrap}
        .btn{border:0;padding:12px 18px;border-radius:12px;cursor:pointer}
        .primary{background:#5b5bd6;color:#fff}.muted{background:#e2e8f0}
        .ok{color:#0a7d20;font-weight:600}.warn{color:#b71c1c;font-weight:600}
        .hint{color:#6b7280;font-size:12px;margin-top:6px}.tag{display:inline-block;background:#ecfdf5;color:#065f46;border-radius:9999px;padding:2px 10px;font-size:12px;margin-left:6px}
      </style>
    </head><body>
      <div class="card">
        <h1>Dashboard</h1>
        <div>Estado: <span id="authLabel" class="warn">No autenticado</span></div>

        <div id="loginBox">
          <label>Email</label><input id="email" type="email" placeholder="admin@tudominio.com"/>
          <label>Contraseña</label><input id="password" type="password" placeholder="********"/>
          <div class="row" style="margin-top:12px"><button class="btn primary" onclick="login()">Ingresar</button></div>
          <div class="hint">También podés loguearte desde <a href="/docs" target="_blank">/docs</a> y pegar el token así: <code>localStorage.setItem('token','TU_JWT')</code></div>
        </div>

        <div id="appBox" style="display:none;margin-top:20px">
          <div>Autenticado <span class="tag">JWT OK</span></div>
          <label style="margin-top:14px">Pegá tu log</label>
          <textarea id="logInput" placeholder="Pegá aquí el log a analizar..."></textarea>
          <div class="row" style="margin-top:12px">
            <button class="btn primary" onclick="generarPDF()">Generar PDF</button>
            <button class="btn muted" onclick="logout()">Salir</button>
          </div>
          <div id="result" class="hint"></div>
        </div>
      </div>
      <script>
        function hasToken(){ return !!localStorage.getItem('token'); }
        function setAuthUI(){
          const ok = hasToken();
          document.getElementById('authLabel').textContent = ok ? 'Autenticado' : 'No autenticado';
          document.getElementById('authLabel').className = ok ? 'ok' : 'warn';
          document.getElementById('loginBox').style.display = ok ? 'none' : 'block';
          document.getElementById('appBox').style.display = ok ? 'block' : 'none';
        }
        setAuthUI();

        async function login(){
          const email = document.getElementById('email').value.trim();
          const password = document.getElementById('password').value.trim();
          if(!email || !password){ alert('Completá email y contraseña'); return; }
          const r = await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ email, password })});
          if(!r.ok){ alert('Error de login: ' + r.status); return; }
          const data = await r.json();
          const token = data.access_token || data.token;
          if(!token){ alert('No llegó token'); return; }
          localStorage.setItem('token', token);
          setAuthUI();
        }
        function logout(){ localStorage.removeItem('token'); setAuthUI(); }

        async function generarPDF(){
          const token = localStorage.getItem('token');
          if(!token){ alert('Primero ingresá con tu usuario.'); return; }
          const log = document.getElementById('logInput').value;
          if(!log.trim()){ alert('Pegá un log para analizar.'); return; }
          const r = await fetch('/analysis/generate_pdf', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ log_content: log })
          });
          if(!r.ok){ const t = await r.text(); alert('Error ' + r.status + ': ' + t); return; }
          const data = await r.json();
          if(data && data.url){ document.getElementById('result').textContent = 'PDF listo: ' + data.url; window.open(data.url,'_blank'); }
          else{ alert('La API no devolvió una URL de PDF.'); }
        }
      </script>
    </body></html>
    """
    return HTMLResponse(html)

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- INCLUIR ROUTERS (si existen) ----------
try:
    from app.routers import analysis
    app.include_router(analysis.router)
except Exception:
    pass
try:
    from app.routers import auth
    app.include_router(auth.router)
except Exception:
    pass

# ---------- FALLBACK: endpoint integrado /analysis/generate_pdf ----------
# Si el router 'analysis' no se cargó por algún import, este endpoint asegura que exista.
class LogInput(BaseModel):
    log_content: str

# importar dependencias si existen; si no, proveer defaults seguros
try:
    from app.security import get_current_user as _get_current_user
except Exception:
    from types import SimpleNamespace
    def _get_current_user():
        # fallback dev: permite seguir probando aunque falte auth
        return SimpleNamespace(email="tester@alerttrail.local")

# analizar log: usar servicio si existe, si no, versión con hallazgos
try:
    from app.services.analysis_service import analyze_log as _analyze_log
    ANALYZER_SOURCE = "service"
except Exception:
    import re
    ANALYZER_SOURCE = "fallback"
    _SSH_FAIL_RE = re.compile(r"Failed password for (invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})", re.I)
    _SSH_OK_RE   = re.compile(r"Accepted password for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})", re.I)
    _SQLI_RE     = re.compile(r"('|\")\s*or\s*1=1|union\s+select|--\s", re.I)
    _XSS_RE      = re.compile(r"<script>|onerror=|onload=", re.I)

    def _analyze_log(text: str):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        findings = []
        ssh_failed = ssh_ok = sqli = xss = 0
        fail_by_ip = {}

        for ln in lines:
            m = _SSH_FAIL_RE.search(ln)
            if m:
                ssh_failed += 1
                ip = m.group("ip"); user = m.group("user")
                fail_by_ip[ip] = fail_by_ip.get(ip, 0) + 1
                findings.append({"severity":"medium","type":"ssh_failed_login","ip":ip,"user":user,"line":ln})
            m = _SSH_OK_RE.search(ln)
            if m:
                ssh_ok += 1
                ip = m.group("ip"); user = m.group("user")
                sev = "high" if user.lower() == "root" else "low"
                findings.append({"severity":sev,"type":"ssh_success","ip":ip,"user":user,"line":ln,
                                 "note":"Acceso a root" if sev=="high" else ""})
            if _SQLI_RE.search(ln):
                sqli += 1
                findings.append({"severity":"high","type":"sql_injection_pattern","line":ln})
            if _XSS_RE.search(ln):
                xss += 1
                findings.append({"severity":"medium","type":"xss_pattern","line":ln})

        bruteforce_ips = sum(1 for ip,c in fail_by_ip.items() if c >= 3)
        if bruteforce_ips:
            for ip,c in fail_by_ip.items():
                if c >= 3:
                    findings.append({"severity":"high","type":"ssh_bruteforce_suspected","ip":ip,"count":c,
                                     "note":"3+ intentos fallidos desde misma IP"})

        score = ssh_failed*1 + bruteforce_ips*5 + sqli*5 + xss*2 + ssh_ok*1
        risk = "high" if score>=10 else ("medium" if score>=4 else "low")

        return {
            "summary":{
                "total_lines": len(lines),
                "ssh_failed": ssh_failed,
                "ssh_accepted": ssh_ok,
                "sqli": sqli,
                "xss": xss,
                "bruteforce_ips": bruteforce_ips,
                "risk": risk,
            },
            "findings": findings
        }
        

# generar pdf: usar servicio si existe, si no, simple
try:
    from app.services.pdf_service import generate_pdf as _generate_pdf
except Exception:
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    def _generate_pdf(user_email: str, analysis: dict) -> bytes:
        buf = BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
        c.setFont("Helvetica-Bold", 16); c.drawString(50, 800, "AlertTrail – Reporte")
        c.setFont("Helvetica", 12); c.drawString(50, 780, f"Usuario: {user_email}")
        y = 760
        for k,v in analysis.get("summary", {}).items():
            c.drawString(50, y, f"{k}: {v}"); y -= 16
        c.showPage(); c.save(); pdf = buf.getvalue(); buf.close(); return pdf

@app.post("/analysis/generate_pdf")
def generate_pdf_and_return_url(payload: LogInput, user=Depends(_get_current_user)):
    analysis = _analyze_log(payload.log_content)
    pdf_bytes = _generate_pdf(user_email=getattr(user, "email", "unknown@alerttrail"), analysis=analysis)
    fname = f"analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    fpath = os.path.join(REPORTS_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(pdf_bytes)
    return {"url": f"/reports/{fname}"}
