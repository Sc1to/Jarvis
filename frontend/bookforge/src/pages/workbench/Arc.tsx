import { useEffect, useState } from 'react'
import { api, bookPath, post } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import type { ArcView, TensionPreview } from '../../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading } from '../../components/ui'

export default function Arc({ series, book }: { series: string; book: string }) {
  const base = `${bookPath(series, book)}/workbench/arc`
  const arc = useApi<ArcView>(base)
  const [sel, setSel] = useState('')
  const [value, setValue] = useState(5)
  const [preview, setPreview] = useState<TensionPreview | null>(null)
  const act = useAction()
  const [t, setT] = useState({ id: '', note: '', setup: '', payoff: '' })

  const chapter = arc.data?.tension.chapters.find((c) => c.id === sel)
  useEffect(() => { if (chapter) setValue(chapter.tension) }, [chapter?.id, chapter?.tension])
  useEffect(() => {
    if (!sel || !chapter || value === chapter.tension) { setPreview(null); return }
    let alive = true
    post<TensionPreview>(`${base}/tension`, { chapter: sel, value }).then((p) => { if (alive) setPreview(p) }).catch(() => undefined)
    return () => { alive = false }
  }, [sel, value, chapter?.tension, base])

  const apply = async () => {
    if (window.confirm(`${preview?.consequence}. Change ${sel} from ${chapter?.tension} to ${value}?`) && (await act.run(() => post(`${base}/tension`, { chapter: sel, value, apply: true })))) { arc.reload() }
  }
  const addThread = async () => { if (await act.run(() => api(`${base}/threads/${encodeURIComponent(t.id)}`, { method: 'PUT', body: { note: t.note, setup: t.setup, payoff: t.payoff } }))) { setT({ id: '', note: '', setup: '', payoff: '' }); arc.reload() } }
  const [m, setM] = useState({ label: '', chapter: '' })
  const addMilestone = async () => { if (await act.run(() => post(`${base}/milestones`, m))) { setM({ label: '', chapter: m.chapter }); arc.reload() } }
  const dropMilestone = async (id: string) => { if (await act.run(() => api(`${base}/milestones/${encodeURIComponent(id)}`, { method: 'DELETE' }))) arc.reload() }
  const dropThread = async (id: string) => { if (await act.run(() => api(`${base}/threads/${encodeURIComponent(id)}`, { method: 'DELETE' }))) arc.reload() }

  if (arc.error) return <ErrorBanner message={arc.error} />
  if (!arc.data) return <Loading />
  const { tension, threads, milestones } = arc.data
  const n = Math.max(threads.scenes.length, 1)
  const nch = Math.max(milestones.chapters.length, 1)
  const num = (id: string) => id.split('.').pop()?.replace('ch', '') ?? id

  return (
    <div className="space-y-3">
      <ErrorBanner message={act.error} onClose={act.clear} />
      <Card title="Story milestones">
        {!milestones.chapters.length ? <Empty>No chapters planned yet.</Empty> : (
          <>
            <div className="relative mt-1 h-6 rounded bg-slate-100" aria-hidden>
              {milestones.items.filter((x) => x.at !== null).map((x) => (
                <span key={x.id} title={`ch ${num(x.chapter)}: ${x.label}`} className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-600" style={{ left: `${(((x.at ?? 0) + 0.5) / nch) * 100}%` }} />
              ))}
            </div>
            <div className="mt-0.5 flex justify-between text-[10px] text-slate-500"><span>ch 1</span><span>ch {num(milestones.chapters[milestones.chapters.length - 1].id)}</span></div>
            {!milestones.items.length && <Empty>Nothing yet. Add what happens where, like “body found” in chapter 2.</Empty>}
            <ul className="mt-2 divide-y divide-slate-100">
              {milestones.items.map((x) => (
                <li key={x.id} className="flex items-center justify-between gap-2 py-1 text-sm">
                  <span><span className="inline-block w-12 tabular-nums text-slate-500">ch {num(x.chapter)}</span>{x.label}{x.problem && <span className="ml-2 text-xs text-red-700">{x.problem}</span>}</span>
                  <button onClick={() => dropMilestone(x.id)} className="min-h-10 px-2 text-xs text-slate-500 underline">remove</button>
                </li>
              ))}
            </ul>
            <form className="mt-3 grid grid-cols-[1fr_auto] gap-2 border-t border-slate-100 pt-3" onSubmit={(e) => { e.preventDefault(); void addMilestone() }}>
              <input value={m.label} onChange={(e) => setM({ ...m, label: e.target.value })} placeholder="what happens, like riddle solved" maxLength={120} required className="col-span-2 min-h-10 rounded-md border border-slate-300 px-2 text-sm" />
              <select value={m.chapter} onChange={(e) => setM({ ...m, chapter: e.target.value })} required aria-label="Chapter" className="min-h-10 rounded-md border border-slate-300 bg-white px-2 text-sm"><option value="">chapter…</option>{milestones.chapters.map((c) => <option key={c.id} value={c.id}>ch {num(c.id)} {c.title}</option>)}</select>
              <Button type="submit" kind="primary" disabled={act.busy}>Add</Button>
            </form>
            <p className="mt-2 text-xs text-slate-500">Notes for you only: nothing is checked against the prose and changing them makes nothing stale.</p>
          </>
        )}
      </Card>
      <Card title="Tension per chapter">
        {!tension.chapters.length ? <Empty>No chapters planned yet.</Empty> : (
          <>
            <div className="overflow-x-auto"><div className="flex h-40 items-end gap-1" style={{ minWidth: Math.max(tension.chapters.length * 28, 280) }} role="group" aria-label="Chapters, tap one to change its tension">
              {tension.chapters.map((c) => (
                <button key={c.id} onClick={() => setSel(c.id)} aria-pressed={sel === c.id} title={`${c.title}: ${c.tension}/10`} className="flex h-full min-w-6 flex-1 flex-col justify-end">
                  <span className="mb-0.5 text-center text-[10px] tabular-nums text-slate-500">{c.tension}</span>
                  <span className={`block w-full rounded-t ${sel === c.id ? 'bg-slate-900' : 'bg-sky-400'}`} style={{ height: `${c.tension * 10}%` }} />
                  <span className="mt-1 text-center text-[10px] text-slate-500">{c.id.split('.').pop()?.replace('ch', '')}</span>
                </button>
              ))}
            </div></div>
            {tension.notes.map((x) => <p key={x} className="mt-2 text-sm text-amber-800">! {x}</p>)}
            {!tension.notes.length && <p className="mt-2 text-sm text-emerald-800">The curve has a climax in the last third and no long flat stretch.</p>}
            {chapter && (
              <div className="mt-3 rounded-md border border-slate-200 p-3">
                <p className="text-sm font-medium">{chapter.id} {chapter.title} <span className="font-normal text-slate-500">({chapter.act})</span></p>
                <div className="mt-2 flex items-center gap-2">
                  <Button onClick={() => setValue(Math.max(1, value - 1))} disabled={value <= 1}>−</Button>
                  <span className="w-10 text-center text-lg tabular-nums">{value}</span>
                  <Button onClick={() => setValue(Math.min(10, value + 1))} disabled={value >= 10}>+</Button>
                  <Button kind="primary" onClick={apply} disabled={act.busy || value === chapter.tension}>Apply</Button>
                </div>
                <p className="mt-2 text-xs text-slate-600">{preview ? preview.consequence : value === chapter.tension ? `${chapter.scenes} scene(s), ${chapter.written} written. Change the number to see what it would affect.` : '…'}</p>
              </div>
            )}
          </>
        )}
      </Card>

      <Card title={`Threads: setups and payoffs${threads.unpaid ? ` (${threads.unpaid} unpaid)` : ''}`}>
        {!threads.threads.length && <Empty>No threads yet. Add each thing set up early that must pay off later.</Empty>}
        <ul className="space-y-3">
          {threads.threads.map((th) => (
            <li key={th.id}>
              <div className="flex items-center justify-between gap-2 text-sm"><span className={th.problem ? 'font-medium text-red-700' : 'font-medium'}>{th.id}</span>
                <button onClick={() => dropThread(th.id)} className="min-h-10 px-2 text-xs text-slate-500 underline">remove</button></div>
              <p className="text-xs text-slate-600">{th.note}</p>
              <div className="relative mt-2 h-5 rounded bg-slate-100" aria-hidden>
                {th.setup_at !== null && <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-600" style={{ left: `${((th.setup_at + 0.5) / n) * 100}%` }} />}
                {th.payoff_at !== null && th.setup_at !== null && <span className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${th.problem ? 'bg-red-500' : 'bg-emerald-500'}`} style={{ left: `${((Math.min(th.setup_at, th.payoff_at) + 0.5) / n) * 100}%`, width: `${(Math.abs(th.payoff_at - th.setup_at) / n) * 100}%` }} />}
                {th.payoff_at !== null && <span className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ${th.problem ? 'bg-red-600' : 'bg-emerald-600'}`} style={{ left: `${((th.payoff_at + 0.5) / n) * 100}%` }} />}
                {th.payoff_at === null && th.setup_at !== null && <span className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-red-500" style={{ left: `${((th.setup_at + 0.5) / n) * 100}%`, right: 0 }} />}
              </div>
              <p className={`mt-1 text-xs ${th.problem ? 'text-red-700' : 'text-slate-500'}`}>{th.setup} → {th.payoff || '…'}{th.problem && ` · ${th.problem}`}</p>
            </li>
          ))}
        </ul>
        <form className="mt-4 space-y-2 border-t border-slate-100 pt-3" onSubmit={(e) => { e.preventDefault(); void addThread() }}>
          <p className="text-sm font-medium">Add or change a thread</p>
          <input value={t.id} onChange={(e) => setT({ ...t, id: e.target.value })} placeholder="id, like the-vestry-key" pattern="[a-z][a-z0-9\-]*" required className="min-h-10 w-full rounded-md border border-slate-300 px-2 text-sm" />
          <input value={t.note} onChange={(e) => setT({ ...t, note: e.target.value })} placeholder="what is set up" className="min-h-10 w-full rounded-md border border-slate-300 px-2 text-sm" />
          <div className="grid grid-cols-2 gap-2">
            <select value={t.setup} onChange={(e) => setT({ ...t, setup: e.target.value })} required aria-label="Setup scene" className="min-h-10 rounded-md border border-slate-300 bg-white px-2 text-sm"><option value="">setup scene</option>{threads.scenes.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            <select value={t.payoff} onChange={(e) => setT({ ...t, payoff: e.target.value })} aria-label="Payoff scene" className="min-h-10 rounded-md border border-slate-300 bg-white px-2 text-sm"><option value="">no payoff yet</option>{threads.scenes.map((s) => <option key={s} value={s}>{s}</option>)}</select>
          </div>
          <Button type="submit" kind="primary" disabled={act.busy}>Save thread</Button>
        </form>
      </Card>
    </div>
  )
}
