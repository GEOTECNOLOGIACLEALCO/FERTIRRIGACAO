const CACHE_NAME = 'ferti-clealco-v4'; 
const TILE_CACHE = 'ferti-tiles-v1';

const ASSETS = [
  './', './index.html', './data.geojson', './manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap'
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
  // Se for imagem de mapa (Esri), tenta buscar do cache offline primeiro.
  if (url.hostname.includes('arcgisonline.com')) {
    e.respondWith(
      caches.match(e.request).then((res) => {
        return res || fetch(e.request).catch(() => new Response('')); // Retorna vazio se offline e sem cache
      })
    );
  } else {
    // Para o app e os dados, tenta Cache, depois rede.
    e.respondWith(caches.match(e.request).then((res) => res || fetch(e.request)));
  }
});