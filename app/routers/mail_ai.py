# app/routers/mail_ai.py
import os
import html as _html
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(tags=["mail_ai"])


# ---------- DB helper ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Utils de usuario/plan ----------
def _get_user_and_plan(request: Request, db: Session) -> (Optional[User], str):
    try:
        payload = get_current_user_cookie(request)
    except Exception:
        return None, "FREE"

    try:
        user_id = payload.get("sub")
        if not user_id:
            return None, "FREE"
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            return None, "FREE"

        plan = (getattr(u, "plan", None) or "FREE").upper()
        # Si es admin y tiene plan FREE, lo tratamos como PRO
        if getattr(u, "is_admin", False) or getattr(u, "is_superuser", False):
            if plan == "FREE":
                plan = "PRO"
        return u, plan
    except Exception:
        return None, "FREE"


def _is_pro_like(plan: str) -> bool:
    return plan in {"PRO", "BIZ", "EMPRESA", "EMPRESAS", "ENTERPRISE"}


# ---------- Motor de análisis (heurístico/IA-lite) ----------

PHISH_KEYWORDS = [
    "verify", "verification", "update", "password", "account", "urgent", "immediately",
    "suspend", "closure", "login", "security alert",
    "verificar", "actualizar", "contraseña", "cuenta", "urgente", "inmediatamente",
    "suspendida", "bloqueada", "factura", "pago", "banco",
]

PHISH_BRANDS = [
    "paypal", "microsoft", "google", "amazon", "icloud", "apple", "outlook",
    "santander", "bbva", "galicia", "mercado pago", "mercadopago", "afip",
]

SUSPICIOUS_TLDS = [
    ".ru", ".cn", ".top", ".xyz", ".club", ".support", ".click", ".loan", ".work",
]


def _analyze_text_risk(subject: str, body: str, from_email: str) -> Dict[str, Any]:
    """
    Analizador heurístico de riesgo de phishing para un correo.
    Devuelve score 0-100, nivel (BAJO/MEDIO/ALTO), veredicto, razones y consejos.
    """
    text = f"{subject}\n{body}".lower()
    score = 10  # base
    reasons: List[str] = []

    # Links
    link_count = text.count("http://") + text.count("https://")
    if "://bit.ly" in text or "://tinyurl" in text:
        score += 15
        reasons.append("Usa links acortados (difícil saber a dónde llevan).")
    if link_count >= 1:
        score += 10
        reasons.append("Incluye al menos un enlace.")
    if link_count >= 3:
        score += 10
        reasons.append("Incluye muchos enlaces, típico de campañas masivas.")

    # Palabras típicas de phishing
    kw_hits = [w for w in PHISH_KEYWORDS if w in text]
    if kw_hits:
        inc = min(35, 10 + len(kw_hits) * 3)
        score += inc
        reasons.append(
            "Usa vocabulario típico de phishing: "
            + f"{', '.join(sorted(set(kw_hits)))[:120]}."
        )

    # Marcas suplantadas
    brand_hits = [b for b in PHISH_BRANDS if b in text]
    if brand_hits:
        score += 15
        reasons.append(
            "Menciona marcas sensibles (posible suplantación): "
            + ", ".join(sorted(set(brand_hits)))
        )

    # Presión temporal
    if "24 horas" in text or "24hs" in text or "48 horas" in text:
        score += 5
        reasons.append("Añade presión temporal (24/48 horas).")

    # From email
    from_l = (from_email or "").lower()
    if from_l:
        at = from_l.split("@")[-1]
        for tld in SUSPICIOUS_TLDS:
            if at.endswith(tld):
                score += 10
                reasons.append(f"El remitente usa un dominio con TLD inusual: {tld}.")
                break
        if any(b in from_l for b in PHISH_BRANDS) and not any(b in text for b in PHISH_BRANDS):
            reasons.append("El remitente parece usar una marca conocida en el email.")
            score += 5

    # Normalizar a 0–100
    score = max(0, min(100, score))

    if score >= 75:
        level = "ALTO"
        verdict = "Probable phishing"
    elif score >= 45:
        level = "MEDIO"
        verdict = "Sospechoso"
    else:
        level = "BAJO"
        verdict = "Poco probable que sea phishing"

    advice: List[str] = []
    if level in {"ALTO", "MEDIO"}:
        advice.append("No hagas clic en enlaces ni descargues adjuntos hasta confirmar con el remitente por otro canal.")
        advice.append("Si el correo dice ser de un banco o servicio, entrá escribiendo la URL manualmente en tu navegador.")
        advice.append("Avisá al equipo de seguridad o responsable de IT si confirmás que es phishing.")
    else:
        advice.append("Aunque el riesgo parezca bajo, evitá reutilizar contraseñas y activá 2FA siempre que puedas.")

    return {
        "score": score,
        "level": level,
        "verdict": verdict,
        "reasons": reasons,
        "advice": advice,
    }


