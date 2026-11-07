import { api } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { Button, Card, ErrorBanner, Loading } from '../components/ui'

interface ModelName { name: string; base_url: string; model: string; backend: string; state: string; loaded: boolean; installed: boolean; is_alias: boolean; layers: string[]; manage_service: string | null }
interface Available { base_url: string; backend: string; id: string; size_gb: number | null; loaded: boolean; warning: string }
interface Backend { base_url: string; backend: string; reachable: boolean; state: string; error: string; models: { id: string; size_gb: number | null; loaded: boolean }[] }
interface Overview {
  names: ModelName[]; backends: Backend[]; available: Available[]; memory: { total_gb?: number; available_gb?: number }
  layers: Record<string, string>; assign: { research: string; extraction: string; qc: string; notes: string }
  notes?: string[]; unloaded?: string[]
}

const key = (base_url: string, id: string) => `${base_url}|${id}`
const STATE: Record<string, string> = {
  ready: 'bg-emerald-100 text-emerald-800', loading: 'bg-amber-100 text-amber-900', down: 'bg-red-100 text-red-800',
}
const ROLES: [string, string, string][] = [
  ['writer', 'Writer', 'Writes the scene drafts, summaries and revisions.'],
  ['critic', 'Planner / critic', 'Plans the acts, chapters and scenes and reviews them (unless a layer has its own model below).'],
  ['research', 'Research', 'Reads pages, extracts facts and picks which results to read.'],
  ['extraction', 'Extraction', 'Records what each accepted scene says about the tracked states.'],
  ['qc', 'Prose checks', 'Judges drafts, answers the continuity questions and scores the scene. The same model as the writer means nothing is swapped during a run.'],
]

function Tag({ children, cls }: { children: React.ReactNode; cls: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>
}

export default function Models({ series, running }: { series: string; running: boolean }) {
  const o = useApi<Overview>(`/models?series=${encodeURIComponent(series)}`, 15000)
  const act = useAction()
  const d = o.data
  if (o.error && !d) return <ErrorBanner message={o.error} />
  if (!d) return <Loading what="Reading the model servers" />

  const byName = Object.fromEntries(d.names.map((n) => [n.name, n]))
  // The endpoint name a role stands for: writer and critic are themselves; the others follow an assignment.
  const nameOf = (role: string) => (role === 'writer' || role === 'critic' ? role : d.assign[role as keyof Overview['assign']])

  const pick = async (target: string, value: string) => {
    if (value === '__default') { await act.run(async () => { await api(`/series/${encodeURIComponent(series)}/models`, { method: 'PUT', body: { target } }); o.reload() }); return }
    const [base_url, ...rest] = value.split('|')
    const id = rest.join('|')
    const a = d.available.find((x) => x.base_url === base_url && x.id === id)
    if (a?.warning && !window.confirm(`${id}: ${a.warning}. Use it anyway?`)) return
    await act.run(async () => { await api(`/series/${encodeURIComponent(series)}/models`, { method: 'PUT', body: { target, base_url, model: id } }); o.reload() })
  }

  const Select = ({ target, current }: { target: string; current: ModelName | undefined }) => {
    const value = current ? key(current.base_url, current.model) : ''
    const listed = d.available.some((a) => key(a.base_url, a.id) === value)
    return (
      <select aria-label={`Model for ${target}`} disabled={running || act.busy} value={value}
        onChange={(e) => pick(target, e.target.value)}
        className="min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm disabled:opacity-50">
        {!listed && <option value={value}>{current?.model ? `${current.model} (not listed right now)` : 'no model set'}</option>}
        {target.startsWith('layer:') && <option value="__default">Default for this layer</option>}
        {d.available.map((a) => (
          <option key={key(a.base_url, a.id)} value={key(a.base_url, a.id)}>
            {a.id} · {a.backend}{a.size_gb ? ` · ${a.size_gb} GB` : ''}{a.loaded ? ' · loaded' : ''}{a.warning ? ' · may not fit' : ''}
          </option>
        ))}
      </select>
    )
  }

  return (
    <div className="space-y-3">
      <ErrorBanner message={act.error} onClose={act.clear} />
      {running && <ErrorBanner message="A job is running. Models can be changed when it is paused or finished." />}
      {d.unloaded && d.unloaded.length > 0 && <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">Unloaded to free memory: {d.unloaded.join(', ')}.</p>}
      {d.notes?.map((n) => <p key={n} className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">{n}</p>)}

      <Card title="Servers" right={<Button onClick={o.reload}>Refresh</Button>}>
        <ul className="space-y-2 text-sm">
          {d.backends.map((b) => (
            <li key={b.base_url} className="rounded-md border border-slate-200 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <Tag cls={STATE[b.state] ?? STATE.down}>{b.state}</Tag>
                <span className="font-medium capitalize">{b.backend}</span>
                <span className="break-all text-slate-500">{b.base_url}</span>
              </div>
              {b.error && <p className="mt-1 text-slate-600">{b.error}</p>}
              {b.models.some((m) => m.loaded) && <p className="mt-1 text-slate-700">Loaded: {b.models.filter((m) => m.loaded).map((m) => m.id).join(', ')}</p>}
            </li>
          ))}
        </ul>
        {d.memory.total_gb !== undefined && <p className="mt-2 text-sm text-slate-600">Memory: {d.memory.available_gb} GB free of {d.memory.total_gb} GB (shared with the GPU).</p>}
        <p className="mt-1 text-xs text-slate-500">A colibri server runs one model, chosen when its unit starts, so it is listed here but changed on the machine. Ollama models can be chosen below; the one a role leaves behind is unloaded unless another role uses it.</p>
      </Card>

      <Card title="Models for each job">
        <ul className="space-y-3">
          {ROLES.map(([role, label, help]) => {
            const n = byName[nameOf(role)]
            return (
              <li key={role}>
                <label className="block text-sm font-medium">{label}</label>
                <p className="mb-1 text-xs text-slate-500">{help}</p>
                <Select target={role} current={n} />
                {n && <p className="mt-1 text-xs text-slate-500"><Tag cls={STATE[n.state] ?? STATE.down}>{n.state}</Tag> {n.loaded ? 'loaded now' : n.installed ? 'not loaded yet' : n.model ? 'not found on the server' : ''}</p>}
              </li>
            )
          })}
        </ul>
      </Card>

      <Card title="Planning layers">
        <p className="mb-2 text-xs text-slate-500">Each layer uses the planner / critic model unless you pick another here (for example a stronger model for the north stars). Prose uses the writer.</p>
        <ul className="space-y-3">
          {Object.entries(d.layers).filter(([layer]) => layer !== 'prose').map(([layer, name]) => (
            <li key={layer}>
              <label className="block text-sm font-medium">{layer.replace(/_/g, ' ')}</label>
              <Select target={`layer:${layer}`} current={byName[name]} />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
