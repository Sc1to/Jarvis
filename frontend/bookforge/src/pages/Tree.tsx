import { useState } from 'react'
import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { TreeAct } from '../lib/types'
import { Dot, Empty, ErrorBanner, Loading, STATUS_STYLE } from '../components/ui'

export default function Tree({ series, book }: { series: string; book: string }) {
  const tree = useApi<TreeAct[]>(`${bookPath(series, book)}/structure`, 15000)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (tree.error) return <ErrorBanner message={tree.error} />
  if (!tree.data) return <Loading />
  if (!tree.data.length) return <Empty>The book has no structure yet. Run the pipeline to plan it.</Empty>

  const count = (scenes: { status: string }[]) => {
    const n: Record<string, number> = {}
    scenes.forEach((s) => { n[s.status] = (n[s.status] ?? 0) + 1 })
    return n
  }

  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-3 text-xs text-slate-600" aria-label="Legend">
        {['accepted', 'flagged', 'stale', 'pending'].map((k) => <li key={k} className="flex items-center gap-1"><Dot status={k} />{STATUS_STYLE[k].label}</li>)}
      </ul>
      {tree.data.map((act) => (
        <section key={act.id || act.title} className="rounded-lg border border-slate-200 bg-white">
          <h2 className="border-b border-slate-100 px-3 py-2 text-sm font-semibold">{act.title}</h2>
          <ul>
            {act.chapters.map((ch) => {
              const all = ch.scenes
              const isOpen = open[ch.id] ?? all.some((s) => s.status === 'flagged' || s.status === 'stale')
              const n = count(all)
              return (
                <li key={ch.id} className="border-b border-slate-100 last:border-0">
                  <button onClick={() => setOpen({ ...open, [ch.id]: !isOpen })} aria-expanded={isOpen}
                    className="flex min-h-12 w-full items-center gap-2 px-3 py-2 text-left">
                    <span className="w-4 text-slate-400">{isOpen ? '▾' : '▸'}</span>
                    <span className="min-w-0 flex-1 truncate text-sm">{ch.title}</span>
                    <span className="flex items-center gap-0.5" aria-label={Object.entries(n).map(([k, v]) => `${v} ${k}`).join(', ')}>
                      {all.map((s) => <Dot key={s.id} status={s.status} title={`${s.id}: ${s.status}`} />)}
                    </span>
                  </button>
                  {isOpen && (
                    <ul className="pb-2 pl-9 pr-3">
                      {all.map((s) => (
                        <li key={s.id}>
                          <a href={href({ series, book, tab: 'scene', id: s.id })} className="flex min-h-11 items-start gap-2 rounded-md py-2 hover:bg-slate-50">
                            <span className="mt-1"><Dot status={s.status} /></span>
                            <span className="min-w-0 flex-1">
                              <span className="block text-sm font-medium">{s.id.split('.').slice(1).join('.')}</span>
                              <span className="block text-xs text-slate-500">{s.purpose}</span>
                              {s.note && s.status !== 'accepted' && <span className="block break-words text-xs text-amber-800">{s.note}</span>}
                            </span>
                          </a>
                        </li>
                      ))}
                      {!all.length && <li className="py-2 text-xs text-slate-500">No scenes planned.</li>}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
