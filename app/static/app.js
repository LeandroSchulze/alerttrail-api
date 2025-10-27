// static/app.js
window.addEventListener("DOMContentLoaded", ()=>{
  if ("Notification" in window) Notification.requestPermission();
  const es = new EventSource("/mail/stream");
  es.addEventListener("mail_alert", (ev)=>{
    const d = JSON.parse(ev.data);
    new Notification("Correo sospechoso", {body:`${d.subject} · ${d.from}`});
  });
});
