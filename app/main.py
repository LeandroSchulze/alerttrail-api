import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

APP_NAME = "AlertTrail"
REPORTS_DIR = os.getenv("REPORTS_DIR", "/var/data/reports")

app = FastAPI(title=APP_NAME)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Carpeta persistente para PDFs
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# Home
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

# Dashboard simple (login + análisis + PDF)
@app.get("/dashboard", include_in_schema=False)
def dashboard():
    html = """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>AlertTrail – Dashboard</title>
      <style>
        body{font-family:system-ui;background:#f6f7fb;margin:0}
        .card{max-width:680px;margin:64px auto;background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.06);padding:28px}
        h1{margin:0 0 12px}
        label{display:block;margin:10px 0 6px;color:#444}
        input,textarea{width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#fafafa}
        textarea{min-height:120px}
        .row{display:flex;gap:12px;flex-wrap:wrap}
        .btn{border:0;padding:12px 18px;border-radius:12px;cursor:pointer}
        .primary{background:#5b5bd6;color:#fff}
        .muted{background:#e2e8f0}
        .ok{color:#0a7d20;font-weight:600}
        .warn{color:#b71c1c;font-weight:600}
        .hint{color:#6b7280;font-size:12px;margin-top:6px}
        .tag{display:inline-block;background:#ecfdf5;color:#065f46;border-radius:9999px;padding:2px 10px;font-size:12px;margin-left:6px}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Dashboard</h1>
        <div id="authState">Estado: <span id="authLabel" class="warn">No autenticado</span></div>

        <div id="loginBox">
          <label>Email</label>
          <input id="email" type="email" placeholder="admin@tudominio.com"/>
          <label>Contraseña</label>
          <input id="password" type="password" placeholder="********"/>
          <div class="row" style="margin-top:12px">
            <button class="btn primary" onclick="login()">Ingresar</button>
          </div>
          <div class="hint">También podés loguearte desde <a href="/docs" target="_blank">/docs</a> y pegar el token aquí: <code>localStorage.setItem('token','TU_JWT')</code></div>
        </div>

        <div id="appBox" style="display:none;margin-top:20px">
          <div>Autenticado <span class="tag">JWT OK</span></div>
          <label style="margin-top:14px">Pega tu log</label>
          <textarea id="logInput" placeholder="Pegá aquí el log a analizar..."></textarea>
          <div class="row" style="margin-top:12px">
            <button class="btn primary" onclick="generarPDF()">Generar PDF</button>
            <button class="btn muted" onclick="logout()">Salir</button>
          </div>
          <div id="result" class="hint"></div>
        </div>
      </div>

      <script>
        const API = ''; // rutas relativas al mismo host

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
          const r = await fetch(API + '/auth/login', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ email, password })
          });
          if(!r.ok){ alert('Error de login: ' + r.status); return; }
          const data = await r.json();
          const token = data.access_token || data.token;
          if(!token){ alert('No llegó token'); return; }
          localStorage.setItem('token', token);
          setAuthUI();
        }

        function logout(){
          localStorage.removeItem('token');
          setAuthUI();
        }

        async function generarPDF(){
          const token = localStorage.getItem('token');
          if(!token){ alert('Primero ingresá con tu usuario.'); return; }
          const log = document.getElementById('logInput').value;
          if(!log.trim()){ alert('Pegá un log para analizar.'); return; }

          const r = await fetch(API + '/analysis/generate_pdf', {
            method:'POST',
            headers:{
              'Content-Type':'application/json',
              'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({ log_content: log })
          });
          if(!r.ok){
            const t = await r.text();
            alert('Error ' + r.status + ': ' + t);
            return;
          }
          const data = await r.json();
          if(data && data.url){
            document.getElementById('result').textContent = 'PDF listo: ' + data.url;
            window.open(data.url, '_blank');
          }else{
            alert('La API no devolvió una URL de PDF.');
          }
        }
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

# Healthcheck
@app.get("/health")
def health():
    return {"status": "ok"}

# Incluir routers si existen
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
try:
    from app.routers import profile
    app.include_router(profile.router)
except Exception:
    pass
try:
    from app.routers import admin
    app.include_router(admin.router)
except Exception:
    pass
try:
    from app.routers import settings
    app.include_router(settings.router)
except Exception:
    pass
