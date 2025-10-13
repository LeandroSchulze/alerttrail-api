(function(){
  const box = document.getElementById("promo-pro-trial");
  if (!box) return;

  const orgId = (box.getAttribute("data-org-id") || "").trim();
  const isOrg = !!orgId && orgId !== "0";

  const btn = document.getElementById("promo-pro-btn");
  const msg = document.getElementById("promo-pro-msg");
  const timerWrap = document.getElementById("promo-pro-timer");
  const countdownEl = document.getElementById("promo-pro-countdown");
  const errEl = document.getElementById("promo-pro-error");
  const subscribeLink = document.getElementById("promo-pro-subscribe");

  // Mostrar/ocultar banner solo para particulares
  if (isOrg) {
    box.style.display = "none";
    return;
  }

  async function getStatus() {
    try {
      const r = await fetch("/promo/status", { credentials: "include" });
      if (!r.ok) throw new Error("status " + r.status);
      return await r.json();
    } catch(e) {
      console.warn("[promo] status error:", e);
      return null;
    }
  }

  function fmt(ms) {
    if (ms <= 0) return "0s";
    const s = Math.floor(ms/1000);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400)/3600);
    const m = Math.floor((s % 3600)/60);
    const sec = s % 60;
    const parts = [];
    if (d) parts.push(d + "d");
    if (h) parts.push(h + "h");
    if (m) parts.push(m + "m");
    parts.push(sec + "s");
    return parts.join(" ");
  }

  let countdownInt = null;
  function startCountdown(seconds) {
    if (countdownInt) clearInterval(countdownInt);
    let remaining = seconds * 1000;
    timerWrap.style.display = "block";
    countdownEl.textContent = fmt(remaining);
    countdownInt = setInterval(() => {
      remaining -= 1000;
      if (remaining <= 0) {
        countdownEl.textContent = "0s";
        clearInterval(countdownInt);
        // Trial vencido: mostrar CTA a suscripción
        msg.textContent = "Tu prueba gratuita terminó.";
        btn.style.display = "none";
        subscribeLink.style.display = "inline-block";
        return;
      }
      countdownEl.textContent = fmt(remaining);
    }, 1000);
  }

  async function refreshUI() {
    const s = await getStatus();
    // Si no hay sesión, oculto banner
    if (!s) { box.style.display = "none"; return; }

    // Mostrar el contenedor
    box.style.display = "block";
    errEl.style.display = "none";

    if (s.effective_pro && s.pro_source !== "trial") {
      // PRO pago: ocultar banner completamente
      box.style.display = "none";
      return;
    }

    if (s.active) {
      msg.textContent = "Prueba activa. Disfrutá PRO sin cargo.";
      btn.style.display = "none";
      subscribeLink.style.display = "none";
      startCountdown(s.remaining_seconds || 0);
    } else {
      // No activa: si ya tuvo trial, ofrecemos suscripción
      if (s.had_trial) {
        msg.textContent = "Ya usaste tu prueba gratis.";
        btn.style.display = "none";
        subscribeLink.style.display = "inline-block";
        timerWrap.style.display = "none";
      } else {
        // elegible para iniciar trial
        msg.textContent = "Activalo ahora y probá todas las funciones PRO sin tarjeta.";
        btn.style.display = "inline-block";
        subscribeLink.style.display = "none";
        timerWrap.style.display = "none";
      }
    }
  }

  async function startTrial() {
    btn.disabled = true;
    btn.textContent = "Activando…";
    errEl.style.display = "none";
    try {
      const r = await fetch("/promo/start", {
        method: "POST",
        credentials: "include"
      });
      if (!r.ok) {
        const err = await r.json().catch(()=>({detail:"Error"}));
        throw new Error(err.detail || ("status " + r.status));
      }
      // activado: recargar UI
      btn.textContent = "Activado";
      await refreshUI();
    } catch(e) {
      errEl.textContent = "No se pudo activar la prueba: " + e.message;
      errEl.style.display = "block";
      btn.textContent = "Activar prueba";
      btn.disabled = false;
    }
  }

  btn && btn.addEventListener("click", startTrial);

  // primera carga
  refreshUI();
})();
