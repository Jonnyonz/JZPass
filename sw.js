// Service worker de JZ PASS: deja instalable la app y guarda el cascaron (la pagina, el icono y el manifest)
// para que abra sin red. Las llamadas a /api nunca se guardan: el fichaje exige conexion y, si no hay, la
// pagina avisa el error. __VERSION__ lo reemplaza main.py con database.VERSION, asi cada version publicada
// renueva la cache.
const CACHE = 'jzpass-__VERSION__';
const SHELL = ['/', '/icono.svg', '/manifest.webmanifest'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
    // Red primero (para recibir la version nueva); si no hay red, lo guardado.
    e.respondWith(fetch(e.request).then(r => {
        if (r.ok) caches.open(CACHE).then(c => c.put(e.request, r.clone()));
        return r;
    }).catch(() => caches.match(e.request, {ignoreSearch: true}).then(r => r || caches.match('/'))));
});
