import { useEffect, useState } from 'react'
import { getWsbPosts, getWsbTopMentions, getWsbCorrelation } from '../api.js'

function SpikeBar({ factor, maxFactor }) {
  const pct = maxFactor > 0 ? (factor / maxFactor) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 w-24">
        <div className="h-1.5 rounded-full bg-amber-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-10">{parseFloat(factor).toFixed(1)}x</span>
    </div>
  )
}

function DDPosts({ posts }) {
  const [expanded, setExpanded] = useState(null)

  if (posts.length === 0)
    return <div className="text-gray-600 text-sm">No DD posts</div>

  return (
    <div className="space-y-2">
      {posts.map(p => (
        <div
          key={p.id}
          className="bg-gray-900 border border-gray-800 rounded-lg p-3 cursor-pointer hover:border-gray-700 transition-colors"
          onClick={() => setExpanded(expanded === p.id ? null : p.id)}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <span className="font-bold text-white">{p.ticker}</span>
              <span className="text-gray-400 text-sm ml-2">{p.title || p.post_id}</span>
            </div>
            {p.quality_score != null && (
              <span className={`text-xs font-bold flex-shrink-0 ${
                p.quality_score >= 70 ? 'text-green-400' : p.quality_score >= 40 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {Math.round(p.quality_score)}/100
              </span>
            )}
          </div>
          {expanded === p.id && (
            <div className="mt-2 text-xs text-gray-400 space-y-1">
              {p.thesis_summary && <div>{p.thesis_summary}</div>}
              {p.catalyst_verified != null && (
                <div className={p.catalyst_verified ? 'text-green-400' : 'text-gray-500'}>
                  Catalyst {p.catalyst_verified ? 'verified' : 'unverified'}
                </div>
              )}
              {p.processed_at && <div className="text-gray-600">{p.processed_at.slice(0, 16)}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function TopMentions({ mentions }) {
  const maxFactor = mentions.reduce((m, r) => Math.max(m, parseFloat(r.peak_spike || 0)), 0)

  if (mentions.length === 0)
    return <div className="text-gray-600 text-sm">No mention spikes</div>

  return (
    <div className="space-y-2">
      {mentions.map(m => (
        <div key={m.ticker} className="flex items-center gap-3">
          <span className="font-bold text-white w-16">{m.ticker}</span>
          <SpikeBar factor={m.peak_spike || 0} maxFactor={maxFactor} />
          <span className="text-xs text-gray-500 w-12 text-right">{m.peak_count} mentions</span>
        </div>
      ))}
    </div>
  )
}

function Correlation({ signals }) {
  if (signals.length === 0)
    return <div className="text-gray-600 text-sm">No correlation signals</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500">
            <th className="px-3 py-2">Ticker</th>
            <th className="px-3 py-2">Pool</th>
            <th className="px-3 py-2">Conviction</th>
            <th className="px-3 py-2 text-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {signals.map(s => (
            <tr key={s.id} className="border-t border-gray-800">
              <td className="px-3 py-2 font-medium text-white">{s.ticker}</td>
              <td className="px-3 py-2 text-gray-500 text-xs">{s.pool}</td>
              <td className="px-3 py-2 text-xs text-gray-300">
                {s.conviction != null ? `${Math.round(s.conviction)}/100` : '—'}
              </td>
              <td className="px-3 py-2 text-right text-gray-500 text-xs">
                {s.timestamp ? s.timestamp.slice(0, 16).replace('T', ' ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function WSB() {
  const [tab, setTab] = useState('dd')
  const [hours, setHours] = useState(2)
  const [posts, setPosts] = useState([])
  const [mentions, setMentions] = useState([])
  const [correlation, setCorrelation] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getWsbPosts(50).then(r => setPosts(r.data)),
      getWsbTopMentions(hours, 30).then(r => setMentions(r.data)),
      getWsbCorrelation(30).then(r => setCorrelation(r.data)),
    ]).finally(() => setLoading(false))

    const id = setInterval(() => {
      getWsbTopMentions(hours, 30).then(r => setMentions(r.data)).catch(() => {})
      getWsbCorrelation(30).then(r => setCorrelation(r.data)).catch(() => {})
    }, 60000)
    return () => clearInterval(id)
  }, [hours])

  const content = { dd: <DDPosts posts={posts} />, mentions: <TopMentions mentions={mentions} />, correlation: <Correlation signals={correlation} /> }

  return (
    <div className="p-6 pb-20 md:pb-6">
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <h1 className="text-lg font-bold text-white">WSB</h1>
        <div className="flex gap-1">
          {[['dd', 'DD Posts'], ['mentions', 'Mentions'], ['correlation', 'Correlation']].map(([t, l]) => (
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
        {tab === 'mentions' && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs text-gray-500">Window:</span>
            {[2, 6, 24].map(h => (
              <button
                key={h}
                onClick={() => setHours(h)}
                className={`px-2 py-1 text-xs rounded ${
                  hours === h ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                {h}h
              </button>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : (
        content[tab]
      )}
    </div>
  )
}
