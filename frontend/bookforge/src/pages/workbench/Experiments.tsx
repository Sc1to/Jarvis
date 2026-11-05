import { useState } from 'react'
import { bookPath, post } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import type { ExperimentSummary, ExperimentView } from '../../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, fmtTime } from '../../components/ui'

const WHO = { a: 'the current prompt', b: 'the candidate', tie: 'a tie' } as const

function Experiment({ series, book, name, onChange }: { series: string; book: string; name: string; onChange: () => void }) {
  const base = `${bookPath(series, book)}/workbench/experiments/${name}`
  const view = useApi<ExperimentView>(base)
  const act = useAction()
  const [open, setOpen] = useState<string | null>(null)
  if (view.error) return <ErrorBanner message={view.error} />
  if (!view.data) return <Loading />
  const v = view.data
  const vote = async (benchmark: string, choice: 'first' | 'second' | 'tie') => { if (await act.run(() => post(`${base}/vote`, { benchmark, choice }))) { view.reload(); onChange() } }
  const promote = async () => { if (window.confirm('Use the candidate as your version of this prompt?') && (await act.run(() => post(`${base}/promote`)))) { view.reload(); onChange() } }

  return (
    <div className="space-y-3">
      <Card title={`${v.name}: ${v.template}`} right={v.promoted ? <span className="text-xs text-emerald-800">adopted</span> : <Button kind="primary" onClick={promote} disabled={act.busy}>Adopt the candidate</Button>}>
        <p className="text-sm">{v.judge ? `The judge: current ${v.judge.a}, candidate ${v.judge.b}, tie ${v.judge.tie}.` : "The judge's totals show once you have voted on every pair."} Yours: current {v.yours.a}, candidate {v.yours.b}, tie {v.yours.tie} (voted {v.yours.a + v.yours.b + v.yours.tie} of {v.yours.of}).</p>
        {v.warnings.map((w) => <p key={w} className="mt-1 text-xs text-amber-800">{w}</p>)}
        <details className="mt-2"><summary className="min-h-10 cursor-pointer text-sm">What differs between the two prompts</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-2 text-xs">{v.diff}</pre></details>
        <ErrorBanner message={act.error} onClose={act.clear} />
      </Card>
      <p className="text-sm text-slate-600">Read both versions and vote before the answer is shown. Their order is shuffled.</p>
      {v.pairs.map((p) => (
        <Card key={p.id} title={p.id} right={p.voted && <span className="text-xs text-slate-500">you chose {WHO[p.vote!]}{p.judge && `; the judge chose ${WHO[p.judge as 'a' | 'b' | 'tie'] ?? p.judge}`}</span>}>
          <div className="grid gap-3 lg:grid-cols-2">
            {([['first', p.first, p.first_is], ['second', p.second, p.second_is]] as const).map(([k, text, is]) => (
              <div key={k} className="rounded-md border border-slate-200 p-2">
                <p className="mb-1 text-xs font-semibold uppercase text-slate-500">{k === 'first' ? 'Version 1' : 'Version 2'}{is && ` · ${WHO[is]}`}</p>
                <div className={`font-serif text-[14px] leading-relaxed [overflow-wrap:anywhere] ${open === p.id ? '' : 'max-h-48 overflow-hidden'}`}>
                  {text.split(/\n\s*\n/).map((para, i) => <p key={i} className="mb-2">{para}</p>)}
                </div>
              </div>
            ))}
          </div>
          <button className="mt-1 min-h-10 text-sm underline" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? 'Show less' : 'Read all'}</button>
          {!p.voted && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Button onClick={() => vote(p.id, 'first')} disabled={act.busy}>Version 1 is better</Button>
              <Button onClick={() => vote(p.id, 'second')} disabled={act.busy}>Version 2 is better</Button>
              <Button onClick={() => vote(p.id, 'tie')} disabled={act.busy}>No difference</Button>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

export default function Experiments({ series, book, selected, onSelect }: { series: string; book: string; selected: string; onSelect: (n: string) => void }) {
  const list = useApi<ExperimentSummary[]>(`${bookPath(series, book)}/workbench/experiments`, 10000)
  if (list.error) return <ErrorBanner message={list.error} />
  if (!list.data) return <Loading />
  return (
    <div className="space-y-3">
      {!list.data.length && <Empty>No experiments yet. Edit a prompt on the Prompts tab and choose “A/B test this text”.</Empty>}
      <ul className="flex flex-wrap gap-2">
        {list.data.map((e) => (
          <li key={e.name}><button onClick={() => onSelect(e.name)} aria-current={selected === e.name}
            className={`min-h-11 rounded-md border px-3 text-left text-sm ${selected === e.name ? 'border-slate-900 bg-slate-50' : 'border-slate-300 bg-white'}`}>
            {e.template} · {fmtTime(e.created)}{e.promoted && ' · adopted'}</button></li>
        ))}
      </ul>
      {selected && <Experiment key={selected} series={series} book={book} name={selected} onChange={list.reload} />}
    </div>
  )
}
