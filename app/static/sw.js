// static/sw.js
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
    data: { url }              // 👈 objeto, no string
    // vibrate: [100, 50, 100], // (opcional) vibración en móviles
    // requireInteraction: true // (opcional) queda visible hasta click
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
