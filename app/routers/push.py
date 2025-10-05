# app/routers/push.py
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..models_push import PushSubscription
from ..security import get_current_user_cookie
from ..utils.push import get_vapid_public_key, send_web_push

router = APIRouter(prefix="/push", tags=["push"])

@router.get("/pubkey")
def pubkey():
    pk = get_vapid_public_key()
    if not pk:
        raise HTTPException(status_code=500, detail="Falta VAPID_PUBLIC_KEY en el servidor")
    return {"vapid_public_key": pk}

@router.post("/subscribe")
async def subscribe(
    req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie)
):
    data = await req.json()
    endpoint = data.get("endpoint")
    keys = (data.get("keys") or {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not (endpoint and p256dh and auth):
        raise HTTPException(status_code=400, detail="Suscripción inválida")

    existing = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if existing:
        # Actualizamos dueño y claves por si cambiaron
        existing.user_id = user.id
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        ps = PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        db.add(ps)
    db.commit()
    return {"ok": True}

@router.post("/unsubscribe")
async def unsubscribe(
    req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie)
):
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
def send_test(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    plan = (getattr(user, "plan", "") or "").upper()
    if plan not in ("PRO", "BIZ", "EMPRESAS", "EMPRESA"):
        raise HTTPException(status_code=403, detail="Solo usuarios PRO o EMPRESAS")
    sub = db.query(PushSubscription).filter_by(user_id=user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="No hay suscripción registrada")
    subscription = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
    ok = send_web_push(subscription, {"title":"AlertTrail","body":"Notificación de prueba","url":"/mail/scanner"})
    return {"sent": bool(ok)}

# Página de prueba simple (no toca tu dashboard)
@router.get("/test-page", response_class=HTMLResponse)
def test_page():
    html = """
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"/><title>AlertTrail Push Test</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script>
async function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4 - base64String.length % 4) % 4);
  const base64=(base64String + padding).replace(/-/g,'+').replace(/_/g,'/');
  const rawData=atob(base64); const outputArray=new Uint8Array(rawData.length);
  for(let i=0;i<rawData.length;i++) outputArray[i]=rawData.charCodeAt(i);
  return outputArray;
}
async function enablePush(){
  if(!('serviceWorker' in navigator) || !('PushManager' in window)){ alert('Sin soporte Push'); return; }
  const perm = await Notification.requestPermission();
  if(perm!=='granted'){ alert('Permiso denegado'); return; }
  const reg = await navigator.serviceWorker.register('/static/sw.js');
  const kp = await fetch('/push/pubkey').then(r=>r.json());
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: await urlBase64ToUint8Array(kp.vapid_public_key)
  });
  await fetch('/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});
  alert('Notificaciones activadas ✅');
}
async function testPush(){
  const r = await fetch('/push/send-test',{method:'POST'});
  const d = await r.json();
  alert(d.sent ? 'Test enviado (mirá la notificación)' : (d.detail || 'Falló el envío'));
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
  <p>1) Activá notificaciones y aceptá el permiso del navegador.</p>
  <p>2) Luego presioná Enviar prueba (tu usuario debe ser PRO o EMPRESAS).</p>
  <div>
    <button onclick="enablePush()">🔔 Activar notificaciones</button>
    <button onclick="testPush()">▶ Enviar prueba</button>
  </div>
</body></html>
"""
    return HTMLResponse(html)
