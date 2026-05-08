(function () {
  "use strict";

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
  }

  async function initPush() {
    // PASO 1: Inicio
    alert("1. Iniciando script de Push...");

    if (!("serviceWorker" in navigator)) {
      alert("ERROR: Tu navegador no soporta Service Workers");
      return;
    }

    // PASO 2: Permisos
    let permission = Notification.permission;
    alert("2. Permiso actual: " + permission);

    if (permission === "default") {
      alert("3. Solicitando permiso al navegador...");
      permission = await Notification.requestPermission();
    }

    if (permission !== "granted") {
      alert("STOP: No diste permiso. Estado: " + permission);
      return;
    }

    // PASO 3: VAPID Key
    alert("4. Buscando llave VAPID en el servidor...");
    let vapidPublicKey = null;
    try {
      const resVapid = await fetch("/push/vapid-public");
      const data = await resVapid.json();
      vapidPublicKey = data.vapidPublicKey;
    } catch (e) {
      alert("ERROR en Paso 4: No pude conectar con /push/vapid-public");
      return;
    }

    if (!vapidPublicKey) {
      alert("STOP: El servidor no envió la llave VAPID.");
      return;
    }

    // PASO 4: Service Worker
    alert("5. Registrando Service Worker...");
    let registration;
    try {
      // Intentamos registrarlo. Asegurate que el archivo esté en esa ruta.
      registration = await navigator.serviceWorker.register('/static/sw.js');
      await navigator.serviceWorker.ready;
      alert("6. Service Worker listo y activo");
    } catch (err) {
      alert("ERROR en Paso 6: No se pudo registrar sw.js. ¿Existe el archivo?");
      return;
    }

    // PASO 5: Suscripción
    alert("7. Creando suscripción de Push...");
    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      try {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });
        alert("8. Suscripción creada en el navegador");
      } catch (err) {
        alert("ERROR en Paso 8: " + err.message);
        return;
      }
    }

    // PASO 6: Guardado en Railway
    alert("9. Enviando datos a la base de datos...");
    try {
      const res = await fetch("/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(subscription),
      });

      if (res.ok) {
        alert("🎉 ¡TODO LISTO! Ya podés recibir pop-ups.");
      } else {
        alert("ERROR en Paso 9: Railway rechazó el guardado. Status: " + res.status);
      }
    } catch (err) {
      alert("ERROR FINAL: No pude conectar con Railway para guardar.");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Esperamos 1 segundo para no interrumpir la carga inicial
    setTimeout(initPush, 1000);
  });
})();
