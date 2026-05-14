// app/static/alert_clients.js
(function () {
  "use strict";

  async function initPush() {
    console.log("🚀 Iniciando registro de notificaciones AlertTrail...");
    
    // 1. Verificar si el navegador es compatible
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      console.warn("Este navegador no soporta notificaciones Push.");
      return;
    }

    // 2. Pedir permiso si no está decidido
    let permission = Notification.permission;
    if (permission === "default") {
      permission = await Notification.requestPermission();
    }

    if (permission !== "granted") {
      console.warn("Permiso de notificaciones denegado por el usuario.");
      return;
    }

    // 3. Registrar el SW desde la RAÍZ (Gracias al cambio en main.py esto ya no da 404)
    // Usamos '/' para que el Service Worker tenga control total sobre la app
    const registration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/'
    });
    
    await navigator.serviceWorker.ready;
    console.log("✅ Service Worker listo y activo.");

    // 4. Obtener la clave pública VAPID del servidor
    const resVapid = await fetch("/push/vapid-public");
    const { vapidPublicKey } = await resVapid.json();

    if (!vapidPublicKey) {
      console.error("No se pudo obtener la VAPID Public Key del servidor.");
      return;
    }

    // 5. Gestionar la suscripción
    let subscription = await registration.pushManager.getSubscription();
    
    if (!subscription) {
      console.log("Generando nueva suscripción...");
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

    // 6. Enviar la suscripción a Railway para guardarla en la DB
    const response = await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription),
    });

    if (response.ok) {
      console.log("✅ Suscripción guardada en el servidor.");
      // Solo mostramos el alert la primera vez que se activa con éxito
      if (Notification.permission === "granted" && !localStorage.getItem('push_notified')) {
          alert("¡Alertas activadas con éxito! Ya podés recibir notificaciones en este dispositivo.");
          localStorage.setItem('push_notified', 'true');
      }
    } else {
      console.error("Error al guardar la suscripción en el servidor:", response.status);
    }
  }

  // Ejecutar inmediatamente al cargar el script
  initPush().catch(err => {
    console.error("❌ Error crítico en el flujo de Push:", err);
  });
})();
