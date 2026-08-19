import { useEffect, useState } from 'react'
import { getAgents, createAgent, updateAgent, deleteAgent, deployAgent, stopAgent, getModels } from '../api.js'

const TOOLS = ['filesystem', 'terminal', 'git', 'github', 'web', 'test_runner', 'code_interpreter']
const EMPTY = { name: '', description: '', model: '', tools: [], memory_scope: 'session', ui_type: 'none', ui_route: '', system_prompt: '' }

export default function Agents() {
  const [agents, setAgents] = useState([])
  const [models, setModels] = useState([])
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [collapsed, setCollapsed] = useState(new Set())

  async function load() {
    try {
      const [a, m] = await Promise.all([getAgents(), getModels().catch(() => ({ data: { models: [] } }))])
      setAgents(a.data)
      setModels(m.data.models ?? [])
    } catch (e) { setError(e.message) }
  }

  useEffect(() => { load() }, [])

  function field(key, val) { setForm(f => ({ ...f, [key]: val })) }

  function toggleTool(t) {
    setForm(f => ({
      ...f,
      tools: f.tools.includes(t) ? f.tools.filter(x => x !== t) : [...f.tools, t],
    }))
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    try {
      if (editing) {
        await updateAgent(editing, form)
        setMsg('Agent updated')
        setEditing(null)
      } else {
        await createAgent(form)
        setMsg('Agent created')
      }
      setForm(EMPTY)
      load()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
  }

  function startEdit(a) {
    setEditing(a.id)
    setForm({
      name: a.name, description: a.description ?? '', model: a.model,
      tools: JSON.parse(a.tools ?? '[]'), memory_scope: a.memory_scope,
      ui_type: a.ui_type, ui_route: a.ui_route ?? '', system_prompt: a.system_prompt ?? '',
    })
  }

  async function remove(id) {
    if (!confirm('Delete agent?')) return
    try { await deleteAgent(id); load() } catch (e) { setError(e.message) }
  }

  async function deploy(id) {
    setMsg(null); setError(null)
    try { const r = await deployAgent(id); setMsg(`Deployed on port ${r.data.port}`) } catch (e) { setError(e.message) }
  }

  async function stop(id) {
    try { await stopAgent(id); setMsg('Agent stopped') } catch (e) { setError(e.message) }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Agents</h1>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {msg && <p className="text-green-400 text-sm">{msg}</p>}

      <form onSubmit={submit} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <h2 className="text-sm font-medium text-gray-400">{editing ? 'Edit Agent' : 'Create Agent'}</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <input className={inp} placeholder="Name" value={form.name} onChange={e => field('name', e.target.value)} required />
          <input className={inp} placeholder="Description" value={form.description} onChange={e => field('description', e.target.value)} />
          <select className={inp} value={form.model} onChange={e => field('model', e.target.value)} required>
            <option value="">Select model…</option>
            {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
          <select className={inp} value={form.memory_scope} onChange={e => field('memory_scope', e.target.value)}>
            <option value="session">session</option>
            <option value="project">project</option>
            <option value="global">global</option>
          </select>
          <select className={inp} value={form.ui_type} onChange={e => field('ui_type', e.target.value)}>
            <option value="none">No UI</option>
            <option value="chat">Chat UI</option>
            <option value="dashboard">Dashboard UI</option>
          </select>
          {form.ui_type !== 'none' && (
            <input className={inp} placeholder="UI route (e.g. /myagent)" value={form.ui_route} onChange={e => field('ui_route', e.target.value)} />
          )}
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">Tools</p>
          <div className="flex flex-wrap gap-2">
            {TOOLS.map(t => (
              <label key={t} className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.tools.includes(t)}
                  onChange={() => toggleTool(t)}
                  className="accent-blue-500"
                />
                <span className={form.tools.includes(t) ? 'text-white' : 'text-gray-400'}>{t}</span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">System prompt</p>
          <textarea
            className={`${inp} min-h-[80px] resize-y`}
            placeholder="You are a..."
            value={form.system_prompt}
            onChange={e => field('system_prompt', e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded">
            {editing ? 'Save' : 'Create'}
          </button>
          {editing && (
            <button type="button" onClick={() => { setEditing(null); setForm(EMPTY) }}
              className="text-sm text-gray-400 hover:text-white px-4 py-2">
              Cancel
            </button>
          )}
        </div>
      </form>

      <div className="space-y-4">
        {agents.length === 0 && <p className="text-gray-500 text-sm">No agents configured yet.</p>}
        {Object.entries(
          agents.reduce((acc, a) => {
            const domain = a.name.includes('_') ? a.name.split('_')[0] : 'custom'
            ;(acc[domain] = acc[domain] ?? []).push(a)
            return acc
          }, {})
        ).map(([domain, list]) => (
          <div key={domain} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-4 py-2 bg-gray-800 hover:bg-gray-750 text-sm font-medium text-gray-300"
              onClick={() => setCollapsed(c => { const n = new Set(c); n.has(domain) ? n.delete(domain) : n.add(domain); return n })}
            >
              <span className="capitalize">{domain} <span className="text-gray-500 font-normal">({list.length})</span></span>
              <span className="text-gray-500 text-xs">{collapsed.has(domain) ? '▶' : '▼'}</span>
            </button>
            {!collapsed.has(domain) && (
              <div className="divide-y divide-gray-700">
                {list.map(a => (
                  <div key={a.id} className="bg-gray-800 px-4 py-3">
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">{a.name}</p>
                        <p className="text-xs text-gray-500">{a.model} · {a.memory_scope}</p>
                        {a.description && <p className="text-xs text-gray-500 mt-0.5">{a.description}</p>}
                        {a.backend_port && <p className="text-xs text-blue-400 mt-0.5">Port {a.backend_port}</p>}
                      </div>
                      <div className="flex gap-2 flex-shrink-0">
                        <button onClick={() => startEdit(a)} className="text-xs text-gray-400 hover:text-white">Edit</button>
                        <button onClick={() => deploy(a.id)} className="text-xs text-green-400 hover:text-green-300">Deploy</button>
                        <button onClick={() => stop(a.id)} className="text-xs text-yellow-400 hover:text-yellow-300">Stop</button>
                        <button onClick={() => remove(a.id)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

const inp = 'bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 w-full'
