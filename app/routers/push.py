# app/routers/push.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models_push import PushSubscription
from app.security import get_current_user_cookie
from app.utils.push import get_vapid_public_key, send_web_push

router = APIRouter(prefix="/push", tags=["push"])


# ---------------------------
# Helper público para enviar push a un usuario (lo usa mail._notify_alert)
# ---------------------------
def send_push_to_user(db: Session, user_id: int, payload: dict) -> bool:
    """
    Envía un WebPush a todas las suscripciones del user_id.
    payload: {"title": "...", "body": "...", "url": "/ruta", "tag": "opcional"}
    Devuelve True si al menos una notificación se envió OK.
    """
    subs = db.query(PushSubscription).filter_by(user_id=user_id).all()
    if not subs:
        return False

    ok_any = False
    for sub in subs:
        subscription = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        }
        try:
            if send_web_push(subscription, payload):
                ok_any = True
        except Exception:
            # Si falla por suscripción inválida, no se borra automáticamente.
            # Se puede limpiar más adelante (status 410 Gone).
            continue
    return ok_any


# =======================
# Endpoints públicos
# =======================
@router.get("/pubkey")
def pubkey():
    """Devuelve la clave pública VAPID para registrar el Service Worker."""
    pk = get_vapid_public_key()
    if not pk:
        raise HTTPException(status_code=500, detail="Falta VAPID_PUBLIC_KEY en el servidor")
    return {"vapid_public_key": pk}


@router.post("/subscribe")
async def subscribe(
    req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """Registra una suscripción de WebPush para el usuario actual."""
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    data = await req.json()
    endpoint = data.get("endpoint")
    keys = (data.get("keys") or {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not (endpoint and p256dh and auth):
        raise HTTPException(status_code=400, detail="Suscripción inválida")

    existing = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if existing:
        existing.user_id = user.id
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        ps = PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        db.add(ps)
    db.commit()
    return {"ok": True, "detail": "Suscripción registrada correctamente"}


@router.post("/unsubscribe")
async def unsubscribe(
    req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """Elimina una suscripción específica de WebPush."""
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    data = await req.json()
    endpoint = data.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint requerido")

    row = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.post("/send-test")
def send_test(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """Envía una notificación push de prueba al usuario actual (solo PRO o BIZ)."""
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    plan = (getattr(user, "plan", "") or "").upper()
    if plan not in ("PRO", "BIZ", "EMPRESAS", "EMPRESA"):
        raise HTTPException(status_code=403, detail="Solo usuarios PRO o EMPRESAS")

    payload = {
        "title": "AlertTrail",
        "body": "Notificación de prueba enviada correctamente 🚀",
        "url": "/mail/scanner",
    }
    sent = send_push_to_user(db, user.id, payload)
    if not sent:
        sub = db.query(PushSubscription).filter_by(user_id=user.id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="No hay suscripción registrada")
    return {"ok": True, "sent": bool(sent)}


# =======================
# Página de prueba simple (independiente del dashboard)
# =======================
@router.get("/test-page", response_class=HTMLResponse)
def test_page():
    """Página HTML de prueba para activar y probar notificaciones Push."""
    html = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>AlertTrail Push Test</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script>
async function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4 - base64String.length % 4) % 4);
  const base64=(base64String + padding).replace(/-/g,'+').replace(/_/g,'/');
  const rawData=atob(base64);
  const outputArray=new Uint8Array(rawData.length);
  for(let i=0;i<rawData.length;i++) outputArray[i]=rawData.charCodeAt(i);
  return outputArray;
}
async function enablePush(){
  if(!('serviceWorker' in navigator) || !('PushManager' in window)){
    alert('Este navegador no soporta notificaciones push');
    return;
  }
  const perm = await Notification.requestPermission();
  if(perm!=='granted'){ alert('Permiso denegado'); return; }
  const reg = await navigator.serviceWorker.register('/sw.js');
  const kp = await fetch('/push/pubkey').then(r=>r.json());
  let sub = await reg.pushManager.getSubscription();
  if(!sub){
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: await urlBase64ToUint8Array(kp.vapid_public_key)
    });
  }
  await fetch('/push/subscribe',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(sub)
  });
  alert('✅ Notificaciones activadas correctamente');
}
async function testPush(){
  const r = await fetch('/push/send-test',{method:'POST'});
  const d = await r.json();
  alert(d.sent ? 'Test enviado (revisá la notificación)' : (d.detail || 'Falló el envío'));
}
</script>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:2rem;}
button{padding:.75rem 1rem;border-radius:.75rem;border:1px solid #ccc;background:#f6f6f9;cursor:pointer}
button+button{margin-left:.5rem}
</style>
</head>
<body>
  <h1>AlertTrail — Prueba de Notificaciones</h1>
  <p>1️⃣ Activá las notificaciones y aceptá el permiso del navegador.</p>
  <p>2️⃣ Luego presioná "Enviar prueba" (requiere usuario PRO o EMPRESAS).</p>
  <div>
    <button onclick="enablePush()">🔔 Activar notificaciones</button>
    <button onclick="testPush()">▶ Enviar prueba</button>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)
