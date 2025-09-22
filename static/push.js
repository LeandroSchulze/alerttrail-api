// static/push.js
async function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4 - base64String.length % 4) % 4);
  const base64=(base64String + padding).replace(/-/g,'+').replace(/_/g,'/');
  const rawData=atob(base64); const outputArray=new Uint8Array(rawData.length);
  for(let i=0;i<rawData.length;i++) outputArray[i]=rawData.charCodeAt(i);
  return outputArray;
}

export async function enablePush(){
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

export async function testPush(){
  const r = await fetch('/push/send-test',{method:'POST'});
  const d = await r.json();
  alert(d.sent ? 'Test enviado (mirá la notificación)' : 'Falló el envío');
}
