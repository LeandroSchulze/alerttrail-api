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

      if (!data || !data.vapidPublicKey) {
        throw new Error("Missing vapidPublicKey in response");
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
      warn("Service workers not supported");
      return;
    }

    if (!("PushManager" in window)) {
      warn("PushManager not supported");
      return;
    }

    const permission = Notification.permission;
    log("Notification permission:", permission);

    if (permission !== "granted") {
      log("Push notifications not granted");
      return;
    }

    const vapidPublicKey = await fetchVapidPublicKey();
    if (!vapidPublicKey) {
      warn("VAPID public key missing, push disabled");
      return;
    }

    let registration;
    try {
      registration = await navigator.serviceWorker.ready;
    } catch (err) {
      error("ServiceWorker not ready:", err);
      return;
    }

    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      try {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });

        log("Push subscription created");
      } catch (err) {
        error("Failed to subscribe:", err);
        return;
      }
    } else {
      log("Existing push subscription found");
    }

    // Send subscription to backend
    try {
      const res = await fetch("/push/subscribe", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
        body: JSON.stringify(subscription),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      log("Push subscription sent to server");
    } catch (err) {
      error("Failed to send subscription to backend:", err);
    }
  }

  // =========================
  // Boot
  // =========================
  document.addEventListener("DOMContentLoaded", () => {
    initPush().catch((e) => error("Init push failed:", e));
  });
})();