# ---------- Estilos para la página de prueba ----------
BASE_STYLE = """
:root{
  --bg:#020617;
  --card:#020617;
  --border:#1e293b;
  --text:#e5e7eb;
  --muted:#94a3b8;
  --accent:#38bdf8;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#0f172a,#020617);
     font-family:system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;color:var(--text);}
.container{max-width:960px;margin:32px auto;padding:0 16px}
.card{background:rgba(15,23,42,.96);border:1px solid var(--border);
      border-radius:18px;box-shadow:0 18px 60px rgba(15,23,42,.75);padding:20px}
h1{font-size:1.6rem;margin:0 0 8px;color:var(--accent);}
p{margin:4px 0;}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;
       padding:4px 10px;border-radius:999px;
       border:1px solid rgba(56,189,248,.6);background:rgba(8,47,73,.7);color:#e0f2fe;}
.badge span.dot{width:7px;height:7px;border-radius:999px;background:#22c55e;
                box-shadow:0 0 10px rgba(34,197,94,.9);}
.form-grid{display:grid;gap:10px;margin-top:12px;}
textarea,input{width:100%;border-radius:10px;border:1px solid #1e293b;
               background:#020617;color:#e5e7eb;padding:8px 10px;font-size:14px;}
label{font-size:13px;color:var(--muted);}
button{margin-top:8px;padding:8px 14px;border-radius:999px;border:none;
       background:linear-gradient(to right,#0ea5e9,#6366f1);color:white;
       font-size:14px;cursor:pointer;}
button:hover{filter:brightness(1.05);}
.result-card{margin-top:16px;padding:12px 14px;border-radius:14px;
             border:1px solid #1e293b;background:rgba(15,23,42,.9);}
.result-badge{display:inline-block;font-size:12px;padding:3px 8px;border-radius:999px;
              border:1px solid rgba(248,250,252,.2);margin-bottom:4px;}
.result-badge.ALTO{border-color:#fb7185;color:#fecaca;}
.result-badge.MEDIO{border-color:#fbbf24;color:#fef3c7;}
.result-badge.BAJO{border-color:#4ade80;color:#bbf7d0;}
.small{font-size:12px;color:var(--muted);}
"""


# ---------- Página HTML de prueba ----------
@router.get("/mail/ai/test", include_in_schema=False, response_class=HTMLResponse)
def mail_ai_test_page(
    request: Request,
    db: Session = Depends(get_db),
):
    user, plan = _get_user_and_plan(request, db)
    is_pro = _is_pro_like(plan)
    badge = "Incluido en PRO / EMPRESAS" if is_pro else "Disponible en planes PRO / EMPRESAS"

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>AI Mail Phishing Analyst — AlertTrail</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> {badge}</div>
    <h1>AI Mail Phishing Analyst</h1>
    <p class="small">
      Probá el motor de análisis de phishing sobre un correo concreto. Ideal para demos y para validar cómo explica el riesgo.
    </p>

    <form method="post" action="/mail/ai/test">
      <div class="form-grid">
        <div>
          <label>Remitente (From)</label>
          <input type="text" name="from_email" placeholder="ej: Banco Ejemplo &lt;notificaciones@banco-ejemplo.com&gt;">
        </div>
        <div>
          <label>Asunto (Subject)</label>
          <input type="text" name="subject" placeholder="ej: URGENTE: se ha bloqueado tu cuenta">
        </div>
        <div>
          <label>Contenido del correo</label>
          <textarea name="body" rows="6" placeholder="Pegá acá el cuerpo del mensaje..."></textarea>
        </div>
      </div>
      <button type="submit">Analizar riesgo</button>
    </form>

    <p class="small" style="margin-top:10px;">
      Tip: copiá y pegá un correo de phishing real que tengas en tu casilla y probá qué score le asigna.
    </p>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)


