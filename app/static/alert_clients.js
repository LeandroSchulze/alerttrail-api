// Polling de alertas – AlertTrail
(function () {
  const INTERVAL_MS = 30000; // 30s
  let lastId = null;

  async function check() {
    try {
      const res = await fetch("/alerts/pending", { credentials: "include" });
      if (!res.ok) return;
      const data = await res.json();
      // Estructura esperada: { ok: true, pending: bool, alert: {id, title, message, level} }
      if (data && data.pending && data.alert) {
        if (data.alert.id && data.alert.id === lastId) return; // evitar repetidos
        lastId = data.alert.id || Date.now();

        const lvl = (data.alert.level || "").toLowerCase();
        const title = data.alert.title || "Alerta";
        const msg = data.alert.message || "Hay una alerta pendiente.";

        if (lvl === "high" || lvl === "error") toaster.error(title, msg);
        else if (lvl === "medium" || lvl === "warn") toaster.warning(title, msg);
        else toaster.info(title, msg);
      }
    } catch (e) {
      // en silencio para no molestar al usuario
    }
  }

  // primer chequeo rápido y luego cada INTERVAL_MS
  window.addEventListener("load", () => {
    check();
    setInterval(check, INTERVAL_MS);
  });
})();
