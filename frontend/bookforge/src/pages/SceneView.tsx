import { Fragment, useState, type ReactNode } from 'react'
import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, Review, SceneDetail } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, StatusBadge } from '../components/ui'
import { ChangeDiff } from './Inbox'

/** The text with each quotation marked. Whitespace differences between the quote and the text are ignored. */
export function highlight(text: string, quotes: string[]): ReactNode[] {
  const escaped = quotes.map((q) => q.trim().split(/\s+/).filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')).filter(Boolean)
  if (!escaped.length) return [text]
  const rx = new RegExp(`(${escaped.join('|')})`, 'g')
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(rx)) {
    if (m.index! > last) out.push(text.slice(last, m.index))
    out.push(<mark key={m.index} className="rounded bg-amber-200 px-0.5">{m[0]}</mark>)
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function Prose({ text, quotes = [] }: { text: string; quotes?: string[] }) {
  return (
    <div className="space-y-3 font-serif text-[15px] leading-relaxed text-slate-900 [overflow-wrap:anywhere]">
      {text.split(/\n\s*\n/).map((p, i) => <p key={i}>{highlight(p, quotes)}</p>)}
    </div>
  )
}

function Scores({ scores }: { scores: Record<string, number> }) {
  return (
    <ul className="space-y-1.5">
      {Object.entries(scores).map(([k, v]) => (
        <li key={k} className="flex items-center gap-2 text-sm">
          <span className="w-32 shrink-0 text-slate-600">{k.replace(/_/g, ' ')}</span>
          <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" aria-hidden>
            <span className={`block h-full ${v <= 2 ? 'bg-red-500' : v === 3 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${v * 20}%` }} />
          </span>
          <span className="w-4 text-right tabular-nums">{v}</span>
        </li>
      ))}
    </ul>
  )
}

function Compare({ detail }: { detail: SceneDetail }) {
  const review = detail.review
  const names = Object.keys(detail.drafts)
  const quotes = review?.critic?.weakest?.map((w) => w.quote) ?? []
  if (!names.length) return <Empty>This scene has no drafts on disk (its text may be your own).</Empty>
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {names.map((n) => {
          const mech = review?.mechanical?.[n]
          const chosen = review?.chosen === n
          return (
            <Card key={n} title={<span className="flex items-center gap-2">{n}{chosen && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">chosen</span>}</span>}
              right={mech && <span className="text-xs text-slate-500">mechanical score {mech.score}</span>}>
              <Prose text={detail.drafts[n]} quotes={chosen ? quotes : []} />
            </Card>
          )
        })}
      </div>
      <Card title="The judge">
        {!review?.judge ? <p className="text-sm text-slate-500">No judgment: there was only one draft to choose from, or the judge is switched off.</p> : (
          <div className="space-y-1 text-sm">
            <p>Wins: {Object.entries(review.judge.wins).map(([k, v]) => `${k} ${v}`).join(', ')}</p>
            {review.judge.pairs.map((p) => (
              <p key={`${p.a}${p.b}`} className="text-slate-600">
                {p.a} against {p.b}: first reading chose {p.run1}, order swapped chose {p.run2} → {p.winner ? `${p.winner} wins` : 'a tie'}
              </p>
            ))}
            {review.judge.error && <p className="text-red-700">The judge failed ({review.judge.error}); the mechanical score decided.</p>}
          </div>
        )}
      </Card>
      <Card title="The critic">
        {!review?.critic ? <p className="text-sm text-slate-500">The critic did not run on this scene.</p> : review.critic.error ? <p className="text-sm text-red-700">{review.critic.error}</p> : (
          <div className="space-y-3">
            <Scores scores={review.critic.scores} />
            {review.critic.weakest?.map((w, i) => (
              <blockquote key={i} className="border-l-4 border-amber-400 pl-3 text-sm">
                <span className="italic">“{w.quote}”</span>
                <span className="mt-0.5 block text-xs text-slate-600">{w.criterion.replace(/_/g, ' ')}: {w.issue}</span>
              </blockquote>
            ))}
            <p className="text-xs text-slate-500">The weakest lines are marked in the chosen draft.</p>
          </div>
        )}
      </Card>
    </div>
  )
}

function ReviewPanel({ review }: { review: Review | null }) {
  if (!review) return <Empty>No review yet: this scene has not been written.</Empty>
  return (
    <div className="space-y-3">
      {review.blocking?.length ? (
        <Card title="Needs you" tone="warn"><ul className="list-disc space-y-1 pl-5 text-sm">{review.blocking.map((b) => <li key={b}>{b}</li>)}</ul></Card>
      ) : null}
      {review.rounds?.length ? (
        <Card title="Revision rounds">
          <ul className="space-y-3 text-sm">
            {review.rounds.map((r) => (
              <li key={r.round}>
                <p className="font-medium">Round {r.round}: {r.mechanical_blocking.length} blocking, {r.continuity_flags.length} continuity flag(s), critic lowest {r.critic_lowest ?? '–'}</p>
                {r.revisions.map((v, i) => (
                  <div key={i} className="mt-1 overflow-hidden rounded-md border border-slate-200 text-xs">
                    <p className="whitespace-pre-wrap break-words bg-red-50 p-2 text-red-900">− {v.before}</p>
                    {v.after && <p className="whitespace-pre-wrap break-words bg-emerald-50 p-2 text-emerald-900">+ {v.after}</p>}
                    {!v.after && <p className="bg-slate-50 p-2 text-slate-600">(line deleted)</p>}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {review.continuity && (
        <Card title={`Continuity (${review.continuity.questions} questions)`}>
          {!review.continuity.flags.length && !review.continuity.unsure.length && <p className="text-sm text-slate-500">All answers were clear.</p>}
          <ul className="space-y-1 text-sm">
            {review.continuity.flags.map((f) => <li key={f.question} className="text-red-800">Flag: {f.question}</li>)}
            {review.continuity.unsure.map((u) => <li key={u.question} className="text-slate-600">Unsure ({u.answer}, {u.confidence}): {u.question}</li>)}
          </ul>
        </Card>
      )}
      {review.extraction?.gaps?.length ? (
        <Card title="Where the prose differs from the plan">
          <ul className="space-y-1 text-sm">{review.extraction.gaps.map((g) => <li key={g.track}><span className="font-medium">{g.track}</span>: planned “{g.planned}”, the scene shows “{g.observed}”</li>)}</ul>
        </Card>
      ) : null}
      {review.stale_fixes?.length ? (
        <Card title="Fixed after a change"><ul className="space-y-1 text-sm">{review.stale_fixes.map((f) => <li key={f.at}>{f.action}: {f.why}</li>)}</ul></Card>
      ) : null}
    </div>
  )
}

export default function SceneView({ series, book, id, status, reload }: { series: string; book: string; id: string; status: BookStatus; reload: () => void }) {
  const base = bookPath(series, book)
  const d = useApi<SceneDetail>(`${base}/scenes/${encodeURIComponent(id)}`)
  const [view, setView] = useState<'text' | 'compare' | 'review' | 'plan'>('text')
  if (d.error) return <div className="space-y-3"><ErrorBanner message={d.error} /><a className="text-sm underline" href={href({ series, book, tab: 'tree' })}>Back to the tree</a></div>
  if (!d.data) return <Loading />
  const x = d.data
  const views: [typeof view, string][] = [['text', 'Text'], ['compare', 'Compare'], ['review', 'Review'], ['plan', 'Plan']]
  return (
    <div className="space-y-3">
      <div>
        <a className="text-sm text-slate-600 underline" href={href({ series, book, tab: 'tree' })}>← Progress tree</a>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold">{id}</h1><StatusBadge status={x.status} />
          <span className="text-xs text-slate-500">version {x.version}</span>
        </div>
        {x.note && x.status !== 'accepted' && <p className="mt-1 break-words text-sm text-amber-800">{x.note}</p>}
      </div>
      <div role="tablist" className="flex gap-1 overflow-x-auto">
        {views.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
            className={`min-h-10 shrink-0 rounded-md px-3 text-sm ${view === k ? 'bg-slate-900 text-white' : 'border border-slate-300 bg-white'}`}>{label}</button>
        ))}
      </div>
      {view === 'text' && (
        <div className="space-y-3">
          {x.text ? <Card><Prose text={x.text} /></Card> : <Empty>This scene has not been written yet.</Empty>}
          {x.summary && <Card title="Summary used for later scenes"><p className="text-sm text-slate-700">{x.summary}</p></Card>}
        </div>
      )}
      {view === 'compare' && <Compare detail={x} />}
      {view === 'review' && <ReviewPanel review={x.review} />}
      {view === 'plan' && (
        <div className="space-y-3">
          <Card title="Plan">
            <p className="text-sm">{x.plan.purpose}</p>
            <p className="mt-2 text-xs text-slate-500">Viewpoint {x.plan.pov} · setting {x.plan.setting} · present: {x.plan.characters.join(', ')}</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">{x.plan.beats.map((b, i) => <Fragment key={i}><li>{b}</li></Fragment>)}</ol>
          </Card>
          {x.change_requests.length > 0 && (
            <Card title="Change requests from this scene">
              <div className="space-y-4">{x.change_requests.map((c) => (
                <ChangeDiff key={c.id} cr={c} series={series} book={book} locked={status.job?.status === 'running'} onDone={() => { d.reload(); reload() }} />
              ))}</div>
            </Card>
          )}
        </div>
      )}
      {view !== 'plan' && <Button onClick={d.reload}>Refresh</Button>}
    </div>
  )
}
