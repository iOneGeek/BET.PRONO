const CACHE = 'bet-prono-v2';
const SHELL = [
  '/login',
  '/app',
  '/static/app.js',
  '/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return; // network only, never cache user data

  // Stratégie "réseau d'abord" : on prend toujours la version la plus récente,
  // le cache n'est qu'un secours hors-ligne. Cela évite de servir d'anciennes
  // versions du site après un déploiement.
  event.respondWith(
    fetch(event.request)
      .then(resp => {
        if (resp.ok && !url.pathname.startsWith('/static/')) {
          caches.open(CACHE).then(cache => cache.put(event.request, resp.clone()));
        }
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});
