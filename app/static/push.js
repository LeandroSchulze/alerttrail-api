// static/push.js
async function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4 - base64String.length % 4) % 4);
  const base64=(base64String + padding).replace(/-/g,'+').replace(/_/g,'/');
  const rawData=atob(base64);
  const outputArray=new Uint8Array(rawData.length);
  for(let i=0;i<rawData.length;i++) outputArray[i]=rawData.charCodeAt(i);
  return outputArray;
}

async function getVapidKey(){
  const r = await fetch('/push/pubkey');
  if(!r.ok) throw new Error('No se pudo obtener la VAPID public key');
  const data = await r.json();
  return data.vapid_public_key;
}

export async function enablePush(){
  try{
    if(!('serviceWorker' in navigator) || !('PushManager' in window)){
      alert('Este navegador no soporta notificaciones push.'); return;
    }
    const perm = await Notification.requestPermission();
    if(perm!=='granted'){ alert('Permiso de notificaciones denegado.'); return; }

    // 👇 ahora el SW vive en /sw.js (scope "/")
    const reg = await navigator.serviceWorker.register('/sw.js');

    let sub = await reg.pushManager.getSubscription();
    if(!sub){
      const vapid = await getVapidKey();
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: await urlBase64ToUint8Array(vapid)
      });
    }

    const res = await fetch('/push/subscribe',{
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(sub)
    });
    if(!res.ok) throw new Error('No se pudo registrar la suscripción');

    alert('Notificaciones activadas ✅');
  }catch(e){
    console.error('enablePush error', e);
    alert('No se pudieron activar las push notifications.');
  }
}

export async function testPush(){
  try{
    const r = await fetch('/push/send-test',{method:'POST'});
    const d = await r.json();
    alert(d.sent ? 'Test enviado (mirá la notificación)' : (d.detail || 'Falló el envío'));
  }catch(e){
    alert('Falló el envío de prueba');
  }
}
