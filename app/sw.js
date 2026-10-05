// عامل الخدمة: أبسط ما يمكن، وكل خطوة محمية (في راصد ٢ كان ينهار مع كل إشعار).
const CACHE = "rasid-v2";
const SHELL = ["./", "index.html", "app.css", "app.js", "core.js", "config.js", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).catch(() => {}));
  self.clients.claim();
});
// كل ملفات التطبيق والنتائج: الشبكة أولاً (حتى تصل التحديثات دائماً)، وعند الانقطاع آخر نسخة محفوظة
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {}); }
    return r;
  }).catch(() => caches.match(e.request).then(hit => hit || caches.match("./"))));
});
// التنبيه الفوري: يعرض العنوان والنص، والضغط يفتح بطاقة الجهة نفسها
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: "راصد", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "راصد", {
    body: d.body || "", icon: "icon-192.png", badge: "icon-192.png", lang: "ar", dir: "rtl",
    data: { url: d.entity ? "./#e=" + encodeURIComponent(d.entity) : "./" },
  }).catch(() => {}));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) {
      if (c.url.startsWith(self.registration.scope)) { c.navigate(target).catch(() => {}); return c.focus(); }
    }
    return self.clients.openWindow(target);
  }).catch(() => self.clients.openWindow(target)));
});
