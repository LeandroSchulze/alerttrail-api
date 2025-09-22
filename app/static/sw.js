// static/sw.js
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : { title: 'AlertTrail', body: 'Alerta recibida', url: '/dashboard' };
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/favicon.ico',
      data: data.url || '/dashboard'
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data || '/dashboard'));
});
