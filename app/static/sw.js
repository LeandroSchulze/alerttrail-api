// static/sw.js

// Toma control rápido del SW
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (e) {}

  const title = payload.title || 'AlertTrail';
  const body  = payload.body  || 'Nueva alerta de correo';
  const url   = payload.url   || '/mail/alerts';

  const options = {
    body,
    icon: '/static/favicon.ico',
    badge: '/static/favicon.ico',
    tag: 'alerttrail-alert',   // agrupa notificaciones repetidas
    renotify: true,            // vuelve a sonar/mostrar si llega otra igual
    data: { url },             // 👈 lleva el destino
    // requireInteraction: true // si querés que quede visible hasta click
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';

  // Abrir o enfocar y NAVEGAR al destino
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      // Si ya hay una ventana, la enfocamos y navegamos al URL del payload
      if ('focus' in client) {
        await client.focus();
        try { await client.navigate(url); } catch (_) {}
        return;
      }
    }
    // Si no hay ventanas, abrimos una nueva al destino
    if (clients.openWindow) {
      return clients.openWindow(url);
    }
  })());
});
