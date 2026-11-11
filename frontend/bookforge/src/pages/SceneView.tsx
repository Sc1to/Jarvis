import { Fragment, useState, type ReactNode } from 'react'
import { bookPath, del, post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, CriticReview, FlagReason, SceneDetail, SceneFindings } from '../lib/types'
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

/** One finding of the continuity check, with what you can do about it. Applied the next time the scene is run. */
function FindingRow({ question, evidence, compared, tone, notes, scenePath, locked, onDone }: {
  question: string; evidence?: string; compared?: string; tone: 'flag' | 'unsure'; notes: SceneFindings; scenePath: string; locked: boolean; onDone: () => void
}) {
  const act = useAction()
  const [text, setText] = useState(notes.instructions[question] ?? '')
  const dismissed = notes.dismissed.includes(question)
  const instruction = notes.instructions[question]
  const send = async (action: 'dismiss' | 'instruct' | 'clear') => {
    if (await act.run(() => post(`${scenePath}/findings`, { question, action, text: action === 'instruct' ? text : '' }))) onDone()
  }
  return (
    <li className="space-y-2 rounded-md border border-slate-200 p-2">
      <p className={tone === 'flag' ? 'text-red-800' : 'text-slate-600'}>{tone === 'flag' ? 'Flag' : 'Unsure'}: {question}</p>
      {evidence && <blockquote className="border-l-4 border-slate-300 pl-2 text-xs italic text-slate-600">“{evidence}”</blockquote>}
      {compared && <p className="text-xs text-slate-600">{compared}</p>}
      {dismissed ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">Dismissed as a false alarm: not asked about again for this scene.
          <Button disabled={act.busy || locked} onClick={() => send('clear')}>Undo</Button></p>
      ) : (
        <>
          {instruction && <p className="text-xs text-emerald-800">Instruction saved: {instruction}</p>}
          <label className="block text-xs font-medium text-slate-700">What should the writer do about it?
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} disabled={act.busy || locked}
              placeholder="For example: keep the grey eyes, and say in the first line that she dyes them."
              className="mt-1 block w-full rounded-md border border-slate-300 p-2 text-sm font-normal" />
          </label>
          <ErrorBanner message={act.error} onClose={act.clear} />
          <div className="flex flex-wrap gap-2">
            <Button kind="primary" disabled={act.busy || locked || !text.trim() || text.trim() === instruction} onClick={() => send('instruct')}>Save instruction</Button>
            <Button disabled={act.busy || locked} onClick={() => send('dismiss')} title="The check is wrong here: do not ask about this again for this scene">False alarm</Button>
            {instruction && <Button disabled={act.busy || locked} onClick={() => { setText(''); void send('clear') }}>Remove instruction</Button>}
          </div>
        </>
      )}
    </li>
  )
}

const VERDICTS: Record<string, { label: string; cls: string }> = {
  shown: { label: 'shown', cls: 'bg-emerald-100 text-emerald-800' },
  thin: { label: 'thin', cls: 'bg-amber-100 text-amber-800' },
  missing: { label: 'missing', cls: 'bg-red-100 text-red-800' },
  out_of_order: { label: 'out of order', cls: 'bg-red-100 text-red-800' },
}

/** Every reason a scene is flagged, each with its own decision: accept it as it is, or leave it to be fixed. */
function ReasonsCard({ detail, scenePath, locked, onDone }: { detail: SceneDetail; scenePath: string; locked: boolean; onDone: () => void }) {
  const reasons = detail.reasons ?? []
  const [showText, setShowText] = useState(false)
  const review = detail.review
  if (!reasons.length) return null
  const evidence = (r: FlagReason) => review?.continuity?.flags.find((f) => `continuity:${f.question}` === r.key)
  const quotes = [
    ...(review?.critic?.weakest?.map((w) => w.quote) ?? []),
    ...reasons.filter((r) => r.kind === 'continuity').map((r) => evidence(r)?.evidence ?? '').filter(Boolean),
  ]
  const open = reasons.filter((r) => !r.accepted).length
  return (
    <Card title="Why this scene is flagged" tone="warn" right={<span className="text-xs text-slate-600">{open ? `${open} of ${reasons.length} still open` : 'all accepted'}</span>}>
      <div className="space-y-3">
        <p className="text-xs text-slate-600">Each reason is its own decision. Accepting one keeps the text as it is for that reason only; the others are still fixed or checked on the next Run. Once every reason is accepted, the scene turns green at once.</p>
        <ul className="space-y-2">{reasons.map((r) => <ReasonRow key={r.key} reason={r} found={evidence(r)} scenePath={scenePath} locked={locked || detail.status !== 'flagged'} onDone={onDone} />)}</ul>
        {!open && detail.status === 'flagged' && <p className="text-sm text-emerald-800">Every reason is accepted: the scene is finished and its text is kept as it is.</p>}
        <div className="space-y-2">
          <Button onClick={() => setShowText((v) => !v)}>{showText ? 'Hide the scene' : 'Read the scene with the quoted lines marked'}</Button>
          {showText && detail.text && <div className="rounded-md border border-slate-200 bg-white p-3"><Prose text={detail.text} quotes={quotes} /></div>}
          <p className="text-xs text-slate-600">The checks quote only a few lines. A low score or a finding can have causes they did not quote, so read the scene before accepting.</p>
        </div>
      </div>
    </Card>
  )
}

