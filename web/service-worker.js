// Retire legacy offline caches: private responses must never be cached.
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys())if(key.startsWith('crypto-ai-trader-'))await caches.delete(key);
  await self.clients.claim();
})()));
// No fetch handler: browser HTTP security and no-store apply normally.
