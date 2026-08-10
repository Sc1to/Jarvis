import { useEffect, useState } from 'react'
import { getModels, getRunningModels, deleteModel, unloadModels, pullModel } from '../api.js'

function fmtSize(bytes) {
  if (!bytes) return '—'
  const gb = bytes / 1e9
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1e6).toFixed(0)} MB`
}

export default function Models() {
  const [models, setModels] = useState([])
  const [running, setRunning] = useState([])
  const [pullName, setPullName] = useState('')
  const [pullLog, setPullLog] = useState(null)
  const [pulling, setPulling] = useState(false)
  const [error, setError] = useState(null)

  async function load() {
    try {
      const [m, r] = await Promise.all([getModels(), getRunningModels()])
      setModels(m.data.models ?? [])
      setRunning(r.data.models ?? [])
    } catch (e) {
      setError('Ollama unavailable')
    }
  }

  useEffect(() => { load() }, [])

  async function remove(name) {
    if (!confirm(`Delete model ${name}?`)) return
    try { await deleteModel(name); load() } catch (e) { setError(e.message) }
  }

  async function unload() {
    try { await unloadModels(); load() } catch (e) { setError(e.message) }
  }

  async function pull(e) {
    e.preventDefault()
    if (!pullName.trim()) return
    setPulling(true)
    setPullLog('Starting...')
    setError(null)
    try {
      await pullModel(pullName.trim(), (evt) => {
        if (evt.status) setPullLog(`${evt.status}${evt.completed ? ` (${Math.round((evt.completed / evt.total) * 100)}%)` : ''}`)
      })
      setPullLog('Done')
      setPullName('')
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setPulling(false)
    }
  }

  const runningNames = new Set(running.map(m => m.name))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Models</h1>
        <button onClick={unload} className="text-xs text-yellow-400 hover:text-yellow-300">Unload all</button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <form onSubmit={pull} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-2">
        <h2 className="text-sm font-medium text-gray-400">Download model</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            placeholder="e.g. qwen2.5:14b"
            value={pullName}
            onChange={e => setPullName(e.target.value)}
            disabled={pulling}
          />
          <button type="submit" disabled={pulling} className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded">
            {pulling ? 'Pulling...' : 'Pull'}
          </button>
        </div>
        {pullLog && <p className="text-xs text-gray-400">{pullLog}</p>}
      </form>

      <div className="space-y-2">
        {models.length === 0 && <p className="text-gray-500 text-sm">No models downloaded.</p>}
        {models.map(m => (
          <div key={m.name} className="bg-gray-800 rounded-lg px-4 py-3 border border-gray-700 flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate">{m.name}</span>
                {runningNames.has(m.name) && (
                  <span className="text-xs bg-blue-900 text-blue-300 px-1.5 py-0.5 rounded">loaded</span>
                )}
              </div>
              <span className="text-xs text-gray-500">{fmtSize(m.size)}</span>
            </div>
            <button onClick={() => remove(m.name)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
          </div>
        ))}
      </div>
    </div>
  )
}