const KIND_LABEL: Record<string, string> = { mechanical: 'rule check', continuity: 'continuity', critic: 'critic' }

function ReasonRow({ reason, found, scenePath, locked, onDone }: {
  reason: FlagReason; found?: { evidence: string; fact_says?: string; text_says?: string }; scenePath: string; locked: boolean; onDone: () => void
}) {
  const act = useAction()
  const [note, setNote] = useState('')
  const send = async (accept: boolean) => {
    if (accept && !window.confirm(`Accept this reason?\n\n${reason.message}\n\nThe text is kept as it is.`)) return
    const ok = await act.run(() => (accept ? post(`${scenePath}/accept-reason`, { key: reason.key, note }) : del(`${scenePath}/accept-reason?key=${encodeURIComponent(reason.key)}`)))
    if (ok) onDone()
  }
  return (
    <li className="space-y-2 rounded-md border border-slate-200 bg-white p-2">
      <div className="flex flex-wrap items-start gap-2">
        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{KIND_LABEL[reason.kind] ?? reason.kind}</span>
        <p className="min-w-0 flex-1 text-sm [overflow-wrap:anywhere]">{reason.message}</p>
        {reason.accepted && <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">accepted</span>}
      </div>
      {found?.evidence && <blockquote className="border-l-4 border-slate-300 pl-2 text-xs italic text-slate-600">“{found.evidence}”</blockquote>}
      {found && (found.fact_says || found.text_says) && <p className="text-xs text-slate-600">Fact says: {found.fact_says || '—'} · Passage says: {found.text_says || '—'}</p>}
      <ErrorBanner message={act.error} onClose={act.clear} />
      {reason.accepted ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">{reason.note ? <>Your note: “{reason.note}”</> : 'Accepted as it is.'}
          <Button disabled={act.busy || locked} onClick={() => send(false)}>Take this back</Button></p>
      ) : (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-slate-700">Why is this fine as it is? (optional)
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} disabled={act.busy || locked}
              className="mt-1 block w-full rounded-md border border-slate-300 p-2 text-sm font-normal" />
          </label>
          <Button kind="primary" disabled={act.busy || locked} onClick={() => send(true)}>Accept this reason</Button>
        </div>
      )}
    </li>
  )
}

