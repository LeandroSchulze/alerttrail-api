// static/dashboard_mail_widget.js
(function () {
  const el = document.getElementById("mailWidget");
  if (!el) return;

  function fmtTS(ts) {
    try {
      const d = new Date((ts || 0) * 1000);
      if (isNaN(d.getTime())) return "—";
      return d.toLocaleString();
    } catch { return "—"; }
  }

  function levelChip(lbl){
    if(lbl === 'high')   return '<span class="chip red">HIGH</span>';
    if(lbl === 'medium') return '<span class="chip yellow">MEDIUM</span>';
    return '<span class="chip">LOW</span>';
  }

  function render(data) {
    if (!data || data.ok === false) {
      el.innerHTML = `
        <div class="card">
          <h2 style="margin:0 0 8px">Mail Scanner</h2>
          <p class="muted" style="margin:0 0 8px">${(data && data.message) || 'Aún no hay escaneos cacheados.'}</p>
          <div class="row" style="margin-top:10px">
            <a href="/mail/scanner"><button class="btn">Ejecutar escaneo ahora</button></a>
          </div>
        </div>`;
      return;
    }

    const counts = data.counts || {low:0, medium:0, high:0};
    const dangerous = data.dangerous ?? (counts.medium + counts.high);
    const deto = data.detonation && data.detonation.results ? Object.keys(data.detonation.results).length : 0;

    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <h2 style="margin:0">Mail Scanner</h2>
          <a href="/mail/scanner"><button class="btn">Ver Scanner</button></a>
        </div>
        <p class="muted" style="margin:6px 0 12px">Carpeta: <b>${data.folder || '-'}</b> · No leídos: <b>${data.unread ?? '-'}</b> · Último: <b>${fmtTS(data.ts)}</b></p>

        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <div class="stat"><div class="statnum">${counts.high || 0}</div><div class="statlbl">Alto</div></div>
          <div class="stat"><div class="statnum">${counts.medium || 0}</div><div class="statlbl">Medio</div></div>
          <div class="stat"><div class="statnum">${counts.low || 0}</div><div class="statlbl">Bajo</div></div>
          <div class="stat"><div class="statnum">${dangerous || 0}</div><div class="statlbl">Sospechosos</div></div>
          <div class="stat"><div class="statnum">${deto}</div><div class="statlbl">URLs analizadas</div></div>
        </div>

        <details style="margin-top:12px">
          <summary>Ver últimos 5</summary>
          <div style="margin-top:8px">
            ${(data.items || []).slice(0,5).map(it=>{
              const level = (it.analysis && it.analysis.danger_level) ? it.analysis.danger_level : (it.suspicious ? 'medium':'low');
              const subj = (it.subject || '—').replace(/</g,'&lt;');
              const who  = (it.from || it.from_email || '—').replace(/</g,'&lt;');
              const hints = (it.analysis && it.analysis.hints) ? it.analysis.hints : null;
              const hintBadges = hints ? Object.keys(hints).filter(k=>hints[k]).map(k=>`<span class="chip">${k}</span>`).join(' ') : '';
              const linkDanger = (it.link_report && it.link_report.dangerous) ? ' <span class="chip red">URL SUSPECT</span>' : '';
              return `
                <div style="border-top:1px solid #e2e8f0;padding:8px 0">
                  ${levelChip(level)} <b>${subj}</b> <span class="muted">— ${who}</span>
                  ${hintBadges}${linkDanger}
                </div>`;
            }).join('')}
          </div>
        </details>
      </div>
    `;
  }

  function cssOnce(){
    if (document.getElementById("mailWidgetStyles")) return;
    const s = document.createElement('style');
    s.id = "mailWidgetStyles";
    s.textContent = `
      .card{border:1px solid #e2e8f0;border-radius:16px;padding:16px;background:#fff}
      .muted{color:#64748b}
      .btn{padding:8px 12px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;cursor:pointer}
      .btn:hover{box-shadow:0 0 0 3px #e2e8f0}
      .chip{display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #c7d2fe;background:#eef2ff;color:#1e3a8a;font-size:12px;font-weight:700;margin-left:6px}
      .chip.red{border-color:#fecaca;background:#fee2e2;color:#7f1d1d}
      .chip.yellow{border-color:#fde68a;background:#fef3c7;color:#7c2d12}
      .stat{min-width:100px;border:1px solid #e2e8f0;border-radius:12px;padding:8px}
      .statnum{font-size:20px;font-weight:800}
      .statlbl{font-size:12px;color:#475569}
    `;
    document.head.appendChild(s);
  }

  async function tick(){
    try {
      const r = await fetch('/mail/summary', {cache:'no-store'});
      const j = await r.json();
      render(j);
    } catch(e) {
      render({ok:false, message:'No se pudo cargar resumen'});
    }
  }

  cssOnce();
  tick();
  setInterval(tick, 30000); // 30s
})();
