self.addEventListener('push', e => {
  const data = e.data?.json() ?? {}
  e.waitUntil(
    self.registration.showNotification(data.title ?? 'Jarvis Trading', {
      body: data.body ?? '',
      data: { url: data.url ?? '/trading/' },
    })
  )
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  const url = e.notification.data?.url ?? '/trading/'
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const match = list.find(w => w.url.includes('/trading/'))
      return match ? match.focus() : clients.openWindow(url)
    })
  )
})
