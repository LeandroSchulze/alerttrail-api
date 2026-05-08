// app/static/alert_clients.js
(function () {
  "use strict";

  // =========================
  // Helpers
  // =========================
  function log(...args) {
    console.log("[Push]", ...args);
  }

  function warn(...args) {
    console.warn("[Push]", ...args);
  }

  function error(...args) {
    console.error("[Push]", ...args);
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, "+")
      .replace(/_/g, "/");

    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
  }

  // =========================
  // Get VAPID public key from backend
  // =========================
  async function fetchVapidPublicKey() {
    try {
      const res = await fetch("/push/vapid-public", {
        credentials: "same-origin",
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      if (!data?.vapidPublicKey) {
        throw new Error("Missing vapidPublicKey");
      }

      return data.vapidPublicKey;
    } catch (err) {
      warn("Failed to fetch VAPID public key:", err);
      return null;
    }
  }

  // =========================
  // Main
  // =========================
  async function initPush() {
    if (!("serviceWorker" in navigator)) {
      warn("ServiceWorker not supported");
      return;
    }

    if (!("PushManager" in window)) {
      warn("PushManager not supported");
      return;
    }

    // --- MEJORA: Solicitar permiso si está en 'default' ---
    let permission = Notification.permission;
    if (permission === "default") {
      log("Solicitando permiso de notificación...");
      permission = await Notification.requestPermission();
    }

    if (permission !== "granted") {
      warn("Permiso de notificación no otorgado (Estado: " + permission + ")");
      return;
    }

    const vapidPublicKey = await fetchVapidPublicKey();
    if (!vapidPublicKey) {
      warn("VAPID public key missing, push disabled");
      return;
    }

    let registration;
    try {
      // Usamos .register para asegurar que el sw.js se cargue correctamente
      registration = await navigator.serviceWorker.register('/static/sw.js');
      await navigator.serviceWorker.ready;
      log("ServiceWorker listo");
    } catch (err) {
      error("Error registrando ServiceWorker:", err);
      return;
    }

    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      try {
        log("Creando nueva suscripción...");
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });
        log("Suscripción creada exitosamente");
      } catch (err) {
        error("Fallo al crear la suscripción en el navegador:", err);
        return;
      }
    } else {
      log("Suscripción existente encontrada");
    }

    // Normalize subscription before sending
    const payload = subscription.toJSON ? subscription.toJSON() : subscription;

    try {
      log("Enviando suscripción al servidor Railway...");
      const res = await fetch("/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        warn("El servidor rechazó la suscripción:", res.status);
        return;
      }

      log("Suscripción guardada en la base de datos");
      
      // --- FEEDBACK VISUAL ---
      // Si tienes la función showToast la usamos, sino un alert clásico
      if (typeof showToast === "function") {
        showToast("🔔 Alertas configuradas", "success");
      } else {
        alert("🔔 AlertTrail: Notificaciones activadas");
      }

    } catch (err) {
      error("Error enviando la suscripción al backend:", err);
    }
  }

  // =========================
  // Boot
  // =========================
  document.addEventListener("DOMContentLoaded", () => {
    // Pequeño delay para asegurar que todo el DOM esté listo
    setTimeout(() => {
      initPush().catch((e) => error("Fallo crítico en initPush:", e));
    }, 500);
  });
})();
