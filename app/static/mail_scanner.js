(function () {
  function $(id) { return document.getElementById(id); }

  function levelChip(level){
    if(level === 'high') return '<span class="chip red">HIGH</span>';
    if(level === 'medium') return '<span class="chip yellow">MEDIUM</span>';
    return '<span class="chip">LOW</span>';
  }

  function esc(s){
    return (s||'').toString().replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function renderItems(targetEl, items){
    if(!items || !items.length){
      targetEl.innerHTML = '<p class="muted">No se encontraron emails para mostrar.</p>';
      return;
    }
    const rows = items.map(it=>{
      const level = (it.analysis && it.analysis.danger_level) ? it.analysis.danger_level : 'low';
      const reasons = (it.analysis && Array.isArray(it.analysis.reasons)) ? it.analysis.reasons : [];
      const score = (typeof it.score === 'number') ? it.score : (it.analysis && typeof it.analysis.score === 'number' ? it.analysis.score : 0);
      const susp = (it.suspicious === true || level === 'medium' || level === 'high');
      const who = esc(it.from || it.from_email || '');
      const subj = esc(it.subject || '—');
      const snip = esc(it.snippet || '');
      const badges = reasons.slice(0,4).map(r=>`<span class="chip">${esc(r||'')}</span>`).join(' ');
      const link = it.link || (it.uid ? (`/mail/scanner?id=${encodeURIComponent(it.uid)}`) : '#');
      return `
        <tr>
          <td style="white-space:nowrap">${levelChip(level)}</td>
          <td>
            <div><a href="${link}" style="text-decoration:none;color:#0f172a;font-weight:700">${subj}</a></div>
            <div class="muted" style="font-size:12px">${who}</div>
            <div class="muted" style="font-size:12px">${(it.date||'').toString()}</div>
          </td>
          <td>
            <div class="${susp ? 'susp' : 'muted'}">score: <span class="score">${Number(score).toFixed(2)}</span></div>
            <div style="margin-top:6px">${badges || '<span class="muted">—</span>'}</div>
          </td>
          <td style="max-width:360px">${snip}</td>
        </tr>
      `;
    }).join('');

    targetEl.innerHTML = `
      <table class="tbl" aria-label="Resultados del escaneo">
        <thead>
          <tr>
            <th>Riesgo</th>
            <th>Email</th>
            <th>Análisis</th>
            <th>Snippet</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function init(){
    const form = $('scanForm');
    const summary = $('summary');
    const list = $('list');
    const raw = $('raw');
    if(!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (summary) summary.innerHTML = '<p class="muted">Conectando IMAP…</p>';
      if (list) list.innerHTML = '';
      if (raw) raw.innerHTML = '';
      try {
        const res = await fetch('/mail/scan', {method:'POST'});
        const data = await res.json();

        if (data.ok) {
          if (summary) {
            summary.innerHTML = `
              <div class="ok">
                <b>Conexión OK.</b><br>
                Carpeta: <b>${data.folder || '-'}</b> ·
                Emails totales: <b>${data.total ?? '-'}</b> ·
                No leídos: <b>${data.unread ?? '-'}</b> ·
                Marcados como leídos en esta corrida: <b>${data.marked_seen ? 'Sí' : 'No'}</b>
              </div>`;
          }
        } else {
          if (summary) summary.innerHTML = `<div class="bad"><b>Error:</b> ${data.message || 'falló la conexión'}</div>`;
        }

        if (list) renderItems(list, data.items || []);
        if (raw) raw.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
      } catch (err) {
        if (summary) summary.innerHTML = `<div class="bad"><b>Excepción:</b> ${String(err)}</div>`;
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
