import { useEffect, useState } from 'react'
import { getSignals, getConvictionSignals } from '../api.js'

function ConvictionBar({ score }) {
  if (score == null) return null
  const pct = Math.min(100, Math.max(0, score))
  const color = pct >= 70 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 w-16">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-8">{Math.round(pct)}</span>
    </div>
  )
}

function SignalRow({ s, expanded, onToggle }) {
  return (
    <>
      <tr
        className="border-t border-gray-800 hover:bg-gray-800/50 cursor-pointer transition-colors"
        onClick={onToggle}
      >
        <td className="px-3 py-2 font-medium text-white">{s.ticker}</td>
        <td className="px-3 py-2 text-gray-500 text-xs">{s.pool}</td>
        <td className="px-3 py-2 text-xs text-gray-400">{s.signal_type}</td>
        <td className="px-3 py-2">
          <span className={`text-xs font-bold ${s.direction === 'BUY' ? 'text-green-400' : s.direction === 'SELL' ? 'text-red-400' : 'text-gray-400'}`}>
            {s.direction || '—'}
          </span>
        </td>
        <td className="px-3 py-2">
          <ConvictionBar score={s.conviction ?? s.strength} />
        </td>
        <td className="px-3 py-2 text-right text-gray-500 text-xs">
          {s.timestamp ? s.timestamp.slice(0, 16).replace('T', ' ') : '—'}
        </td>
      </tr>
      {expanded && s.rationale && (
        <tr className="border-t border-gray-800 bg-gray-900/50">
          <td colSpan={6} className="px-3 py-2 text-xs text-gray-400 italic">
            {s.rationale}
          </td>
        </tr>
      )}
    </>
  )
}

export default function Signals() {
  const [tab, setTab] = useState('all')
  const [pool, setPool] = useState('')
  const [signals, setSignals] = useState([])
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const p = pool || undefined
    const fetch = tab === 'conviction'
      ? getConvictionSignals(100, p)
      : getSignals(100, p)
    fetch
      .then(r => setSignals(r.data))
      .finally(() => setLoading(false))

    const id = setInterval(() => {
      const f = tab === 'conviction' ? getConvictionSignals(100, p) : getSignals(100, p)
      f.then(r => setSignals(r.data)).catch(() => {})
    }, 30000)
    return () => clearInterval(id)
  }, [tab, pool])

  return (
    <div className="p-6 pb-20 md:pb-6">
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <h1 className="text-lg font-bold text-white">Signals</h1>
        <div className="flex gap-1">
          {['all', 'conviction'].map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs rounded ${
                tab === t ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {['', 'stocks', 'crypto'].map(p => (
            <button
              key={p}
              onClick={() => setPool(p)}
              className={`px-3 py-1 text-xs rounded ${
                pool === p ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {p || 'All'}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-gray-600">{signals.length} signals</span>
      </div>

      {loading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : signals.length === 0 ? (
        <div className="text-gray-600 text-sm">No signals</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500">
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Pool</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Dir</th>
                <th className="px-3 py-2">Score</th>
                <th className="px-3 py-2 text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              {signals.map(s => (
                <SignalRow
                  key={s.id}
                  s={s}
                  expanded={expanded === s.id}
                  onToggle={() => setExpanded(expanded === s.id ? null : s.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
