# app/routers/training.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["training"])

BASE_STYLE = """
:root{
  --bg:#f8fafc;
  --card:#ffffff;
  --border:#e2e8f0;
  --text:#0f172a;
  --muted:#64748b;
  --accent:#2563eb;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#e0f2fe,#f8fafc);
     font-family:system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;color:var(--text);}
.container{max-width:980px;margin:32px auto;padding:0 16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:18px;
      box-shadow:0 18px 60px rgba(15,23,42,.08);padding:20px}
h1{font-size:1.8rem;margin:0 0 8px;color:var(--accent);}
h2{font-size:1.2rem;margin:16px 0 8px;}
p{margin:4px 0;}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;
       padding:4px 10px;border-radius:999px;border:1px solid rgba(37,99,235,.3);
       background:#eff6ff;color:#1d4ed8;}
.grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);
      gap:18px;margin-top:16px;}
ul{padding-left:18px;margin:6px 0;}
li{margin-bottom:4px;}
.btn-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}
.btn{padding:10px 14px;border-radius:999px;border:1px solid #d1d5db;
     background:#ffffff;color:#111827;cursor:pointer;font-size:14px;
     text-decoration:none;display:inline-flex;align-items:center;gap:6px;}
.btn.primary{background:linear-gradient(to right,#2563eb,#4f46e5);
             border-color:transparent;color:white;}
.btn.primary:hover{filter:brightness(1.05);}
.btn.secondary:hover{border-color:#2563eb;}
.muted{color:var(--muted);font-size:14px;}
.question-card{border-radius:16px;border:1px solid #e2e8f0;padding:12px;
               margin-top:8px;background:#f9fafb;}
.option{display:flex;align-items:flex-start;gap:8px;margin-top:6px;}
.option input{margin-top:4px;}
"""

HTML_PAGE = f"""<!doctype html>
<meta charset="utf-8">
<title>Phishing Training — AlertTrail</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge">Módulo educativo • Ideal como extra PRO</div>
    <h1>Phishing Training</h1>
    <p class="muted">Módulo de entrenamiento para ayudar a tu equipo a detectar
    emails y mensajes sospechosos.</p>

    <div class="grid">
      <div>
        <h2>¿Cómo funcionará?</h2>
        <p>La idea es ofrecer <b>lecciones cortas</b> y <b>quizzes</b>, y guardar
        el progreso por usuario.</p>
        <ul>
          <li>Escenarios reales de phishing (bancos, criptos, soporte técnico).</li>
          <li>Preguntas de opción múltiple con feedback inmediato.</li>
          <li>Certificado interno cuando el usuario completa el módulo.</li>
        </ul>
        <p class="muted">Por ahora es una demo visual. Más adelante lo podemos conectar
        a tu base de datos y mostrar estadísticas por organización.</p>

        <div class="btn-row">
          <a href="/billing/subscriptions" class="btn primary">Ofrecer como add-on PRO</a>
          <a href="/dashboard" class="btn secondary">Volver al dashboard</a>
        </div>
      </div>
      <div>
        <h2>Ejemplo de lección</h2>
        <div class="question-card">
          <p><b>Situación:</b> Recibís un correo diciendo que tu cuenta será suspendida
          en 24 horas si no hacés clic en un enlace para “verificar tu identidad”.</p>
          <p class="muted" style="margin-top:6px;">¿Qué deberías hacer?</p>
          <div class="option">
            <input type="radio" disabled>
            <span>Hacer clic en el enlace inmediatamente para no perder la cuenta.</span>
          </div>
          <div class="option">
            <input type="radio" disabled checked>
            <span>Ignorar el enlace, entrar al sitio escribiendo la URL manualmente
              y verificar desde tu cuenta oficial si hay algún aviso.</span>
          </div>
          <div class="option">
            <input type="radio" disabled>
            <span>Responder al correo pidiendo más información.</span>
          </div>
        </div>
        <p class="muted" style="margin-top:8px;">En la versión completa, estas respuestas
        se guardarían por usuario y podrías ver un reporte de quién necesita más
        entrenamiento.</p>
      </div>
    </div>
  </div>
</div>
</body>
"""

# Cubrimos /training y /training/
@router.get("/training", include_in_schema=False, response_class=HTMLResponse)
@router.get("/training/", include_in_schema=False, response_class=HTMLResponse)
def training_page():
    return HTMLResponse(HTML_PAGE)