@router.post("/mail/ai/test", include_in_schema=False, response_class=HTMLResponse)
def mail_ai_test_submit(
    request: Request,
    from_email: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    user, plan = _get_user_and_plan(request, db)
    is_pro = _is_pro_like(plan)
    badge = "Incluido en PRO / EMPRESAS" if is_pro else "Disponible en planes PRO / EMPRESAS"

    analysis = _analyze_text_risk(subject or "", body or "", from_email or "")

    from_safe = _html.escape(from_email or "", quote=True)
    subject_safe = _html.escape(subject or "", quote=True)
    body_safe = _html.escape(body or "", quote=True).replace("\n", "<br>")

    reasons_html = "".join(f"<li>{_html.escape(r, quote=True)}</li>" for r in analysis["reasons"])
    advice_html = "".join(f"<li>{_html.escape(a, quote=True)}</li>" for a in analysis["advice"])

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>AI Mail Phishing Analyst — Resultado</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> {badge}</div>
    <h1>AI Mail Phishing Analyst</h1>
    <p class="small">
      Resultado del análisis sobre el correo que pegaste abajo.
    </p>

    <div class="result-card">
      <div class="result-badge {analysis['level']}">
        Riesgo {analysis['level']} — Score: {analysis['score']}/100
      </div>
      <p><strong>Veredicto:</strong> {analysis['verdict']}</p>
      <p class="small"><strong>Remitente:</strong> {from_safe or "-"}<br>
         <strong>Asunto:</strong> {subject_safe or "-"}</p>

      <p><strong>Factores detectados:</strong></p>
      <ul>{reasons_html or "<li>No se encontraron señales fuertes de phishing.</li>"}</ul>

      <p><strong>Recomendaciones:</strong></p>
      <ul>{advice_html}</ul>
      <p class="small" style="margin-top:8px;">
        Nota: este motor usa reglas y heurísticas diseñadas para phishing. No garantiza al 100% que un correo sea legítimo o malicioso,
        pero ayuda a priorizar qué revisar primero.
      </p>
    </div>

    <h2 style="margin-top:18px;font-size:1rem;">Correo analizado</h2>
    <div class="result-card">
      <p class="small"><strong>From:</strong> {from_safe or "-"}</p>
      <p class="small"><strong>Subject:</strong> {subject_safe or "-"}</p>
      <p class="small" style="margin-top:8px;">{body_safe or "<i>(sin contenido)</i>"}</p>
    </div>

    <form method="post" action="/mail/ai/test" style="margin-top:14px;">
      <div class="form-grid">
        <div>
          <label>Remitente (From)</label>
          <input type="text" name="from_email" value="{from_safe}">
        </div>
        <div>
          <label>Asunto (Subject)</label>
          <input type="text" name="subject" value="{subject_safe}">
        </div>
        <div>
          <label>Contenido del correo</label>
          <textarea name="body" rows="6">{_html.escape(body or "", quote=False)}</textarea>
        </div>
      </div>
      <button type="submit">Volver a analizar</button>
    </form>

    <p class="small" style="margin-top:10px;">
      Más adelante, este mismo motor se puede usar directamente desde el Mail Scanner de AlertTrail para analizar correos reales de tu casilla.
    </p>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)


# ---------- Endpoint JSON para integrar luego con el Mail Scanner ----------
@router.post("/mail/ai/analyze", response_class=JSONResponse)
def mail_ai_analyze_api(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Endpoint JSON para integrar con el Mail Scanner via fetch.
    Espera un body JSON con: subject, from_email, body.
    Solo disponible para planes PRO / EMPRESAS.
    """
    user, plan = _get_user_and_plan(request, db)
    is_pro = _is_pro_like(plan)

    if not user:
        raise HTTPException(status_code=401, detail="No autenticado.")

    if not is_pro:
        # Si querés, podés cambiar a 402 para marcarlo como "se requiere pago"
        raise HTTPException(status_code=403, detail="Analizador IA disponible solo en planes PRO / EMPRESAS.")

    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    from_email = (payload.get("from_email") or "").strip()

    analysis = _analyze_text_risk(subject, body, from_email)

    return {
        "ok": True,
        "plan": plan,
        "analysis": analysis,
    }
