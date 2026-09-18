const C="hossein-hub-v3";
self.addEventListener("install",e=>{self.skipWaiting();e.waitUntil(caches.keys().then(ks=>Promise.all(ks.map(k=>caches.delete(k)))))});
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{if(e.request.method!=="GET")return;if(e.request.url.includes("/api/"))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});
