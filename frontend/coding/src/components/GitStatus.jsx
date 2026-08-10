import { useState } from 'react'
import { pushProject, createPR } from '../api.js'

export default function GitStatus({ projectId, status, onRefresh }) {
  const [pushing, setPushing] = useState(false)
  const [prOpen, setPrOpen] = useState(false)
  const [pr, setPr] = useState({ title: '', body: '', head_branch: '', base_branch: 'main' })
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)

  async function push() {
    setPushing(true); setError(null); setMsg(null)
    try {
      await pushProject(projectId, { remote: 'origin', branch: status?.branch ?? 'main' })
      setMsg('Pushed')
      onRefresh()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
    finally { setPushing(false) }
  }

  async function submitPR(e) {
    e.preventDefault(); setError(null)
    try {
      const r = await createPR(projectId, pr)
      setMsg(`PR created: ${r.data.url}`)
      setPrOpen(false)
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
  }

  if (!status) return <p className="text-xs text-gray-500">No project selected</p>

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-gray-400">Branch: <span className="text-blue-400 font-mono">{status.branch}</span></span>
        <button onClick={onRefresh} className="text-gray-500 hover:text-white">↻</button>
      </div>

      {error && <p className="text-red-400">{error}</p>}
      {msg && <p className="text-green-400 break-all">{msg}</p>}

      {status.staged.length > 0 && (
        <div>
          <p className="text-gray-500 mb-1">Staged</p>
          {status.staged.map((f, i) => <p key={i} className="text-green-400 font-mono truncate">+ {f}</p>)}
        </div>
      )}

      {status.unstaged.length > 0 && (
        <div>
          <p className="text-gray-500 mb-1">Unstaged</p>
          {status.unstaged.map((f, i) => <p key={i} className="text-red-400 font-mono truncate">~ {f}</p>)}
        </div>
      )}

      {status.commits.length > 0 && (
        <div>
          <p className="text-gray-500 mb-1">Recent commits</p>
          {status.commits.slice(0, 5).map((c, i) => (
            <p key={i} className="text-gray-400 font-mono truncate">{c}</p>
          ))}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          onClick={push}
          disabled={pushing}
          className="flex-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white py-1.5 rounded text-xs"
        >
          {pushing ? 'Pushing…' : 'Push'}
        </button>
        <button
          onClick={() => setPrOpen(o => !o)}
          className="flex-1 bg-gray-700 hover:bg-gray-600 text-white py-1.5 rounded text-xs"
        >
          PR
        </button>
      </div>

      {prOpen && (
        <form onSubmit={submitPR} className="space-y-2 pt-1">
          <input
            className={inp}
            placeholder="Head branch"
            value={pr.head_branch}
            onChange={e => setPr(p => ({ ...p, head_branch: e.target.value }))}
            required
          />
          <input
            className={inp}
            placeholder="PR title"
            value={pr.title}
            onChange={e => setPr(p => ({ ...p, title: e.target.value }))}
            required
          />
          <textarea
            className={`${inp} resize-none`}
            rows={3}
            placeholder="Description (optional)"
            value={pr.body}
            onChange={e => setPr(p => ({ ...p, body: e.target.value }))}
          />
          <button type="submit" className="w-full bg-blue-700 hover:bg-blue-600 text-white py-1.5 rounded text-xs">
            Create PR
          </button>
        </form>
      )}
    </div>
  )
}

const inp = 'w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500'
