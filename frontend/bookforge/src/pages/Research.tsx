import { useMemo, useState } from 'react'
import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { Fact } from '../lib/types'
import { Empty, ErrorBanner, Loading } from '../components/ui'

export default function Research({ series, book }: { series: string; book: string }) {
  const facts = useApi<Fact[]>(`${bookPath(series, book)}/research`)
  const [scene, setScene] = useState('')
  const [query, setQuery] = useState('')
  const [sensitiveOnly, setSensitiveOnly] = useState(false)
  const scenes = useMemo(() => [...new Set((facts.data ?? []).flatMap((f) => f.used_in))].sort(), [facts.data])
  if (facts.error) return <ErrorBanner message={facts.error} />
  if (!facts.data) return <Loading />
  if (!facts.data.length) return <Empty>No research facts yet.</Empty>

  const q = query.trim().toLowerCase()
  const shown = facts.data.filter((f) => (!scene || f.used_in.includes(scene)) && (!sensitiveOnly || f.sensitive) &&
    (!q || `${f.claim} ${f.title} ${f.question}`.toLowerCase().includes(q)))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search facts" aria-label="Search facts"
          className="min-h-10 min-w-0 flex-1 rounded-md border border-slate-300 px-2 text-sm" />
        <select value={scene} onChange={(e) => setScene(e.target.value)} aria-label="Only facts used in a scene" className="min-h-10 rounded-md border border-slate-300 bg-white px-2 text-sm">
          <option value="">all scenes</option>
          {scenes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label className="flex min-h-10 items-center gap-1 text-sm"><input type="checkbox" checked={sensitiveOnly} onChange={(e) => setSensitiveOnly(e.target.checked)} /> verify first</label>
      </div>
      <p className="text-xs text-slate-500">{shown.length} of {facts.data.length} facts</p>
      <ul className="space-y-2">
        {shown.map((f) => (
          <li key={f.id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{f.id}</span>
              {f.sensitive && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">verify before publishing</span>}
            </div>
            <p className="mt-1">{f.claim}</p>
            <blockquote className="mt-1 border-l-4 border-slate-300 pl-3 text-xs italic text-slate-600">“{f.quote}”</blockquote>
            <a href={f.url} target="_blank" rel="noreferrer noopener" className="mt-1 block break-all text-xs underline">{f.title || f.url}</a>
            <p className="mt-1 text-xs text-slate-500">{f.layer} · fetched {f.fetched}</p>
            <p className="mt-1 text-xs">Used in: {f.used_in.length ? f.used_in.map((s, i) => <span key={s}>{i ? ', ' : ''}<a className="underline" href={href({ series, book, tab: 'scene', id: s })}>{s}</a></span>) : 'not cited yet'}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
