'use strict';
// Live updates without blocking the page: poll a small JSON endpoint and reload only when something changed.
const poller = document.querySelector('[data-poll]');
if (poller) {
  const active = s => ['new', 'drafting', 'queued', 'running', 'publishing'].includes(s);
  const check = async () => {
    try {
      const r = await fetch(poller.dataset.poll, {cache: 'no-store', headers: {Accept: 'application/json'}});
      if (r.ok) {
        const d = await r.json();
        const changed = d.status !== poller.dataset.status ||
          (poller.dataset.completed !== undefined && String(d.completed) !== poller.dataset.completed);
        // Never reload while someone is typing in a form on this page.
        const typing = document.activeElement && ['TEXTAREA', 'INPUT', 'SELECT'].includes(document.activeElement.tagName);
        if (changed && !typing) { location.reload(); return; }
        if (!active(d.status) && !changed) return;
      }
    } catch (e) { /* app restarting; try again */ }
    setTimeout(check, 2000);
  };
  if (active(poller.dataset.status)) setTimeout(check, 2000);
}
const reloader = document.querySelector('[data-reload]');
if (reloader) setTimeout(() => {
  const typing = document.activeElement && ['TEXTAREA', 'INPUT', 'SELECT'].includes(document.activeElement.tagName);
  if (!typing) location.reload();
}, Number(reloader.dataset.reload) * 1000);
for (const a of document.querySelectorAll('[data-back]')) a.addEventListener('click', e => { e.preventDefault(); history.back(); });
// Prevent double submits while a request is in flight.
for (const f of document.querySelectorAll('form[method=post]')) f.addEventListener('submit', () => {
  setTimeout(() => f.querySelectorAll('button').forEach(b => { b.disabled = true; }), 0);
});
