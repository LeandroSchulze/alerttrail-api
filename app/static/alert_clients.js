// app/static/alert_clients.js
(function () {
  "use strict";

  async function initPush() {
    console.log("Iniciando registro de notificaciones...");
    
    // 1. Pedir permiso si no está decidido
    if (Notification.permission === "default") {
      await Notification.requestPermission();
    }

    if (Notification.permission !== "granted") {
      console.warn("Sin permiso de notificaciones.");
      return;
    }

    // 2. Registrar el SW en la raíz (es vital que el archivo esté en /sw.js)
    const registration = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;

    // 3. Obtener la suscripción
    const resVapid = await fetch("/push/vapid-public");
    const { vapidPublicKey } = await resVapid.json();

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: (function(base64String) {
          const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
          const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
          const rawData = window.atob(base64);
          return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
        })(vapidPublicKey)
      });
    }

    // 4. Guardar en Railway
    await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription),
    });

    console.log("✅ Suscripción completada.");
    alert("¡Alertas activadas! Ya podés cerrar esta ventana.");
  }

  // Ejecutar inmediatamente
  initPush().catch(err => console.error("Error en Push:", err));
})();
