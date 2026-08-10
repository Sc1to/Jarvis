import { useEffect, useState } from 'react'
import { getTailscale } from '../api.js'

export default function Network() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  async function load() {
    try {
      const r = await getTailscale()
      setStatus(r.data)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { load() }, [])

  const self = status?.Self
  const peers = Object.values(status?.Peer ?? {})

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Network</h1>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {status?.error && (
        <p className="text-yellow-400 text-sm">Tailscale unavailable: {status.error}</p>
      )}

      {self && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-2">
          <h2 className="text-sm font-medium text-gray-400">This device</h2>
          <p className="text-sm"><span className="text-gray-400">Name: </span>{self.HostName}</p>
          {self.TailscaleIPs?.map(ip => (
            <p key={ip} className="text-sm font-mono text-blue-300">{ip}</p>
          ))}
          <p className="text-sm"><span className="text-gray-400">OS: </span>{self.OS}</p>
        </div>
      )}

      {peers.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-gray-400 mb-2">Connected devices ({peers.length})</h2>
          <div className="space-y-2">
            {peers.map(p => (
              <div key={p.ID} className="bg-gray-800 rounded-lg px-4 py-3 border border-gray-700 flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full ${p.Online ? 'bg-green-500' : 'bg-gray-600'}`} />
                <div className="flex-1">
                  <p className="text-sm">{p.HostName}</p>
                  <p className="text-xs text-gray-500 font-mono">{p.TailscaleIPs?.[0]}</p>
                </div>
                <span className="text-xs text-gray-500">{p.OS}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <a
        href="https://login.tailscale.com/admin/machines"
        target="_blank"
        rel="noreferrer"
        className="inline-block text-sm text-blue-400 hover:text-blue-300"
      >
        Tailscale admin console →
      </a>
    </div>
  )
}
