// app/static/js/billing.js

(async function () {
  const planBadge = document.getElementById("plan-badge");
  const expiryText = document.getElementById("expiry-text");
  const tbody = document.getElementById("history-body");

  const btnMonthly = document.getElementById("btn-pro-monthly");
  const btnYearly = document.getElementById("btn-pro-yearly");
  const btnTrial = document.getElementById("btn-trial");
  const btnRefresh = document.getElementById("btn-refresh");

  function money(amount_cents, currency) {
    const v = (amount_cents || 0) / 100.0;
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(v);
    } catch {
      return `${v.toFixed(2)} ${currency || "USD"}`;
    }
  }

  function fmtDate(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return d.toLocaleString();
  }

  async function loadStatus() {
    try {
      const r = await fetch("/billing/me", { credentials: "include" });
      const j = await r.json();
      if (!j.ok) throw new Error("status not ok");

      const isPro = !!j.is_pro;
      const plan = (j.plan || "FREE").toUpperCase();
      planBadge.textContent = isPro ? `PRO` : plan;

      planBadge.className =
        "inline-flex items-center rounded-full px-3 py-1 text-sm font-medium " +
        (isPro
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"
          : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200");

      if (j.pro_expires_at) {
        expiryText.textContent = `• Activo hasta ${fmtDate(j.pro_expires_at)} (${j.remaining_days}d ${j.remaining_hours}h)`;
      } else {
        expiryText.textContent = isPro ? "" : "• Sin PRO activo";
      }
    } catch (e) {
      planBadge.textContent = "Error";
      expiryText.textContent = "";
      console.error(e);
    }
  }

  async function loadHistory() {
    try {
      const r = await fetch("/billing/history?limit=100", { credentials: "include" });
      const j = await r.json();
      if (!j.ok) throw new Error("history not ok");
      const items = j.items || [];
      tbody.innerHTML = "";

      if (items.length === 0) {
        tbody.innerHTML = `<tr><td class="py-3 text-gray-500 dark:text-gray-400" colspan="6">No hay pagos registrados.</td></tr>`;
        return;
      }

      for (const it of items) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="py-2 pr-4 whitespace-nowrap">${fmtDate(it.created_at)}</td>
          <td class="py-2 pr-4">${it.description || "-"}</td>
          <td class="py-2 pr-4">${money(it.amount_cents, it.currency)}</td>
          <td class="py-2 pr-4">${(it.status || "").toUpperCase()}</td>
          <td class="py-2 pr-4">${fmtDate(it.expires_at)}</td>
          <td class="py-2 pr-4">${it.origin || "-"}</td>
        `;
        tbody.appendChild(tr);
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td class="py-3 text-red-600" colspan="6">Error al cargar historial.</td></tr>`;
      console.error(e);
    }
  }

  async function startCheckout(period) {
    try {
      const url = `/payments/checkout?plan=pro&period=${encodeURIComponent(period)}`;
      const r = await fetch(url, { credentials: "include" });
      const j = await r.json();

      // Trial activa directo
      if (period === "trial" && j.ok && j.trial_activated) {
        await loadStatus();
        await loadHistory();
        alert("Trial PRO activado. ¡Disfruta 5 días!");
        return;
      }

      const init = j.init_point;
      if (j.ok && init) {
        window.location.href = init;
      } else {
        alert("No se pudo iniciar el checkout.");
      }
    } catch (e) {
      console.error(e);
      alert("Error iniciando checkout.");
    }
  }

  btnMonthly?.addEventListener("click", () => startCheckout("monthly"));
  btnYearly?.addEventListener("click", () => startCheckout("yearly"));
  btnTrial?.addEventListener("click", () => startCheckout("trial"));
  btnRefresh?.addEventListener("click", async () => { await loadStatus(); await loadHistory(); });

  await loadStatus();
  await loadHistory();
})();
