import { useEffect, useState } from 'react'
import { getAppPrompts, updateAppPrompt } from '../api.js'

const APP_ORDER = ['chat', 'coding', 'writer', 'conductor', 'backend', 'frontend', 'db', 'tester', 'refactorer']

const APP_LABELS = {
  chat: 'Chat',
  coding: 'Coding Assistant',
  writer: 'Writer',
  conductor: 'Autocoder — Conductor',
  backend: 'Autocoder — Backend',
  frontend: 'Autocoder — Frontend',
  db: 'Autocoder — DB',
  tester: 'Autocoder — Tester',
  refactorer: 'Autocoder — Refactorer',
}

export default function Prompts() {
  const [prompts, setPrompts] = useState({})
  const [collapsed, setCollapsed] = useState(new Set())
  const [editing, setEditing] = useState(null) // { app, key, value }
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)

  async function load() {
    try {
      const r = await getAppPrompts()
      setPrompts(r.data)
    } catch (e) {
      setError('Failed to load prompts — are the app services running?')
    }
  }

  useEffect(() => { load() }, [])

  function toggle(app) {
    setCollapsed(c => { const n = new Set(c); n.has(app) ? n.delete(app) : n.add(app); return n })
  }

  function startEdit(app, key, value) {
    setEditing({ app, key, value })
    setMsg(null)
    setError(null)
  }

  function cancelEdit() { setEditing(null) }

  async function saveEdit() {
    if (!editing) return
    setSaving(true)
    setError(null)
    try {
      await updateAppPrompt(editing.app, editing.key, editing.value)
      setMsg(`Saved ${editing.key}`)
      setEditing(null)
      load()
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setSaving(false)
    }
  }

  const apps = APP_ORDER.filter(a => prompts[a] !== undefined)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">App Prompts</h1>
        <button onClick={load} className="text-xs text-gray-400 hover:text-white">Refresh</button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {msg && <p className="text-green-400 text-sm">{msg}</p>}

      {apps.length === 0 && !error && (
        <p className="text-gray-500 text-sm">No prompts loaded — services may be offline.</p>
      )}

      {apps.map(appKey => {
        const agentMap = prompts[appKey] ?? {}
        const agents = Object.entries(agentMap)
        return (
          <div key={appKey} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-4 py-2 bg-gray-800 hover:bg-gray-750 text-sm font-medium text-gray-300"
              onClick={() => toggle(appKey)}
            >
              <span>{APP_LABELS[appKey] ?? appKey}</span>
              <span className="text-gray-500 text-xs">{collapsed.has(appKey) ? '▶' : '▼'}</span>
            </button>

            {!collapsed.has(appKey) && (
              <div className="divide-y divide-gray-700">
                {agents.length === 0
                  ? <p className="px-4 py-3 text-xs text-gray-500">Service offline — no prompts available.</p>
                  : agents.map(([key, value]) => (
                    <div key={key} className="bg-gray-800 px-4 py-3">
                      {editing?.app === appKey && editing?.key === key ? (
                        <div className="space-y-2">
                          <p className="text-xs font-mono text-blue-400">{key}</p>
                          <textarea
                            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 min-h-[200px] resize-y font-mono"
                            value={editing.value}
                            onChange={e => setEditing(ed => ({ ...ed, value: e.target.value }))}
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={saveEdit}
                              disabled={saving}
                              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded"
                            >
                              {saving ? 'Saving…' : 'Save'}
                            </button>
                            <button onClick={cancelEdit} className="text-xs text-gray-400 hover:text-white px-3 py-1.5">
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-mono text-blue-400 mb-1">{key}</p>
                            <p className="text-xs text-gray-400 line-clamp-3 whitespace-pre-wrap break-words">
                              {value || <span className="italic text-gray-600">empty — no system prompt</span>}
                            </p>
                          </div>
                          <button
                            onClick={() => startEdit(appKey, key, value ?? '')}
                            className="text-xs text-gray-400 hover:text-white flex-shrink-0"
                          >
                            Edit
                          </button>
                        </div>
                      )}
                    </div>
                  ))
                }
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
