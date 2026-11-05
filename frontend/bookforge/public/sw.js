// Bookforge service worker: shows the push notifications the service sends when a run needs you or fails.
self.addEventListener('push', (e) => {
  const data = e.data ? e.data.json() : {}
  e.waitUntil(
    self.registration.showNotification(data.title || 'Bookforge', {
      body: data.body || '',
      data: { url: data.url || '/bookforge/' },
    }),
  )
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const url = (e.notification.data && e.notification.data.url) || '/bookforge/'
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const open = list.find((w) => w.url.includes('/bookforge/'))
      if (open) { open.navigate(url); return open.focus() }
      return clients.openWindow(url)
    }),
  )
})
