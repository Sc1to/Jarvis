import { useEffect, useState } from 'react'

interface Status {
  service: string
  version: string
  milestone: string
}

// Placeholder for milestone 14.0: proves the route, proxy and API envelope work.
// The real dashboard arrives in milestone 14.11.
export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/bookforge/api/status')
      .then((r) => r.json())
      .then((body) => {
        if (body.status === 'ok') setStatus(body.data)
        else setError(body.detail ?? 'Unknown error')
      })
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <main className="mx-auto max-w-xl p-4 sm:p-8">
      <h1 className="text-2xl font-semibold">Bookforge</h1>
      <p className="mt-2 text-sm text-gray-600">Service shell. The pipeline is not built yet.</p>
      <div className="mt-6 rounded-lg border border-gray-200 p-4 text-sm">
        {error && <p className="text-red-600">Backend unreachable: {error}</p>}
        {!error && !status && <p>Checking backend…</p>}
        {status && (
          <p>
            {status.service} v{status.version}, milestone {status.milestone}
          </p>
        )}
      </div>
    </main>
  )
}
