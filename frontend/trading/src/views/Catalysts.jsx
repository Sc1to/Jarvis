import { useEffect, useState } from 'react'
import { getCatalysts, addCatalyst, resolveCatalyst } from '../api.js'

const STATE_COLORS = {
  upcoming:           'bg-blue-900 text-blue-300',
  pre_catalyst:       'bg-amber-900 text-amber-300',
  post_catalyst:      'bg-gray-800 text-gray-400',
  resolved_positive:  'bg-green-900 text-green-300',
  resolved_negative:  'bg-red-900 text-red-300',
  neutral:            'bg-gray-800 text-gray-500',
}

function StateBadge({ state }) {
  const cls = STATE_COLORS[state] || 'bg-gray-800 text-gray-500'
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${cls}`}>
      {state?.replace(/_/g, ' ') ?? '—'}
    </span>
  )
}

function AddForm({ onAdd }) {
  const [form, setForm] = useState({ ticker: '', catalyst_type: '', description: '', event_date: '' })
  const [saving, setSaving] = useState(false)

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  const submit = async e => {
    e.preventDefault()
    if (!form.ticker || !form.event_date) return
    setSaving(true)
    try {
      await addCatalyst({ ...form, ticker: form.ticker.toUpperCase() })
      setForm({ ticker: '', catalyst_type: '', description: '', event_date: '' })
      onAdd()
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div className="text-xs text-gray-500 mb-3">Add Catalyst</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
        <input
          value={form.ticker}
          onChange={set('ticker')}
          placeholder="Ticker"
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <input
          value={form.catalyst_type}
          onChange={set('catalyst_type')}
          placeholder="Type (earnings, FDA...)"
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <input
          value={form.event_date}
          onChange={set('event_date')}
          type="date"
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-gray-500"
        />
        <input
          value={form.description}
          onChange={set('description')}
          placeholder="Description"
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
      </div>
      <button
        type="submit"
        disabled={saving || !form.ticker || !form.event_date}
        className="text-xs px-3 py-1 bg-gray-700 text-white rounded disabled:opacity-40 hover:bg-gray-600 transition-colors"
      >
        {saving ? 'Adding...' : 'Add'}
      </button>
    </form>
  )
}

export default function Catalysts() {
  const [catalysts, setCatalysts] = useState([])
  const [loading, setLoading] = useState(true)
  const [resolving, setResolving] = useState(null)

  const load = () =>
    getCatalysts().then(r => setCatalysts(r.data)).finally(() => setLoading(false))

  useEffect(() => {
    load()
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [])

  const resolve = async (id, outcome) => {
    setResolving(id)
    try {
      await resolveCatalyst(id, outcome)
      await load()
    } finally {
      setResolving(null)
    }
  }

  return (
    <div className="p-6 pb-20 md:pb-6">
      <h1 className="text-lg font-bold text-white mb-6">Catalysts</h1>

      <AddForm onAdd={load} />

      {loading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : catalysts.length === 0 ? (
        <div className="text-gray-600 text-sm">No upcoming catalysts</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500">
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Description</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Resolve</th>
              </tr>
            </thead>
            <tbody>
              {catalysts.map(c => (
                <tr key={c.id} className="border-t border-gray-800 hover:bg-gray-800/50 transition-colors">
                  <td className="px-3 py-2 font-bold text-white">{c.ticker}</td>
                  <td className="px-3 py-2 text-gray-400 text-xs">{c.catalyst_type}</td>
                  <td className="px-3 py-2 text-gray-300 text-xs">{c.event_date}</td>
                  <td className="px-3 py-2 text-gray-400 text-xs max-w-xs truncate">{c.description}</td>
                  <td className="px-3 py-2">
                    <StateBadge state={c.temporal_state} />
                  </td>
                  <td className="px-3 py-2">
                    {!c.temporal_state?.startsWith('resolved') && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => resolve(c.id, 'resolved_positive')}
                          disabled={resolving === c.id}
                          className="text-xs px-2 py-0.5 rounded bg-green-900 text-green-300 hover:bg-green-800 disabled:opacity-40 transition-colors"
                        >
                          +
                        </button>
                        <button
                          onClick={() => resolve(c.id, 'resolved_negative')}
                          disabled={resolving === c.id}
                          className="text-xs px-2 py-0.5 rounded bg-red-900 text-red-300 hover:bg-red-800 disabled:opacity-40 transition-colors"
                        >
                          -
                        </button>
                      </div>
                    )}
                    {c.temporal_state?.startsWith('resolved') && c.outcome_notes && (
                      <span className="text-xs text-gray-600 italic">{c.outcome_notes}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
