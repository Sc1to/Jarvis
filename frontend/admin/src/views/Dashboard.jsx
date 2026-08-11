import { useEffect, useState } from 'react'
import { getStats, getHealthCheck, getPlatformEvents } from '../api.js'

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-semibold text-white">{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

function StatusDot({ status }) {
  const color = status === 'ok' ? 'bg-green-500' : status === 'degraded' ? 'bg-yellow-500' : 'bg-red-500'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}

const EVENT_COLORS = {
  service_down: 'text-red-400',
  restart_failed: 'text-red-400',
  service_recovered: 'text-green-400',
  update_applied: 'text-blue-400',
  updates_available: 'text-yellow-400',
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [services, setServices] = useState([])
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)

  async function load() {
    try {
      const [s, h, e] = await Promise.all([getStats(), getHealthCheck(), getPlatformEvents(15)])
      setStats(s.data)
      setServices(h.data)
      setEvents(e.data)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  }, [])

  const downServices = services.filter((s) => s.health?.status !== 'ok' && s.health?.status !== 'degraded')

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Dashboard</h1>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {downServices.length > 0 && (
        <div className="bg-red-950 border border-red-700 rounded-lg px-4 py-3 flex items-start gap-3">
          <span className="text-red-400 mt-0.5">⚠</span>
          <div>
            <p className="text-sm font-medium text-red-300">
              {downServices.length} service{downServices.length > 1 ? 's' : ''} down
            </p>
            <p className="text-xs text-red-400 mt-0.5">
              {downServices.map((s) => s.name).join(', ')}
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="CPU" value={stats ? `${stats.cpu_percent}%` : null} />
        <StatCard
          label="Memory"
          value={stats ? `${stats.memory_percent}%` : null}
          sub={stats ? `${stats.memory_used_gb} / ${stats.memory_total_gb} GB` : null}
        />
        {stats?.gpu && (
          <StatCard
            label="GPU VRAM"
            value={`${stats.gpu.vram_used_gb} / ${stats.gpu.vram_total_gb} GB`}
            sub="used / total"
          />
        )}
        {stats?.temperature_c && Object.entries(stats.temperature_c).slice(0, 1).map(([k, entries]) => (
          <StatCard key={k} label="Temp" value={`${entries[0]?.current ?? '?'}°C`} sub={k} />
        ))}
      </div>

      <div>
        <h2 className="text-sm font-medium text-gray-400 mb-2">Services</h2>
        {services.length === 0 ? (
          <p className="text-gray-500 text-sm">No apps registered yet.</p>
        ) : (
          <div className="space-y-2">
            {services.map((svc) => (
              <div key={svc.id} className="bg-gray-800 rounded-lg px-4 py-3 border border-gray-700 flex items-center gap-3">
                <StatusDot status={svc.health?.status ?? 'down'} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium">{svc.name}</span>
                  <span className="text-xs text-gray-500 ml-2">{svc.route}</span>
                </div>
                <span className="text-xs text-gray-500">:{svc.backend_port}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {events.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-gray-400 mb-2">Platform Events</h2>
          <div className="bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700 max-h-64 overflow-y-auto">
            {events.map((ev) => (
              <div key={ev.id} className="px-4 py-2.5 flex items-start gap-3">
                <span className={`text-xs font-mono mt-0.5 ${EVENT_COLORS[ev.event_type] ?? 'text-gray-400'}`}>
                  {ev.event_type}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300">{ev.message}</p>
                  <p className="text-xs text-gray-600 mt-0.5">{ev.service} · {ev.timestamp}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
