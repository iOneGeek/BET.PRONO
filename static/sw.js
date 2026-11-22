/* Œil du Trader en ligne — service worker : affiche les notifications (trades, PC hors ligne). Aucun cache. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {texte: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(d.titre || "Œil du Trader", {
    body: d.texte || "", tag: d.tag || undefined, renotify: !!d.tag,
    icon: "/static/icon-192.png", badge: "/static/icon-192.png", data: {url: "/"},
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(L => {
    for (const c of L) if ("focus" in c) return c.focus();
    return self.clients.openWindow("/");
  }));
});
