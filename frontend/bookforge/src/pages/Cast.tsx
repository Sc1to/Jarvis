import { useState } from 'react'
import { bookPath, del, post, api } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { Button, Card, Empty, ErrorBanner, Loading } from '../components/ui'

interface Entity { id: string; kind: string; name: string; facts: string[]; used: number }
interface CastData { entities: Entity[]; shared_bible: boolean }
interface Usage { entity: string; usage: { where: string; as: string }[] }

const KINDS = ['character', 'place', 'object', 'group', 'concept']

/** The form for one entity: used to add a new one and to edit an existing one (its id is fixed, rename is separate). */
function EntityForm({ initial, onSave, onCancel, busy }: { initial?: Entity; onSave: (e: { id: string; kind: string; name: string; facts: string[] }) => void; onCancel: () => void; busy: boolean }) {
  const [id, setId] = useState(initial?.id ?? '')
  const [kind, setKind] = useState(initial?.kind ?? 'character')
  const [name, setName] = useState(initial?.name ?? '')
  const [facts, setFacts] = useState((initial?.facts ?? []).join('\n'))
  return (
    <form className="space-y-3 text-sm" onSubmit={(e) => { e.preventDefault(); onSave({ id: id.trim(), kind, name: name.trim(), facts: facts.split('\n').map((f) => f.trim()).filter(Boolean) }) }}>
      {!initial && (
        <label className="block">Id
          <input value={id} onChange={(e) => setId(e.target.value)} required pattern="[a-z][a-z0-9\-]*" placeholder="anna-voss" className="mt-1 min-h-10 w-full rounded-md border border-slate-300 p-2" />
          <span className="text-xs text-slate-500">Lowercase letters, digits and -. This is how chapters and scenes refer to it.</span>
        </label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">Name
          <input value={name} onChange={(e) => setName(e.target.value)} required className="mt-1 min-h-10 w-full rounded-md border border-slate-300 p-2" />
        </label>
        <label className="block">Kind
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="mt-1 min-h-10 w-full rounded-md border border-slate-300 bg-white px-2">
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
      </div>
      <label className="block">Facts that do not change (one per line)
        <textarea value={facts} onChange={(e) => setFacts(e.target.value)} rows={5} required className="mt-1 w-full rounded-md border border-slate-300 p-2" />
      </label>
      <div className="flex gap-2">
        <Button type="submit" kind="primary" disabled={busy || !name.trim() || !facts.trim() || (!initial && !id.trim())}>{busy ? 'Saving…' : 'Save'}</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}

function Row({ base, e, shared, onChanged }: { base: string; e: Entity; shared: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const usage = useApi<Usage>(open ? `${base}/cast/${encodeURIComponent(e.id)}/usage` : null)
  const act = useAction()
  const save = async (v: { kind: string; name: string; facts: string[] }) => {
    if (await act.run(() => api(`${base}/cast/${encodeURIComponent(e.id)}`, { method: 'PUT', body: { kind: v.kind, name: v.name, facts: v.facts } }))) { setEditing(false); onChanged(); usage.reload() }
  }
  const remove = async () => {
    if (window.confirm(`Remove ${e.name} from the cast?`) && (await act.run(() => del(`${base}/cast/${encodeURIComponent(e.id)}`)))) onChanged()
  }
  const rename = async () => {
    const next = window.prompt(`New id for ${e.name} (now "${e.id}"). Every reference in chapters, scenes, tracks and rules changes with it (${e.used} place${e.used === 1 ? '' : 's'}). Git keeps the old version.`, e.id)
    if (next && next.trim() && next.trim() !== e.id && (await act.run(() => post(`${base}/cast/${encodeURIComponent(e.id)}/rename`, { id: next.trim() })))) onChanged()
  }
  return (
    <li className="py-2">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex min-h-11 w-full items-center justify-between gap-2 text-left">
        <span className="min-w-0"><span className="font-medium">{e.name}</span> <span className="text-xs text-slate-500">{e.kind} · {e.id}</span></span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${e.used ? 'bg-sky-100 text-sky-800' : 'bg-slate-100 text-slate-600'}`}>{e.used ? `used ${e.used}×` : 'unused'}</span>
      </button>
      {open && (
        <div className="mt-1 space-y-2 pl-1 text-sm">
          <ErrorBanner message={act.error} onClose={act.clear} />
          {editing ? <EntityForm initial={e} busy={act.busy} onSave={save} onCancel={() => setEditing(false)} /> : (
            <>
              <ul className="list-disc space-y-0.5 pl-5 text-slate-700">{e.facts.map((f, i) => <li key={i} className="break-words">{f}</li>)}</ul>
              <div className="flex flex-wrap gap-2">
                <Button disabled={act.busy} onClick={() => setEditing(true)}>Edit</Button>
                <Button disabled={act.busy || shared} title={shared ? 'Give each book its own bible first (Documents → split)' : undefined} onClick={rename}>Rename id</Button>
                <Button kind="danger" disabled={act.busy} onClick={remove}>Delete</Button>
              </div>
              {usage.loading && <Loading />}
              {usage.data && (usage.data.usage.length === 0 ? <p className="text-xs text-slate-500">Nothing refers to this yet.</p> : (
                <details className="rounded-md border border-slate-200 p-2">
                  <summary className="cursor-pointer text-xs font-medium">Used in {usage.data.usage.length} place{usage.data.usage.length === 1 ? '' : 's'}</summary>
                  <ul className="mt-1 max-h-48 space-y-0.5 overflow-auto text-xs text-slate-700">{usage.data.usage.map((u, i) => <li key={i} className="break-words">{u.where} <span className="text-slate-500">({u.as})</span></li>)}</ul>
                </details>
              ))}
            </>
          )}
        </div>
      )}
    </li>
  )
}

export default function Cast({ series, book }: { series: string; book: string }) {
  const base = bookPath(series, book)
  const data = useApi<CastData>(`${base}/cast`)
  const [filter, setFilter] = useState('all')
  const [adding, setAdding] = useState(false)
  const add = useAction()
  const create = async (v: { id: string; kind: string; name: string; facts: string[] }) => {
    if (await add.run(() => post(`${base}/cast`, v))) { setAdding(false); data.reload() }
  }
  const shown = (data.data?.entities ?? []).filter((e) => filter === 'all' || e.kind === filter)
  return (
    <div className="space-y-3">
      {data.error && <ErrorBanner message={data.error} />}
      {data.loading && !data.data && <Loading />}
      {data.data?.shared_bible && (
        <Card tone="warn"><p className="text-sm">This series still shares one cast between all its books. You can add, edit and delete here, but renaming needs each book to have its own (Documents tab).</p></Card>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">Show <select value={filter} onChange={(e) => setFilter(e.target.value)} className="min-h-10 rounded-md border border-slate-300 bg-white px-2">
          <option value="all">everything</option>{KINDS.map((k) => <option key={k} value={k}>{k}s</option>)}
        </select></label>
        <span className="ml-auto"><Button kind="primary" onClick={() => setAdding(!adding)}>{adding ? 'Cancel' : 'Add to the cast'}</Button></span>
      </div>
      {adding && <Card title="New entry"><ErrorBanner message={add.error} onClose={add.clear} /><EntityForm busy={add.busy} onSave={create} onCancel={() => setAdding(false)} /></Card>}
      {data.data && (shown.length === 0 ? <Empty>Nothing here yet.</Empty> : (
        <Card><ul className="divide-y divide-slate-100">{shown.map((e) => <Row key={e.id} base={base} e={e} shared={data.data!.shared_bible} onChanged={data.reload} />)}</ul></Card>
      ))}
    </div>
  )
}
