import { useEffect, useState } from 'react'
import { getPositions, getPositionHistory } from '../api.js'

function pnlColor(val) {
  if (val == null) return 'text-gray-500'
  return parseFloat(val) >= 0 ? 'text-green-400' : 'text-red-400'
}

function fmt(val, decimals = 2) {
  if (val == null) return '—'
  return parseFloat(val).toFixed(decimals)
}

function fmtDate(dt) {
  if (!dt) return '—'
  return dt.slice(0, 16).replace('T', ' ')
}

function PositionRow({ p, closed }) {
  return (
    <tr className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
      <td className="px-3 py-2 font-medium text-white">{p.ticker}</td>
      <td className="px-3 py-2 text-gray-400 text-xs">{p.pool}</td>
      <td className="px-3 py-2 text-xs text-gray-400">{p.direction || 'LONG'}</td>
      <td className="px-3 py-2 text-right text-gray-300">{fmt(p.entry_price)}</td>
      {!closed && (
        <td className="px-3 py-2 text-right text-gray-300">{fmt(p.current_price)}</td>
      )}
      {closed && (
        <td className="px-3 py-2 text-right text-gray-300">{fmt(p.exit_price)}</td>
      )}
      <td className="px-3 py-2 text-right text-gray-300">{fmt(p.cost_basis)}</td>
      <td className={`px-3 py-2 text-right font-medium ${pnlColor(closed ? p.realised_pnl : p.unrealised_pnl)}`}>
        {fmt(closed ? p.realised_pnl : p.unrealised_pnl)}
      </td>
      <td className="px-3 py-2 text-right text-gray-500 text-xs">
        {closed ? fmtDate(p.closed_at) : fmtDate(p.opened_at)}
      </td>
    </tr>
  )
}

export default function Positions() {
  const [tab, setTab] = useState('open')
  const [open, setOpen] = useState([])
  const [history, setHistory] = useState([])
  const [pool, setPool] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const p = pool || undefined
    Promise.all([
      getPositions(p).then(r => setOpen(r.data)),
      getPositionHistory(100).then(r => setHistory(r.data)),
    ]).finally(() => setLoading(false))

    const id = setInterval(() => {
      getPositions(p).then(r => setOpen(r.data)).catch(() => {})
    }, 15000)
    return () => clearInterval(id)
  }, [pool])

  const rows = tab === 'open' ? open : history
  const filtered = pool ? rows.filter(r => r.pool === pool) : rows

  return (
    <div className="p-6 pb-20 md:pb-6">
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-lg font-bold text-white">Positions</h1>
        <div className="flex gap-1">
          {['open', 'history'].map(t => (
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
        <div className="ml-auto flex gap-1">
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
      </div>

      {loading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : filtered.length === 0 ? (
        <div className="text-gray-600 text-sm">No {tab} positions</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500">
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Pool</th>
                <th className="px-3 py-2">Dir</th>
                <th className="px-3 py-2 text-right">Entry</th>
                <th className="px-3 py-2 text-right">{tab === 'open' ? 'Current' : 'Exit'}</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">{tab === 'open' ? 'Opened' : 'Closed'}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => (
                <PositionRow key={p.id} p={p} closed={tab === 'history'} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
