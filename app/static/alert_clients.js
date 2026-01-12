// app/static/alert_clients.js
// AlertTrail - Desktop popups + Toasts + PUSH

(function () {
  const POLL_MS = Number(window.ALERT_POLL_MS || 10000);
  let lastId = null;
  let permissionAsked = false;
  let pushInitialized = false;

  /* -------------------- TOAST -------------------- */
  function notifyToast(a) {
    try {
      if (!window.toaster) return false;

      const sev = String(a.severity || "info").toLowerCase();
      const title = a.title || "Alerta";
      const body = a.body || "";

      if (sev === "high" || sev === "error") {
        window.toaster.error(title, body);
        return true;
      }
      if (sev === "medium" || sev === "warn" || sev === "warning") {
        window.toaster.warning(title, body);
        return true;
      }
      window.toaster.info(title, body);
      return true;
    } catch (e) {
      return false;
    }
  }

  /* -------------------- PERMISSION -------------------- */
  async function ensureNotificationPermission() {
    if (!("Notification" in window)) return "unsupported";
    if (Notification.permission === "granted") return "granted";
    if (Notification.permission === "denied") return "denied";
    if (permissionAsked) return Notification.permission;

    permissionAsked = true;
    try {
      return await Notification.requestPermission();
    } catch (e) {
      return Notification.permission;
    }
  }

  /* -------------------- NATIVE (fallback) -------------------- */
  async function notifyNative(a) {
    try {
      const perm = await ensureNotificationPermission();
      if (perm !== "granted") return false;

      const n = new Notification(a.title || "Alerta", {
        body: a.body || "",
        tag: a.id || undefined,
      });

      setTimeout(() => {
        try { n.close(); } catch (e) {}
      }, 12000);

      return true;
    } catch (e) {
      return false;
    }
  }

  /* -------------------- PUSH SETUP -------------------- */
  async function initPush() {
    if (pushInitialized) return;
    if (!("serviceWorker" in navigator)) return;

    try {
      const perm = await ensureNotificationPermission();
      if (perm !== "granted") return;

      const reg = await navigator.serviceWorker.register("/static/sw.js");

      const existing = await reg.pushManager.getSubscription();
      if (existing) {
        pushInitialized = true;
        return;
      }

      const vapidKey = window.VAPID_PUBLIC_KEY;
      if (!vapidKey) {
        console.warn("VAPID public key missing");
        return;
      }

      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      });

      await fetch("/push/subscribe", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub),
      });

      pushInitialized = true;
    } catch (e) {
      console.error("Push init failed", e);
    }
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  /* -------------------- POLLING -------------------- */
  async function poll() {
    try {
      const r = await fetch("/alerts/pending", { credentials: "include" });
      if (!r.ok) return;

      const data = await r.json();
      if (!data || !data.ok || !data.pending || !data.alert) return;

      const a = data.alert;
      if (!a || !a.id) return;
      if (lastId && String(a.id) === String(lastId)) return;

      lastId = a.id;
      notifyToast(a);
      await notifyNative(a);
    } catch (e) {
      // no-op
    }
  }

  /* -------------------- INIT -------------------- */
  window.addEventListener("load", () => {
    initPush();          // 🔔 PUSH REAL
    setTimeout(poll, 2500);
    setInterval(poll, POLL_MS);
  });
})();
