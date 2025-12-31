// app/static/alert_clients.js
// AlertTrail - Desktop popups + Toasts

(function () {
  const POLL_MS = Number(window.ALERT_POLL_MS || 10000);
  let lastId = null;
  let permissionAsked = false;

  function notifyToast(a) {
  try {
    if (!window.toaster) return false;

    const sev = String(a.severity || 'info').toLowerCase();
    const title = a.title || 'Alerta';
    const body = a.body || '';

    if (sev === 'high') {
      window.toaster.error(title, body);
      return true;
    }
    if (sev === 'medium' || sev === 'warn' || sev === 'warning') {
      window.toaster.warning(title, body);
      return true;
    }
    window.toaster.info(title, body);
    return true;
  } catch (e) {
    return false;
  }
}


  async function ensureNotificationPermission() {
    if (!('Notification' in window)) return 'unsupported';
    if (Notification.permission === 'granted') return 'granted';
    if (Notification.permission === 'denied') return 'denied';
    if (permissionAsked) return Notification.permission;

    permissionAsked = true;
    try {
      const p = await Notification.requestPermission();
      return p;
    } catch (e) {
      return Notification.permission;
    }
  }

  async function notifyNative(a) {
    try {
      const perm = await ensureNotificationPermission();
      if (perm !== 'granted') return false;

      const n = new Notification(a.title || 'Alerta', {
        body: a.body || '',
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

  async function poll() {
    try {
      const r = await fetch('/alerts/pending', { credentials: 'include' });
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

  setTimeout(poll, 2500);
  setInterval(poll, POLL_MS);
})();
