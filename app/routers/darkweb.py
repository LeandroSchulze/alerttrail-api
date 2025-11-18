# app/routers/darkweb.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(tags=["darkweb"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


BASE_STYLE = """
:root{
  --bg:#0b1120;
  --card:#020617;
  --border:#1e293b;
  --text:#e5e7eb;
  --muted:#94a3b8;
  --accent:#38bdf8;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#0f172a,#020617);
     font-family:system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;color:var(--text);}
.container{max-width:980px;margin:32px auto;padding:0 16px}
.card{background:rgba(15,23,42,.92);border:1px solid var(--border);
      border-radius:18px;box-shadow:0 18px 60px rgba(15,23,42,.75);padding:20px}
h1{font-size:1.8rem;margin:0 0 8px;color:var(--accent);}
h2{font-size:1.2rem;margin:16px 0 8px;color:#e5e7eb;}
p{margin:4px 0;}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;
       padding:4px 10px;border-radius:999px;
       border:1px solid rgba(56,189,248,.6);background:rgba(8,47,73,.7);color:#e0f2fe;}
.badge span.dot{width:7px;height:7px;border-radius:999px;background:#22c55e;
                box-shadow:0 0 10px rgba(34,197,94,.9);}
.grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);
      gap:18px;margin-top:16px;}
ul{padding-left:18px;margin:6px 0;}
li{margin-bottom:4px;}
.btn-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}
.btn{padding:10px 14px;border-radius:999px;border:1px solid #1e293b;
     background:#020617;color:#e5e7eb;cursor:pointer;font-size:14px;
     text-decoration:none;display:inline-flex;align-items:center;gap:6px;}
.btn.primary{background:linear-gradient(to right,#0ea5e9,#6366f1);
             border-color:transparent;color:white;}
.btn.primary:hover{filter:brightness(1.05);}
.btn.secondary:hover{border-color:#38bdf8;}
.muted{color:var(--muted);font-size:14px;}
"""


def _get_user_plan(request: Request, db: Session) -> str:
    """
    Devuelve el plan del usuario actual en MAYÚSCULAS.
    Si no hay usuario o algo falla, devuelve 'FREE'.
    """
    try:
        payload = get_current_user_cookie(request)
    except Exception:
        return "FREE"

    try:
        user_id = payload.get("sub")
        if not user_id:
            return "FREE"
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            return "FREE"
        return (getattr(u, "plan", None) or "FREE").upper()
    except Exception:
        return "FREE"


@router.get("/darkweb", include_in_schema=False, response_class=HTMLResponse)
@router.get("/darkweb/", include_in_schema=False, response_class=HTMLResponse)
def darkweb_radar_page(request: Request, db: Session = Depends(get_db)):
    plan = _get_user_plan(request, db)
    pro_like = {"PRO", "BIZ", "EMPRESA", "EMPRESAS", "ENTERPRISE"}

    is_pro = plan in pro_like

    if is_pro:
        badge = "Incluido en tu plan PRO / EMPRESAS"
        subtitle = "Vista previa del monitor de filtraciones incluido en tu cuenta."
        state_text = (
            "Tu cuenta PRO ya está marcada para acceder a este módulo cuando lo "
            "liberemos. Mientras tanto, podés usar esta pantalla para explicar a tu "
            "equipo qué hace Dark Web Radar."
        )
        cta_label = "Ver tu suscripción"
    else:
        badge = "Módulo PRO • Vista previa"
        subtitle = "Vista previa del monitor de filtraciones para tus emails y dominios."
        state_text = (
            "En esta versión solo ves la vista previa. Para activar el monitoreo real "
            "de filtraciones, pasá a un plan PRO o EMPRESAS."
        )
        cta_label = "Ver planes PRO"

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Dark Web Radar — AlertTrail</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> {badge}</div>
    <h1>Dark Web Radar</h1>
    <p class="muted">{subtitle}</p>

    <div class="grid">
      <div>
        <h2>¿Qué va a hacer esta función?</h2>
        <p>La idea es que Dark Web Radar te avise si aparecen credenciales o datos sensibles
        vinculados a tus correos o dominios en foros, dumps o mercados de la dark web.</p>
        <ul>
          <li>Vigilancia continua de emails corporativos.</li>
          <li>Alertas cuando se detectan combinaciones email/contraseña filtradas.</li>
          <li>Resumen ejecutivo para que el equipo no técnico entienda el riesgo.</li>
        </ul>
        <p class="muted">{state_text}</p>

        <div class="btn-row">
          <a href="/billing/subscriptions" class="btn primary">{cta_label}</a>
          <a href="/dashboard" class="btn secondary">Volver al dashboard</a>
        </div>
      </div>
      <div>
        <h2>Ejemplo de alerta</h2>
        <p class="muted">Así podría verse una alerta dentro de AlertTrail:</p>
        <div style="margin-top:8px;padding:10px 12px;border-radius:14px;
                    border:1px solid #1e293b;background:rgba(15,23,42,.9);">
          <p style="margin:0 0 4px;"><strong>Posible filtración detectada</strong></p>
          <p class="muted" style="margin:0 0 6px;">Encontramos credenciales asociadas a
          <b>admin@tudominio.com</b> en una base de datos filtrada.</p>
          <p class="muted" style="margin:0 0 4px;">Recomendamos:</p>
          <ul>
            <li>Forzar cambio de contraseña del usuario.</li>
            <li>Revisar si se usó la misma clave en otros servicios.</li>
            <li>Habilitar 2FA cuando sea posible.</li>
          </ul>
        </div>
        <h2 style="margin-top:16px;">Estado actual</h2>
        <p class="muted">
          No hay escaneo real en esta versión, pero la integración ya está preparada
          para activarse primero en cuentas PRO y EMPRESAS.
        </p>
      </div>
    </div>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)
