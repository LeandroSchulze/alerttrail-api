// static/sw.js
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch(e) {}

  const title = payload.title || 'AlertTrail';
  const body  = payload.body  || 'Nueva alerta de correo';
  const url   = payload.url   || '/mail/alerts';

  const options = {
    body,
    icon: '/static/favicon.ico',
    badge: '/static/favicon.ico',
    tag: 'alerttrail-alert',
    renotify: true,
    data: { url }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil((async () => {
    const clientsList = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clientsList) {
      if ('focus' in client) {
        await client.focus();
        try { await client.navigate(url); } catch (_) {}
        return;
      }
    }
    if (clients.openWindow) return clients.openWindow(url);
  })());
});

