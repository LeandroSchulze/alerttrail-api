/* app/static/push_client.js */

function urlB64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

async function ensureServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  return await navigator.serviceWorker.register("/static/sw.js");
}

async function subscribePush(publicKey) {
  const reg = await ensureServiceWorker();
  if (!reg) return null;

  const existing = await reg.pushManager.getSubscription();
  if (existing) return existing;

  return await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlB64ToUint8Array(publicKey),
  });
}

async function sendSubscriptionToServer(sub) {
  const res = await fetch("/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
    credentials: "include",
  });
  return await res.json();
}

// Llamalo cuando el usuario toque un botón "Activar notificaciones"
window.enableDesktopAlerts = async function enableDesktopAlerts() {
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      alert("Necesitás permitir notificaciones para recibir alertas en el escritorio.");
      return;
    }

    const cfg = await fetch("/push/config", { credentials: "include" }).then((r) => r.json());
    if (!cfg || !cfg.public_key) {
      alert("Falta configurar VAPID_PUBLIC_KEY en el servidor.");
      return;
    }

    const sub = await subscribePush(cfg.public_key);
    if (!sub) {
      alert("Tu navegador no soporta Push/ServiceWorker en este contexto.");
      return;
    }

    const out = await sendSubscriptionToServer(sub);
    if (out && out.ok) {
      alert("Listo ✅ Te van a llegar alertas al escritorio cuando se detecten mails riesgosos.");
    } else {
      alert("No se pudo registrar la suscripción. Revisar servidor.");
    }
  } catch (e) {
    alert("Error al activar notificaciones: " + (e && e.message ? e.message : e));
  }
};
