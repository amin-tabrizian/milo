// Milo service worker: offline app shell + push notifications.
const CACHE = 'milo-v26';
const SHELL = ['/', '/style.css', '/app.js', '/manifest.webmanifest', '/mascot.js', '/reaction.js', '/vendor/three/three.module.min.js', '/mark.svg', '/mark-dark.svg', '/face.svg', '/face-dark.svg', '/icon-180.png', '/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname === '/ws') return;
  // Vendored libraries keep their path per version (bump CACHE when one changes): cache first, so three.js
  // (700 KB) is not downloaded on every launch.
  if (url.pathname.startsWith('/vendor/')) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return r;
    })));
    return;
  }
  // Network first, so updates on the Mac show up at once; cache when offline.
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request).then((r) => r || caches.match('/')))
  );
});

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: 'Milo', body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Milo', {
    body: d.body || '', tag: d.tag || undefined, data: { url: d.url || '/', chat: d.chat || null }, icon: '/icon-192.png', badge: '/icon-192.png',
  }));
});
// A tap opens the chat the alert is about. iOS may drop any one way of saying which, so the app hears it three ways
// and opens it once (by n): a note in the cache, read on start and each time the app comes back (iOS often starts
// the app, or brings it back, before this runs; or starts it on "/" and drops the link); a message to every open
// window (iOS reuses the window it has); and the #c= link of the window it brings back or opens.
// The app comes up first: focus() and openWindow() work only for a moment after the tap (WebKit: about 1-2 s), so
// they don't wait for the cache, which can be slow after a lock. A window that can't be focused (iOS may list a page
// it froze or dropped) is no reason to stay shut: the chat's link opens a window then.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL(e.notification.data && e.notification.data.url || '/', self.registration.scope);
  const d = e.notification.data || {};
  const chat = d.chat || new URLSearchParams(url.hash.slice(1)).get('c') || null;   // the push names it; else the link
  const tap = { type: 'open', chat, url: url.href, n: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, at: Date.now() };
  const keep = caches.open('milo-open').then((c) => c.put('/__open', new Response(JSON.stringify(tap), { headers: { 'content-type': 'application/json' } }))).catch(() => {});
  const isApp = (c) => { try { return new URL(c.url).pathname === new URL(self.registration.scope).pathname; } catch { return false; } };
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (list) => {
    for (const c of list) { try { c.postMessage(tap); } catch {} }
    const app = list.filter(isApp), pool = app.length ? app : list;   // the app's page, not a file opened in a window
    const best = pool.find((c) => c.focused) || pool.find((c) => c.visibilityState === 'visible') || pool[0];
    let shown = null, opened = false;
    if (best) { try { shown = (await best.focus()) || best; } catch {} }
    if (!shown) { try { shown = await self.clients.openWindow(url.href); opened = !!shown; } catch {} }
    // focus only brings the window back as it was (after a lock iOS may thaw it with no event the app hears): send it
    // to the chat's link too. Only the hash changes, so the app opens it on hashchange, or on start if iOS reloads.
    // navigate needs no tap, so it is tried even when focus and openWindow were refused.
    const win = shown || best;
    if (!opened && win && chat && win.navigate && !String(win.url || '').endsWith(`#c=${chat}`)) { try { await win.navigate(url.href); } catch {} }
    await keep;
  }).catch(() => keep));
});
