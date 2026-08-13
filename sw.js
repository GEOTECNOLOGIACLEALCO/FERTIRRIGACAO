const CACHE_NAME = 'ferti-clealco-v35'; 
const TILE_CACHE = 'ferti-tiles-v1';

const ASSETS = [
  './', './index.html', './data.geojson', './talhoes.geojson', './perimetro.geojson', './tubulacao.geojson', './indicadores.json', './labels.json', './manifest.json',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(ASSETS)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.map((k) => { if (k !== CACHE_NAME && k !== TILE_CACHE) return caches.delete(k); })
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.hostname.includes('arcgisonline.com') || url.hostname.includes('maplibre.org')) {
    e.respondWith(
      caches.match(e.request).then((res) => {
        return res || fetch(e.request).catch(() => new Response(''));
      })
    );
  } else {
    e.respondWith(caches.match(e.request).then((res) => res || fetch(e.request)));
  }
});