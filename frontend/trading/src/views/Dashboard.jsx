import { useEffect, useState } from 'react'
import { getHealth, getStatus, getBriefLatest, getConvictionSignals } from '../api.js'

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">{value ?? '—'}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

function DepBadge({ label, status }) {
  const ok = status === 'ok'
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-green-500' : 'bg-red-500'}`} />
      <span className="text-gray-400">{label}</span>
      <span className={`ml-auto text-xs ${ok ? 'text-green-400' : 'text-red-400'}`}>{status ?? 'unknown'}</span>
    </div>
  )
}

export default function Dashboard() {
  const [health, setHealth] = useState(null)
  const [status, setStatus] = useState(null)
  const [brief, setBrief] = useState(null)
  const [briefErr, setBriefErr] = useState(false)
  const [signals, setSignals] = useState([])

  useEffect(() => {
    const load = () => {
      getHealth().then(r => setHealth(r.data)).catch(() => {})
      getStatus().then(r => setStatus(r.data)).catch(() => {})
      getBriefLatest().then(r => setBrief(r.data)).catch(() => setBriefErr(true))
      getConvictionSignals(5).then(r => setSignals(r.data)).catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const deps = health?.dependencies || {}
  const mode = health?.trading_mode

  return (
    <div className="p-6 pb-20 md:pb-6 max-w-4xl">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-lg font-bold text-white">Dashboard</h1>
        {mode && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${
            mode === 'live' ? 'bg-blue-900 text-blue-300' : 'bg-amber-900 text-amber-300'
          }`}>
            {mode.toUpperCase()}
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <StatCard label="Open Positions" value={status?.open_positions} />
        <StatCard label="Signals Today" value={status?.signals_today} />
        <StatCard label="Pending Orders" value={status?.pending_orders} />
        <StatCard
          label="Last Brief"
          value={status?.last_morning_brief ?? '—'}
        />
      </div>

      {/* Dependencies */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 mb-6">
        <div className="text-xs text-gray-500 mb-3">Services</div>
        <div className="space-y-2">
          <DepBadge label="IBKR TWS" status={deps.ibkr_tws} />
          <DepBadge label="Coinbase" status={deps.coinbase} />
        </div>
      </div>

      {/* Recent conviction signals */}
      {signals.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 mb-6">
          <div className="text-xs text-gray-500 mb-3">Recent Conviction Signals</div>
          <div className="space-y-2">
            {signals.map(s => (
              <div key={s.id} className="flex items-center gap-3 text-sm">
                <span className={`font-bold w-16 ${s.direction === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                  {s.direction}
                </span>
                <span className="text-white font-medium">{s.ticker}</span>
                <span className="text-gray-500 text-xs">{s.pool}</span>
                <span className="ml-auto text-xs text-gray-400">
                  {s.conviction != null ? `${Math.round(s.conviction)}/100` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Morning brief */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-3">
          Morning Brief
          {brief?.brief_date && (
            <span className="ml-2 text-gray-600">{brief.brief_date}</span>
          )}
        </div>
        {briefErr || !brief ? (
          <div className="text-gray-600 text-sm">No brief generated yet</div>
        ) : (
          <pre className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">
            {brief.content}
          </pre>
        )}
      </div>
    </div>
  )
}
