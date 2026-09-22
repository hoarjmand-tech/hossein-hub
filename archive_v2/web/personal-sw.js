// No caching of private documents, email, audio or authenticated API responses.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>{
 let message={};try{message=event.data.json()}catch{}
 event.waitUntil(self.registration.showNotification(message.title||'همراه من',{
 body:message.body||'یک پیگیری منتظر توست.',tag:message.tag||'personal',
 icon:'/personal/icon-192.png',data:{url:'/personal'}
 }));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();event.waitUntil((async()=>{
 const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
 const client=windows.find(x=>new URL(x.url).pathname.startsWith('/personal'));
 if(client){await client.navigate('/personal');return client.focus()}
 return self.clients.openWindow('/personal');
 })());
});
