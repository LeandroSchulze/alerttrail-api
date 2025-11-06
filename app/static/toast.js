// Toasts – AlertTrail (sin dependencias)
(function () {
  const rootId = "toasts";
  function ensureRoot() {
    let r = document.getElementById(rootId);
    if (!r) {
      r = document.createElement("div");
      r.id = rootId;
      document.body.appendChild(r);
    }
    return r;
  }
  function makeToast(kind, title, message, ms = 6000) {
    const r = ensureRoot();
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.innerHTML = `
      <div class="title">${title || kind.toUpperCase()}</div>
      <div class="msg">${message || ""}</div>
      <button aria-label="Cerrar">✕</button>
    `;
    const btn = el.querySelector("button");
    const close = () => {
      el.style.animation = "toast-out .16s forwards";
      setTimeout(() => el.remove(), 160);
    };
    btn.addEventListener("click", close);
    r.appendChild(el);
    if (ms > 0) setTimeout(close, ms);
  }
  window.toaster = {
    success: (t, m, ms) => makeToast("ok", t, m, ms),
    warning: (t, m, ms) => makeToast("warn", t, m, ms),
    error:   (t, m, ms) => makeToast("err", t, m, ms),
    info:    (t, m, ms) => makeToast("info", t, m, ms),
  };
})();
