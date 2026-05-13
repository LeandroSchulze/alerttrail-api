/* app/sw.js */

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "AlertTrail", body: "Actividad sospechosa detectada" };
  }

  const title = data.title || "AlertTrail";
  const options = {
    body: data.body || "Nueva alerta de seguridad",
    
    // --- ACTUALIZADO: Usamos el nuevo icono SVG ---
    icon: "/static/icon.svg",
    badge: "/static/icon.svg",
    
    data: data.data || {},
    
    // --- TOQUES DE CALIDAD ---
    vibrate: [200, 100, 200, 100, 400], // Patrón de alerta
    tag: "security-alert",               // Agrupa notificaciones
    renotify: true,                      // Vibra siempre
    actions: [
      { action: 'view', title: 'Ver Detalle' },
      { action: 'close', title: 'Cerrar' }
    ]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  if (event.action === 'close') return;

  const url = (event.notification.data && event.notification.data.url) || "/dashboard";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(url) && "focus" in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
