/* app/sw.js - Versión Mejorada */

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
    icon: data.icon || "/static/icon.png",
    badge: data.badge || "/static/icon.png",
    data: data.data || {},
    
    // --- TOQUES DE CALIDAD ---
    vibrate: [200, 100, 200, 100, 400], // Patrón de vibración de alerta
    tag: "security-alert",               // Agrupa notificaciones para no llenar la pantalla
    renotify: true,                      // Hace que el cel vibre aunque ya haya una notif previa
    actions: [
      { action: 'view', title: 'Ver Detalle' },
      { action: 'close', title: 'Cerrar' }
    ]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  // Si hizo clic en el botón 'close', no hacemos nada más
  if (event.action === 'close') return;

  const url = (event.notification.data && event.notification.data.url) || "/dashboard";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        // Mejoramos la búsqueda: si la URL coincide, enfocamos
        if (client.url.includes(url) && "focus" in client) return client.focus();
      }
      // Si no hay ninguna abierta, abrimos una nueva
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
