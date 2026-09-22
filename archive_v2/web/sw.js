const CACHE="hossein-archive-v4.6-personal-private";
const SHELL=["/","/manifest.webmanifest","/icon.svg","/font-persian-regular.ttf","/font-persian-bold.ttf"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()))});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=="GET"||u.origin!==location.origin)return;
  if(u.pathname.startsWith("/api/")||u.pathname.startsWith("/personal")||u.pathname.startsWith("/shared/")||u.pathname.startsWith("/s/")){
    e.respondWith(fetch(e.request));return;
  }
  e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(CACHE).then(x=>x.put(e.request,c));return r}).catch(()=>caches.match(e.request).then(r=>r||caches.match("/"))))
});
