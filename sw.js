const CACHE_NAME = 'home-v36-summer-clean';
const ASSETS = [
  '/',
  '/index.html',
  '/static/summer-green-background.png',
  '/static/theme.js?v=42',
  '/static/manifest.json',
  'https://unpkg.com/lucide@latest/dist/umd/lucide.min.js'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/') || e.request.url.includes('/data/') || e.request.url.includes('console.html')) return;
  const isPage = e.request.mode === 'navigate' || e.request.url.endsWith('.html');
  if (isPage) {
    // 页面走网络优先：改版立刻可见，断网才用缓存兜底
    e.respondWith(
      fetch(e.request).then(resp => {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  e.respondWith(
    fetch(e.request).then(resp => {
      const clone = resp.clone();
      caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
      return resp;
    }).catch(() => caches.match(e.request))
  );
});
