import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { TrackData } from '../lib/types'
import { Empty, ErrorBanner, Loading } from '../components/ui'

const COLORS = ['bg-sky-200', 'bg-violet-200', 'bg-teal-200', 'bg-rose-200', 'bg-lime-200', 'bg-orange-200']

/** Each state track as a bar across the book (a segment per plan entry), with a mark at every scene where the prose was checked. */
export default function Tracks({ series, book }: { series: string; book: string }) {
  const t = useApi<TrackData>(`${bookPath(series, book)}/tracks`, 30000)
  if (t.error) return <ErrorBanner message={t.error} />
  if (!t.data) return <Loading />
  const { scenes, chapters, tracks } = t.data
  if (!tracks.length || !scenes.length) return <Empty>No state tracks yet. They are created with the chapters.</Empty>

  const n = scenes.length
  const index = new Map(scenes.map((s, i) => [s.id, i]))
  const firstOf = (ch: string) => { const i = scenes.findIndex((s) => s.chapter === ch); return i < 0 ? n : i }
  const at = (pos: string) => (index.has(pos) ? index.get(pos)! : firstOf(pos))
  const width = Math.max(n * 28, 560)
  const pct = (i: number) => `${(100 * i) / n}%`

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Each bar is one state across the book. Dots mark scenes where the extraction compared the prose with the plan:
        <span className="ml-1 inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-600" /> agrees</span>
        <span className="ml-2 inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-red-600" /> differs</span>
        <span className="ml-2 inline-flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full bg-slate-400" /> unclear</span>
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3">
        <div style={{ width }}>
          <div className="relative mb-2 h-5 text-[10px] text-slate-500" aria-hidden>
            {chapters.map((c) => firstOf(c) < n && <span key={c} className="absolute border-l border-slate-300 pl-1" style={{ left: pct(firstOf(c)) }}>{c.split('.').pop()}</span>)}
          </div>
          {tracks.map((tr, k) => {
            const entries = [...tr.plan].sort((a, b) => at(a.from) - at(b.from))
            return (
              <div key={tr.id} className="mb-4">
                <p className="mb-1 text-xs font-medium text-slate-700">{tr.entity_name} · {tr.kind} <span className="font-normal text-slate-400">({tr.id}, v{tr.version})</span></p>
                <div className="relative h-8 rounded bg-slate-50">
                  {entries.map((e, i) => {
                    const start = at(e.from)
                    const end = i + 1 < entries.length ? at(entries[i + 1].from) : n
                    return (
                      <div key={e.from} title={`${e.from}: ${e.value}`}
                        className={`absolute top-0 flex h-8 items-center overflow-hidden whitespace-nowrap border-l-2 border-white px-1 text-[11px] ${COLORS[(k + i) % COLORS.length]} ${e.must_show ? 'font-semibold' : ''}`}
                        style={{ left: pct(start), width: `${(100 * Math.max(end - start, 0)) / n}%` }}>{e.value}</div>
                    )
                  })}
                  {tr.observed.map((o, oi) => index.has(o.at) && (
                    <a key={`${o.at}-${oi}`} href={href({ series, book, tab: 'scene', id: o.at })} title={`${o.at}: ${o.value}${o.matches_plan === false ? ' (differs from the plan)' : ''}`}
                      className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white ${o.matches_plan === true ? 'bg-emerald-600' : o.matches_plan === false ? 'bg-red-600' : 'bg-slate-400'}`}
                      style={{ left: pct(index.get(o.at)! + 0.5) }} />
                  ))}
                </div>
                <ul className="mt-1 text-[11px] text-slate-500">
                  {entries.map((e) => <li key={e.from}><span className="font-mono">{e.from}</span> {e.must_show ? '(shown on the page) ' : ''}{e.value}</li>)}
                </ul>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
