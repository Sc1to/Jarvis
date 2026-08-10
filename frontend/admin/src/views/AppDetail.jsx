import { useEffect, useState, useMemo } from 'react'
import { getAppAgents, createAgent, updateAgent, deleteAgent, getModels } from '../api.js'

const TOOLS = ['filesystem', 'terminal', 'git', 'github', 'web', 'test_runner', 'code_interpreter']
const EMPTY_AGENT = { name: '', description: '', model: '', tools: [], memory_scope: 'session', ui_type: 'none', ui_route: '', system_prompt: '', calls: [] }

// ── Communication diagram ─────────────────────────────────────────────────────

const NODE_W = 172
const NODE_H = 72
const H_GAP  = 76
const V_GAP  = 16
const PAD_X  = 32
const PAD_Y  = 44

const PHASE_MAP = {
  1: { color: '#3B7EF6', label: 'Phase 1' },
  2: { color: '#C47A1E', label: 'Phase 2' },
  3: { color: '#16A17A', label: 'Phase 3' },
  0: { color: '#7C5CDB', label: 'Agent'   },
}

function detectPhase(agent) {
  const d = (agent.description || '').toLowerCase()
  if (d.includes('phase 1')) return 1
  if (d.includes('phase 2')) return 2
  if (d.includes('phase 3')) return 3
  return 0
}

function shortLabel(name) {
  const parts = name.split('_')
  const tail = parts.length > 2 ? parts.slice(-2) : parts
  return tail.map(p => p.length <= 3 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)).join(' ')
}

function buildLayout(agents) {
  if (!agents.length) return { positions: {}, edges: [], svgW: 0, svgH: 0 }

  const byName = Object.fromEntries(agents.map(a => [a.name, a]))
  const called = new Set(agents.flatMap(a => JSON.parse(a.calls || '[]')))
  const roots  = agents.filter(a => !called.has(a.name))

  const levels = []
  const placed = new Set()
  let front = roots.length ? roots : [agents[0]]
  while (front.length) {
    levels.push(front)
    front.forEach(a => placed.add(a.name))
    const next = []
    front.forEach(a => JSON.parse(a.calls || '[]').forEach(n => {
      if (byName[n] && !placed.has(n)) { placed.add(n); next.push(byName[n]) }
    }))
    front = next
  }
  const orphans = agents.filter(a => !placed.has(a.name))
  if (orphans.length) levels.push(orphans)

  const maxRows = Math.max(...levels.map(l => l.length))
  const svgH = PAD_Y * 2 + maxRows * NODE_H + (maxRows - 1) * V_GAP
  const svgW = PAD_X * 2 + levels.length * NODE_W + (levels.length - 1) * H_GAP

  const positions = {}
  levels.forEach((level, li) => {
    const blockH = level.length * NODE_H + (level.length - 1) * V_GAP
    const y0 = (svgH - blockH) / 2
    level.forEach((a, ni) => {
      positions[a.name] = { x: PAD_X + li * (NODE_W + H_GAP), y: y0 + ni * (NODE_H + V_GAP) }
    })
  })

  const edges = agents.flatMap(a =>
    JSON.parse(a.calls || '[]')
      .filter(n => positions[a.name] && positions[n])
      .map(n => ({ from: a.name, to: n, phase: detectPhase(a) }))
  )

  return { positions, edges, svgW, svgH }
}

function CommunicationDiagram({ agents }) {
  const { positions, edges, svgW, svgH } = useMemo(() => buildLayout(agents), [agents])
  if (!agents.length) return null

  const presentPhases = [...new Set(agents.map(detectPhase))].filter(p => p > 0)

  return (
    <div style={{ background: '#0c1118', borderRadius: 12, border: '1px solid #1e2535', position: 'relative', overflow: 'hidden' }}>
      {/* dot grid */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.055) 1px, transparent 1px)',
        backgroundSize: '22px 22px',
      }} />

      {/* header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px 0', position: 'relative', zIndex: 1 }}>
        <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#485068', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Agent communication
        </span>
        {presentPhases.length > 0 && (
          <div style={{ display: 'flex', gap: 12 }}>
            {presentPhases.map(p => (
              <span key={p} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: '#5a6478', fontFamily: 'monospace' }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: PHASE_MAP[p].color, display: 'inline-block', opacity: 0.85 }} />
                {PHASE_MAP[p].label}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* diagram canvas */}
      <div style={{ overflowX: 'auto' }}>
        <div style={{ position: 'relative', width: svgW, height: svgH }}>

          {/* SVG: edges */}
          <svg width={svgW} height={svgH} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <defs>
              {Object.entries(PHASE_MAP).map(([p, { color }]) => (
                <marker key={p} id={`tip-${p}`} markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
                  <path d="M0,1 L0,6 L6,3.5 z" fill={color} fillOpacity="0.65" />
                </marker>
              ))}
            </defs>
            {edges.map((e, i) => {
              const f = positions[e.from], t = positions[e.to]
              const x1 = f.x + NODE_W, y1 = f.y + NODE_H / 2
              const x2 = t.x,          y2 = t.y + NODE_H / 2
              const cx = (x1 + x2) / 2
              return (
                <path key={i}
                  d={`M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`}
                  stroke={PHASE_MAP[e.phase].color} strokeWidth="1.5"
                  strokeOpacity="0.42" fill="none"
                  markerEnd={`url(#tip-${e.phase})`}
                />
              )
            })}
          </svg>

          {/* HTML: nodes */}
          {agents.map(a => {
            const pos = positions[a.name]
            if (!pos) return null
            const { color, label } = PHASE_MAP[detectPhase(a)]
            return (
              <div key={a.name} style={{
                position: 'absolute', left: pos.x, top: pos.y,
                width: NODE_W, height: NODE_H, boxSizing: 'border-box',
                background: '#141b27', border: '1px solid #222c3f',
                borderLeft: `3px solid ${color}`, borderRadius: 8,
                padding: '10px 12px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 4,
              }}>
                <span style={{ fontSize: 9, fontFamily: 'monospace', color, textTransform: 'uppercase', letterSpacing: '0.09em', opacity: 0.8 }}>
                  {label}
                </span>
                <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'monospace', color: '#dde4f0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {shortLabel(a.name)}
                </span>
                {a.description && (
                  <span style={{ fontSize: 10, color: '#49566e', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.3 }}>
                    {a.description}
                  </span>
                )}
              </div>
            )
          })}
        </div>
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

      {agents.length > 0 && <CommunicationDiagram agents={agents} />}

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
