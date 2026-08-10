import { useEffect, useState } from 'react'
import { getAppAgents, createAgent, updateAgent, deleteAgent, getModels } from '../api.js'

const TOOLS = ['filesystem', 'terminal', 'git', 'github', 'web', 'test_runner', 'code_interpreter']
const EMPTY_AGENT = { name: '', description: '', model: '', tools: [], memory_scope: 'session', ui_type: 'none', ui_route: '', system_prompt: '', calls: [] }

function FlowDiagram({ agents }) {
  if (agents.length === 0) return null
  const byName = Object.fromEntries(agents.map(a => [a.name, a]))
  const allCalled = new Set(agents.flatMap(a => JSON.parse(a.calls || '[]')))
  const roots = agents.filter(a => !allCalled.has(a.name))
  const start = roots.length > 0 ? roots : [agents[0]]

  const levels = []
  const visited = new Set()
  let frontier = start
  while (frontier.length > 0) {
    levels.push(frontier)
    frontier.forEach(a => visited.add(a.name))
    const next = []
    frontier.forEach(a => {
      JSON.parse(a.calls || '[]').forEach(n => {
        if (byName[n] && !visited.has(n)) { visited.add(n); next.push(byName[n]) }
      })
    })
    frontier = next
  }
  // append any agents not reachable from roots (disconnected)
  const unseen = agents.filter(a => !visited.has(a.name))
  if (unseen.length > 0) levels.push(unseen)

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 overflow-x-auto">
      <p className="text-xs text-gray-400 mb-3 uppercase tracking-wide">Call flow</p>
      <div className="flex items-start gap-3">
        {levels.map((level, i) => (
          <div key={i} className="flex items-start gap-3">
            <div className="flex flex-col gap-2">
              {level.map(agent => (
                <div key={agent.id} className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-xs min-w-[130px]">
                  <div className="font-medium text-white truncate">{agent.name}</div>
                  <div className="text-gray-400 truncate mt-0.5">{agent.model || '—'}</div>
                </div>
              ))}
            </div>
            {i < levels.length - 1 && (
              <div className="self-center text-gray-500 text-base mt-1">→</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function AgentCard({ agent, models, onSaved, onDeleted }) {
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(toForm(agent))
  const [error, setError] = useState(null)

  function toForm(a) {
    return {
      name: a.name,
      description: a.description ?? '',
      model: a.model,
      tools: JSON.parse(a.tools || '[]'),
      memory_scope: a.memory_scope,
      ui_type: a.ui_type,
      ui_route: a.ui_route ?? '',
      system_prompt: a.system_prompt ?? '',
      calls: JSON.parse(a.calls || '[]'),
    }
  }

  function field(k, v) { setForm(f => ({ ...f, [k]: v })) }
  function toggleTool(t) {
    setForm(f => ({ ...f, tools: f.tools.includes(t) ? f.tools.filter(x => x !== t) : [...f.tools, t] }))
  }

  async function save() {
    setError(null)
    try {
      await updateAgent(agent.id, form)
      setEditing(false)
      onSaved()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
  }

  async function remove() {
    if (!confirm(`Delete agent "${agent.name}"?`)) return
    try { await deleteAgent(agent.id); onDeleted() } catch (e) { setError(e.message) }
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {editing ? (
            <input className={inp} value={form.name} onChange={e => field('name', e.target.value)} placeholder="Agent name" />
          ) : (
            <p className="font-medium text-sm">{agent.name}</p>
          )}
          {!editing && agent.description && <p className="text-xs text-gray-500 mt-0.5">{agent.description}</p>}
        </div>
        <div className="flex gap-2 flex-shrink-0">
          {editing ? (
            <>
              <button onClick={save} className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded">Save</button>
              <button onClick={() => { setEditing(false); setForm(toForm(agent)) }} className="text-xs text-gray-400 hover:text-white px-2 py-1">Cancel</button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="text-xs text-gray-400 hover:text-white">Edit</button>
              <button onClick={remove} className="text-xs text-red-400 hover:text-red-300">Delete</button>
            </>
          )}
        </div>
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}

      {editing && (
        <input className={inp} value={form.description} onChange={e => field('description', e.target.value)} placeholder="Description" />
      )}

      {/* Model */}
      <div>
        <label className="text-xs text-gray-400">Model</label>
        {editing ? (
          <select className={`${inp} mt-1`} value={form.model} onChange={e => field('model', e.target.value)}>
            <option value="">Select model…</option>
            {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
            <option value="qwen2.5:14b">qwen2.5:14b</option>
            <option value="qwen2.5-coder:32b">qwen2.5-coder:32b</option>
            <option value="qwen2.5:72b-instruct-q4_K_M">qwen2.5:72b-instruct-q4_K_M</option>
          </select>
        ) : (
          <p className="text-sm mt-0.5">{agent.model || <span className="text-gray-500">—</span>}</p>
        )}
      </div>

      {/* System prompt */}
      <div>
        <label className="text-xs text-gray-400">System prompt</label>
        {editing ? (
          <textarea
            className={`${inp} mt-1 min-h-[100px] resize-y`}
            value={form.system_prompt}
            onChange={e => field('system_prompt', e.target.value)}
            placeholder="You are a…"
          />
        ) : (
          <p className="text-xs text-gray-300 mt-0.5 whitespace-pre-wrap max-h-32 overflow-y-auto">
            {agent.system_prompt || <span className="text-gray-500">—</span>}
          </p>
        )}
      </div>

      {/* Calls */}
      <div>
        <label className="text-xs text-gray-400">Calls (agents this one invokes)</label>
        {editing ? (
          <input
            className={`${inp} mt-1`}
            value={form.calls.join(', ')}
            onChange={e => field('calls', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            placeholder="agent_name_1, agent_name_2"
          />
        ) : (
          <div className="flex flex-wrap gap-1 mt-1">
            {JSON.parse(agent.calls || '[]').length === 0
              ? <span className="text-xs text-gray-500">—</span>
              : JSON.parse(agent.calls || '[]').map(n => (
                  <span key={n} className="bg-gray-700 text-xs px-2 py-0.5 rounded text-blue-300">{n}</span>
                ))}
          </div>
        )}
      </div>

      {/* Tools */}
      <div>
        <label className="text-xs text-gray-400">Tools</label>
        {editing ? (
          <div className="flex flex-wrap gap-2 mt-1">
            {TOOLS.map(t => (
              <label key={t} className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.tools.includes(t)} onChange={() => toggleTool(t)} className="accent-blue-500" />
                <span className={form.tools.includes(t) ? 'text-white' : 'text-gray-400'}>{t}</span>
              </label>
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-1 mt-1">
            {JSON.parse(agent.tools || '[]').length === 0
              ? <span className="text-xs text-gray-500">—</span>
              : JSON.parse(agent.tools || '[]').map(t => (
                  <span key={t} className="bg-gray-700 text-xs px-2 py-0.5 rounded">{t}</span>
                ))}
          </div>
        )}
      </div>

      {/* Memory scope — only in edit mode */}
      {editing && (
        <div>
          <label className="text-xs text-gray-400">Memory scope</label>
          <select className={`${inp} mt-1`} value={form.memory_scope} onChange={e => field('memory_scope', e.target.value)}>
            <option value="session">session</option>
            <option value="project">project</option>
            <option value="global">global</option>
          </select>
        </div>
      )}
    </div>
  )
}

function AddAgentForm({ appId, models, onCreated }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ ...EMPTY_AGENT })
  const [error, setError] = useState(null)

  function field(k, v) { setForm(f => ({ ...f, [k]: v })) }
  function toggleTool(t) {
    setForm(f => ({ ...f, tools: f.tools.includes(t) ? f.tools.filter(x => x !== t) : [...f.tools, t] }))
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    try {
      await createAgent({ ...form, app_id: appId, calls: form.callsRaw?.split(',').map(s => s.trim()).filter(Boolean) ?? [] })
      setForm({ ...EMPTY_AGENT })
      setOpen(false)
      onCreated()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
  }

  if (!open) return (
    <button onClick={() => setOpen(true)} className="w-full border border-dashed border-gray-600 rounded-lg py-3 text-sm text-gray-400 hover:text-white hover:border-gray-400 transition-colors">
      + Add agent
    </button>
  )

  return (
    <form onSubmit={submit} className="bg-gray-800 border border-blue-600 rounded-lg p-4 space-y-3">
      <p className="text-sm font-medium text-blue-400">New agent</p>
      {error && <p className="text-red-400 text-xs">{error}</p>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input className={inp} placeholder="Name (e.g. platform_chat)" value={form.name} onChange={e => field('name', e.target.value)} required />
        <input className={inp} placeholder="Description" value={form.description} onChange={e => field('description', e.target.value)} />
        <select className={inp} value={form.model} onChange={e => field('model', e.target.value)} required>
          <option value="">Select model…</option>
          {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
          <option value="qwen2.5:14b">qwen2.5:14b</option>
          <option value="qwen2.5-coder:32b">qwen2.5-coder:32b</option>
          <option value="qwen2.5:72b-instruct-q4_K_M">qwen2.5:72b-instruct-q4_K_M</option>
        </select>
        <select className={inp} value={form.memory_scope} onChange={e => field('memory_scope', e.target.value)}>
          <option value="session">session</option>
          <option value="project">project</option>
          <option value="global">global</option>
        </select>
      </div>
      <input className={inp} placeholder="Calls: agent_a, agent_b" value={form.callsRaw ?? ''} onChange={e => field('callsRaw', e.target.value)} />
      <div>
        <p className="text-xs text-gray-400 mb-1">Tools</p>
        <div className="flex flex-wrap gap-2">
          {TOOLS.map(t => (
            <label key={t} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.tools.includes(t)} onChange={() => toggleTool(t)} className="accent-blue-500" />
              <span className={form.tools.includes(t) ? 'text-white' : 'text-gray-400'}>{t}</span>
            </label>
          ))}
        </div>
      </div>
      <textarea className={`${inp} min-h-[80px] resize-y`} placeholder="System prompt…" value={form.system_prompt} onChange={e => field('system_prompt', e.target.value)} />
      <div className="flex gap-2">
        <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded">Create</button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm text-gray-400 hover:text-white px-4 py-2">Cancel</button>
      </div>
    </form>
  )
}

export default function AppDetail({ app, onBack }) {
  const [agents, setAgents] = useState([])
  const [models, setModels] = useState([])
  const [error, setError] = useState(null)

  async function load() {
    try {
      const [a, m] = await Promise.all([
        getAppAgents(app.id),
        getModels().catch(() => ({ data: { models: [] } })),
      ])
      setAgents(a.data)
      setModels(m.data.models ?? [])
    } catch (e) { setError(e.message) }
  }

  useEffect(() => { load() }, [app.id])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-gray-400 hover:text-white text-sm">← Back</button>
        <div>
          <h1 className="text-lg font-semibold">{app.name}</h1>
          <p className="text-xs text-gray-500">{app.route} → :{app.backend_port}{app.description ? ` · ${app.description}` : ''}</p>
        </div>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* Flow diagram */}
      {agents.length > 0 && <FlowDiagram agents={agents} />}

      {/* Agent cards */}
      <div className="space-y-4">
        {agents.length === 0 && (
          <p className="text-gray-500 text-sm">No agents configured for this app yet.</p>
        )}
        {agents.map(agent => (
          <AgentCard key={agent.id} agent={agent} models={models} onSaved={load} onDeleted={load} />
        ))}
      </div>

      <AddAgentForm appId={app.id} models={models} onCreated={load} />
    </div>
  )
}

const inp = 'bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 w-full'