/** What the critic based its scores on: the evidence for a critic reason. */
function CriticEvidence({ detail }: { detail: SceneDetail }) {
  const review = detail.review
  const critic = review?.critic
  const minimum = detail.critic_min_score ?? 3
  if (!review || !critic || critic.error || !critic.scores) return null
  const low = Object.entries(critic.scores).filter(([, v]) => v < minimum).map(([c]) => c)
  if (!low.length) return null
  const label = (c: string) => c.replace(/_/g, ' ')
  const verdicts = new Map((critic.beats ?? []).map((b) => [b.beat, b]))
  const first: CriticReview | null | undefined = review.rewrote_with_critic_notes ? review.first_attempt_critic : null
  return (
    <Card title="The critic's evidence">
      <div className="space-y-4">
        <div>
          <Scores scores={critic.scores} />
          <p className="mt-2 text-sm text-amber-900">Minimum score is {minimum}. Below it: {low.map((c) => `${label(c)} (${critic.scores[c]})`).join(', ')}.</p>
          {first && <p className="mt-1 text-xs text-slate-600">This is the second attempt. Before the scene was written again the critic gave: {Object.entries(first.scores).map(([c, v]) => `${label(c)} ${v}`).join(', ')}.</p>}
        </div>
        {low.map((c) => detail.rubric?.[c] && (
          <p key={c} className="text-sm"><span className="font-medium">{label(c)} asks:</span> <span className="text-slate-700">{detail.rubric[c]}</span></p>
        ))}
        <div>
          <h3 className="mb-1 text-sm font-medium">The planned beats, and what the critic found for each</h3>
          <ol className="space-y-1.5 text-sm">
            {detail.plan.beats.map((b, i) => {
              const v = verdicts.get(i + 1)
              return (
                <li key={i} className="rounded-md border border-slate-200 bg-white p-2">
                  <div className="flex flex-wrap items-start gap-2">
                    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{i + 1}. {b}</span>
                    {v && <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${VERDICTS[v.verdict]?.cls ?? ''}`}>{VERDICTS[v.verdict]?.label ?? v.verdict}</span>}
                  </div>
                  {v?.note && <p className="mt-1 text-xs text-slate-600">{v.note}</p>}
                </li>
              )
            })}
          </ol>
          {!verdicts.size && <p className="mt-1 text-xs text-slate-500">The critic gave no verdict per beat for this attempt (it was reviewed before that was asked). Read the beats against the text.</p>}
        </div>
        <div className="space-y-2">
          <h3 className="text-sm font-medium">The lines the critic quoted</h3>
          {critic.weakest?.map((w, i) => (
            <blockquote key={i} className="border-l-4 border-amber-400 pl-3 text-sm">
              <span className="italic">“{w.quote}”</span>
              <span className="mt-0.5 block text-xs text-slate-700">{label(w.criterion)}: {w.issue}</span>
            </blockquote>
          ))}
        </div>
      </div>
    </Card>
  )
}

function ReviewPanel({ detail, scenePath, locked, onDone }: { detail: SceneDetail; scenePath: string; locked: boolean; onDone: () => void }) {
  const review = detail.review
  const findings: SceneFindings = detail.findings ?? { dismissed: [], instructions: {} }
  if (!review) return <Empty>No review yet: this scene has not been written.</Empty>
  return (
    <div className="space-y-3">
      {review.blocking?.length && !detail.reasons?.length ? (
        <Card title="Needs you" tone="warn"><ul className="list-disc space-y-1 pl-5 text-sm">{review.blocking.map((b) => <li key={b}>{b}</li>)}</ul></Card>
      ) : null}
      <ReasonsCard detail={detail} scenePath={scenePath} locked={locked} onDone={onDone} />
      <CriticEvidence detail={detail} />
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
          {(review.continuity.flags.length > 0 || review.continuity.unsure.length > 0) && (
            <p className="mb-2 text-xs text-slate-600">What you say here is used the next time you press Run: the flagged scene is first revised with it, and a finding you call a false alarm is not asked about again for this scene.</p>
          )}
          <ul className="space-y-2 text-sm">
            {review.continuity.flags.map((f) => <FindingRow key={f.question} question={f.question} evidence={f.evidence} compared={f.fact_says || f.text_says ? `Fact says: ${f.fact_says || '—'} · Passage says: ${f.text_says || '—'}` : undefined} tone="flag" notes={findings} scenePath={scenePath} locked={locked} onDone={onDone} />)}
            {review.continuity.unsure.map((u) => <FindingRow key={u.question} question={`${u.question}`} evidence={u.evidence} compared={u.confirmed === false ? `Second check did not confirm. Fact says: ${u.fact_says || '—'} · Passage says: ${u.text_says || '—'}` : undefined} tone="unsure" notes={findings} scenePath={scenePath} locked={locked} onDone={onDone} />)}
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
  const [view, setView] = useState<'text' | 'compare' | 'review' | 'plan' | null>(null)
  const accept = useAction()
  if (d.error) return <div className="space-y-3"><ErrorBanner message={d.error} /><a className="text-sm underline" href={href({ series, book, tab: 'tree' })}>Back to the tree</a></div>
  if (!d.data) return <Loading />
  const x = d.data
  const current = view ?? (x.status === 'flagged' ? 'review' : 'text') // a flagged scene opens on why it was flagged
  const views: ['text' | 'compare' | 'review' | 'plan', string][] = [['text', 'Text'], ['compare', 'Compare'], ['review', 'Review'], ['plan', 'Plan']]
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
          <button key={k} role="tab" aria-selected={current === k} onClick={() => setView(k)}
            className={`min-h-10 shrink-0 rounded-md px-3 text-sm ${current === k ? 'bg-slate-900 text-white' : 'border border-slate-300 bg-white'}`}>{label}</button>
        ))}
      </div>
      {current === 'text' && (
        <div className="space-y-3">
          {x.text ? <Card><Prose text={x.text} /></Card> : <Empty>This scene has not been written yet.</Empty>}
          {x.summary && <Card title="Summary used for later scenes"><p className="text-sm text-slate-700">{x.summary}</p></Card>}
        </div>
      )}
      {current === 'compare' && <Compare detail={x} />}
      {current === 'review' && <ReviewPanel detail={x} scenePath={`${base}/scenes/${encodeURIComponent(id)}`} locked={status.job?.status === 'running'} onDone={d.reload} />}
      {current === 'plan' && (
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
      {x.status === 'stale' && (
        <Card title="Out of date" tone="warn">
          <p className="mb-2 text-sm text-slate-700">Something this scene was built from has changed. If the text is still fine, keep it as it is.</p>
          <ErrorBanner message={accept.error} onClose={accept.clear} />
          <Button kind="primary" disabled={accept.busy || status.job?.status === 'running'}
            onClick={async () => { if (window.confirm('Accept this scene as it is?') && await accept.run(() => post(`${base}/scenes/${encodeURIComponent(id)}/accept-stale`))) { d.reload(); reload() } }}>Accept as is</Button>
        </Card>
      )}
      {current !== 'plan' && <Button onClick={d.reload}>Refresh</Button>}
    </div>
  )
}
