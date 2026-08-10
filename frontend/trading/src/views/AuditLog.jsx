import { useEffect, useState } from 'react'
import { getAuditHistory, getAuditLatest, getRiskGateLog, triggerAudit } from '../api.js'

function DecisionBadge({ decision }) {
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded ${
      decision === 'PASS' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
    }`}>
      {decision}
    </span>
  )
}

function ComplianceTab() {
  const [history, setHistory] = useState([])
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  const load = () =>
    getAuditHistory(20).then(r => setHistory(r.data)).finally(() => setLoading(false))

  useEffect(() => {
    load()
    const id = setInterval(load, 120000)
    return () => clearInterval(id)
  }, [])

  const run = async () => {
    setRunning(true)
    try {
      await triggerAudit()
      await load()
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-gray-500">Runs every 2 hours</span>
        <button
          onClick={run}
          disabled={running}
          className="text-xs px-3 py-1 bg-gray-700 text-white rounded hover:bg-gray-600 disabled:opacity-40 transition-colors"
        >
          {running ? 'Running...' : 'Run Now'}
        </button>
      </div>

      {loading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : history.length === 0 ? (
        <div className="text-gray-600 text-sm">No audits run yet</div>
      ) : (
        <div className="space-y-2">
          {history.map(a => (
            <div
              key={a.id}
              className="bg-gray-900 border border-gray-800 rounded-lg p-3 cursor-pointer hover:border-gray-700 transition-colors"
              onClick={() => setExpanded(expanded === a.id ? null : a.id)}
            >
              <div className="flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${a.violations_found > 0 ? 'bg-red-500' : 'bg-green-500'}`} />
                <span className="text-gray-400 text-xs">{a.run_at ? a.run_at.slice(0, 16).replace('T', ' ') : '—'}</span>
                <span className="text-gray-500 text-xs ml-2">{a.positions_checked} positions</span>
                {a.violations_found > 0 && (
                  <span className="text-red-400 text-xs font-bold ml-auto">{a.violations_found} violations</span>
                )}
                {a.force_exits_executed > 0 && (
                  <span className="text-red-300 text-xs">• {a.force_exits_executed} force-exits</span>
                )}
              </div>
              {expanded === a.id && a.findings && (
                <pre className="mt-2 text-xs text-gray-400 whitespace-pre-wrap">
                  {typeof a.findings === 'string' ? a.findings : JSON.stringify(JSON.parse(a.findings || '{}'), null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RiskGateTab() {
  const [log, setLog] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getRiskGateLog(100).then(r => setLog(r.data)).finally(() => setLoading(false))
    const id = setInterval(() => {
      getRiskGateLog(100).then(r => setLog(r.data)).catch(() => {})
    }, 30000)
    return () => clearInterval(id)
  }, [])

  if (loading) return <div className="text-gray-500 text-sm">Loading...</div>
  if (log.length === 0) return <div className="text-gray-600 text-sm">No risk gate entries</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500">
            <th className="px-3 py-2">Ticker</th>
            <th className="px-3 py-2">Pool</th>
            <th className="px-3 py-2">Decision</th>
            <th className="px-3 py-2">Rule</th>
            <th className="px-3 py-2 text-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {log.map(r => (
            <tr key={r.id} className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
              <td className="px-3 py-2 font-medium text-white">{r.ticker}</td>
              <td className="px-3 py-2 text-gray-500 text-xs">{r.pool}</td>
              <td className="px-3 py-2">
                <DecisionBadge decision={r.decision} />
              </td>
              <td className="px-3 py-2 text-xs text-gray-400">{r.rule_violated || '—'}</td>
              <td className="px-3 py-2 text-right text-gray-500 text-xs">
                {r.evaluated_at ? r.evaluated_at.slice(0, 16).replace('T', ' ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AuditLog() {
  const [tab, setTab] = useState('compliance')

  return (
    <div className="p-6 pb-20 md:pb-6">
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-lg font-bold text-white">Audit Log</h1>
        <div className="flex gap-1">
          {[['compliance', 'Compliance'], ['riskgate', 'Risk Gate']].map(([t, l]) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs rounded ${
                tab === t ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      {tab === 'compliance' ? <ComplianceTab /> : <RiskGateTab />}
    </div>
  )
}
