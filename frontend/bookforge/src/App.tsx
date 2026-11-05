import { useEffect, useState } from 'react'
import { disablePush, enablePush, pushState, type PushState } from './lib/push'
import { useRoute } from './lib/route'
import Book from './pages/Book'
import SeriesList from './pages/SeriesList'

function PushToggle() {
  const [state, setState] = useState<PushState>('off')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { pushState().then(setState).catch(() => setState('unsupported')) }, [])
  if (state === 'unsupported') return null
  const toggle = async () => {
    setError(null)
    try { setState(state === 'on' ? await disablePush() : await enablePush()) } catch (e) { setError(String(e)) }
  }
  const label = state === 'on' ? 'Notifications on' : state === 'denied' ? 'Notifications blocked in the browser' : 'Notify me'
  return (
    <button onClick={toggle} disabled={state === 'denied'} title={error ?? label} aria-pressed={state === 'on'}
      className="min-h-10 rounded-md border border-slate-300 bg-white px-3 text-sm disabled:opacity-50">
      {state === 'on' ? '🔔 On' : state === 'denied' ? '🔕 Blocked' : '🔔 Notify me'}
    </button>
  )
}

export default function App() {
  const route = useRoute()
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-2 sm:px-4">
          <a href="#/" className="text-base font-semibold">Bookforge</a>
          <PushToggle />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-3 py-3 sm:px-4 sm:py-4">
        {route.series && route.book ? <Book key={`${route.series}/${route.book}`} route={route} /> : <SeriesList />}
      </main>
    </div>
  )
}
