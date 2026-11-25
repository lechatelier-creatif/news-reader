const C='news-v14';
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','manifest.json','icon.png'])));self.skipWaiting()});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=='GET')return;
  if(u.origin===location.origin){
    // réseau d'abord, cache en secours (hors ligne)
    e.respondWith(fetch(e.request).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put(e.request.url.split('?')[0],cp));return r}).catch(()=>caches.match(e.request.url.split('?')[0])));
  }else if(e.request.destination==='image'){
    e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{const cp=r.clone();caches.open(C+'-img').then(c=>c.put(e.request,cp));return r})));
  }
});
