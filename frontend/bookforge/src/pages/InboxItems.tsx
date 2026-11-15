import { useState } from 'react'
import { bookPath, post } from '../lib/api'
import { useAction, useApi, useJob } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, InboxItem, InboxView } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading } from '../components/ui'

const STAGE_LABEL: Record<string, string> = { ledger: 'Story events (ledger)', acts: 'Acts', chapters: 'Chapters', scenes: 'Scenes', prose: 'Prose' }
const STAGE_ORDER = ['ledger', 'acts', 'chapters', 'scenes', 'prose']
// the stages whose open items approving a checkpoint as it is would skip (mirrors bookforge/inbox.py)
export const CHECKPOINT_STAGES: Record<string, string[]> = { ledger: ['ledger'], structure: ['acts', 'chapters', 'scenes'], voice: ['prose'], final: ['prose'] }

const STATUS_STYLE: Record<string, string> = {
  open: 'bg-amber-100 text-amber-900', answered: 'bg-sky-100 text-sky-800', applied: 'bg-emerald-100 text-emerald-800', dismissed: 'bg-slate-100 text-slate-600',
}
const STATUS_LABEL: Record<string, string> = { open: 'open', answered: 'answered, waits for the next run', applied: 'applied', dismissed: 'dismissed' }

/** One question or finding: its words, the quoted sentences, one-tap answers, a text box you can edit, Answer / Dismiss / Edit. */
function ItemCard({ item, base, locked, onDone }: { item: InboxItem; base: string; locked: boolean; onDone: () => void }) {
  const act = useAction()
  const [text, setText] = useState(item.answer)
  const [editing, setEditing] = useState(false)
  const [dismissing, setDismissing] = useState(false)
  const [reason, setReason] = useState('')
  const open = item.status === 'open'
  const canEdit = item.status === 'answered' || (item.status === 'dismissed' && item.kind === 'question')
  const showForm = open || editing
  const send = async () => { if (await act.run(() => post(`${base}/inbox/answer`, { id: item.id, answer: text.trim() }))) { setEditing(false); onDone() } }
  const dismiss = async () => { if (await act.run(() => post(`${base}/inbox/dismiss`, { id: item.id, reason: reason.trim() }))) { setDismissing(false); setReason(''); onDone() } }
  return (
    <li className={`space-y-2 rounded-md border p-3 ${item.blocking ? 'border-red-300 bg-red-50/40' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {item.blocking && <span className="rounded-full bg-red-600 px-2 py-0.5 font-medium text-white">blocking</span>}
        <span className={`rounded-full px-2 py-0.5 ${STATUS_STYLE[item.status]}`}>{STATUS_LABEL[item.status]}</span>
        <span className="text-slate-500">{item.type.replace(/_/g, ' ')}{item.kind === 'finding' ? ' · check' : ''}</span>
      </div>
      <p className="break-words text-sm font-medium">{item.title}</p>
      {item.why && <p className="text-xs text-slate-600">{item.why}</p>}
      {item.quotes.map((q, i) => <blockquote key={i} className="break-words border-l-4 border-slate-300 pl-3 text-xs italic text-slate-700">“{q}”</blockquote>)}
      {item.items.length > 0 && <p className="break-words text-xs text-slate-500">{item.items.slice(0, 6).join(', ')}</p>}
      {!showForm && item.status === 'answered' && <p className="whitespace-pre-wrap break-words rounded-md bg-sky-50 p-2 text-sm">{item.answer}</p>}
      {!showForm && item.status === 'applied' && <p className="whitespace-pre-wrap break-words text-xs text-slate-600">Your answer: {item.answer}</p>}
      {!showForm && item.status === 'dismissed' && item.dismiss_reason && <p className="break-words text-xs text-slate-600">Reason: {item.dismiss_reason}</p>}
      {item.proposal && showForm && (
        <div className="space-y-2 rounded-md border border-violet-200 bg-violet-50/60 p-2">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="rounded-full bg-violet-600 px-2 py-0.5 font-medium text-white">the tool suggests</span>
            <span className="rounded-full bg-white px-2 py-0.5 text-violet-900">{item.proposal.label}</span>
            <span className="text-slate-500">{item.proposal.mode === 'shadow' ? 'suggestion only: nothing is applied' : item.proposal.applied ? 'applied by the tool' : item.proposal.mode}</span>
          </div>
          <p className="break-words text-sm">{item.proposal.answer}</p>
          {item.proposal.rationale && <p className="break-words text-xs text-slate-600">{item.proposal.rationale}</p>}
          {item.proposal.sources.map((src, i) => <blockquote key={i} className="break-words border-l-4 border-violet-300 pl-3 text-xs italic text-slate-700">“{src.quote}” <a className="not-italic underline" href={src.url}>source</a></blockquote>)}
          <button type="button" disabled={act.busy || locked} onClick={() => setText(item.proposal!.answer)}
            className="min-h-11 rounded-md border border-violet-300 bg-white px-3 py-2 text-left text-sm font-medium active:bg-violet-100 disabled:opacity-50">Use suggestion</button>
        </div>
      )}
      {showForm && (
        <div className="space-y-2">
          {item.options.length > 0 && (
            <div className="flex flex-col gap-2">
              {item.options.map((o) => (
                <button key={o} type="button" disabled={act.busy || locked} onClick={() => setText(o)}
                  className="min-h-11 rounded-md border border-slate-300 bg-white px-3 py-2 text-left text-sm active:bg-slate-100 disabled:opacity-50">{o}</button>
              ))}
            </div>
          )}
          <label className="block text-xs font-medium text-slate-700">
            {item.kind === 'finding' ? 'Your instruction for the next run' : 'Your answer'}
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} disabled={act.busy || locked}
              placeholder={item.options.length ? 'Tap an option above, or write your own' : 'Write your answer'}
              className="mt-1 block w-full rounded-md border border-slate-300 p-2 text-sm font-normal" />
          </label>
        </div>
      )}
      <ErrorBanner message={act.error} onClose={act.clear} />
      {dismissing && (
        <div className="space-y-2 rounded-md border border-slate-200 p-2">
          <label className="block text-xs font-medium text-slate-700">Why? (optional, kept with it)
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} className="mt-1 block min-h-11 w-full rounded-md border border-slate-300 px-2 text-sm font-normal" />
          </label>
          <div className="flex gap-2"><Button kind="danger" disabled={act.busy || locked} onClick={dismiss}>Dismiss</Button><Button onClick={() => setDismissing(false)}>Cancel</Button></div>
        </div>
      )}
      {!dismissing && (
        <div className="flex flex-wrap gap-2">
          {showForm && <Button kind="primary" disabled={act.busy || locked || !text.trim()} onClick={send}>{editing ? 'Save answer' : 'Answer'}</Button>}
          {editing && <Button onClick={() => { setEditing(false); setText(item.answer) }}>Cancel</Button>}
          {canEdit && !editing && <Button disabled={locked} onClick={() => { setText(item.answer); setEditing(true) }}>Edit answer</Button>}
          {(open || item.status === 'answered') && !editing && <Button disabled={act.busy || locked} onClick={() => setDismissing(true)}>Dismiss…</Button>}
        </div>
      )}
    </li>
  )
}

/** Everything that stops a stage and waits for you, for any stage, blocking first. */
export default function InboxItems({ series, book, status, reload }: { series: string; book: string; status: BookStatus; reload: () => void }) {
  const base = bookPath(series, book)
  const inbox = useApi<InboxView>(`${base}/inbox`, status.job ? 5000 : undefined)
  const run = useJob(base)
  const skip = useAction()
  const propose = useJob(base)
  const locked = status.job?.status === 'running' || run.busy
  const done = () => { inbox.reload(); reload() }
  const view = inbox.data
  const items = view?.items ?? []
  const active = items.filter((i) => i.status === 'open' || i.status === 'answered')
  const handled = items.filter((i) => i.status === 'applied' || i.status === 'dismissed')
  const groups = STAGE_ORDER.map((st) => ({ stage: st, items: active.filter((i) => i.stage === st) })).filter((g) => g.items.length)
  const blocking = view?.summary.blocking ?? 0
  const canRun = !!view && blocking === 0 && view.summary.answered_waiting > 0
  const lr = view?.last_run
  const runAgain = async () => { await run.run('/run', {}); done() }
  const getSuggestions = async () => { await propose.run('/inbox/propose', {}); done() }
  const withoutProposal = active.filter((i) => i.status === 'open' && !i.proposal).length
  const waitingCheckpoints = Object.entries(CHECKPOINT_STAGES).filter(([cp, stages]) => status.checkpoints[cp] === 'waiting' && active.some((i) => stages.includes(i.stage) && i.status === 'open'))
  const approveAnyway = async (cp: string) => {
    const skipped = active.filter((i) => i.status === 'open' && CHECKPOINT_STAGES[cp].includes(i.stage))
    const list = skipped.map((i) => `• ${STAGE_LABEL[i.stage] ?? i.stage}: ${i.title.slice(0, 110)}`).join('\n')
    if (window.confirm(`Approve the ${cp} checkpoint WITHOUT answering these ${skipped.length} open item(s)?\n\n${list}\n\nThey are dismissed and the next stages are built on things as they are.`) && (await skip.run(() => post(`${base}/approve/${cp}`, { skip_open: true })))) done()
  }

  return (
    <Card title={`Questions and findings (${blocking ? blocking + ' blocking, ' : ''}${active.length} open)`}>
      <p className="mb-2 text-xs text-slate-600">What stopped a stage and needs your word. Tap a suggested answer or write your own, then run again.</p>
      {inbox.error && <ErrorBanner message={inbox.error} />}
      {!view && <Loading />}
      {view && !active.length && <Empty>Nothing is waiting for an answer.</Empty>}
      <div className="space-y-4">
        {groups.map((g) => (
          <section key={g.stage} aria-label={STAGE_LABEL[g.stage] ?? g.stage} className="space-y-2">
            <h3 className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase text-slate-500">
              <span className="normal-case">{series} / {book} · {STAGE_LABEL[g.stage] ?? g.stage}</span>
              {g.items.some((i) => i.blocking) && <span className="rounded-full bg-red-600 px-2 py-0.5 normal-case text-white">{g.items.filter((i) => i.blocking).length} blocking</span>}
            </h3>
            <ul className="space-y-3">{g.items.map((it) => <ItemCard key={`${it.id}:${it.status}:${it.answer}`} item={it} base={base} locked={!!locked} onDone={done} />)}</ul>
          </section>
        ))}
      </div>
      {view && withoutProposal > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button disabled={!!locked || propose.busy} onClick={getSuggestions}>{propose.busy ? 'Working out suggestions…' : 'Get suggestions from the tool'}</Button>
          <span className="text-xs text-slate-600">It suggests an answer for {withoutProposal} item(s); nothing is applied.</span>
        </div>
      )}
      <ErrorBanner message={propose.error} onClose={propose.reset} />
      <ErrorBanner message={run.error} onClose={run.reset} />
      <ErrorBanner message={skip.error} onClose={skip.clear} />
      {canRun && (
        <div className="mt-3 rounded-md border border-sky-300 bg-sky-50 p-3">
          <p className="mb-2 text-sm">{view!.summary.answered_waiting} answer(s) wait for a run. Running again works them into the ledger and checks it once more.</p>
          <Button kind="primary" disabled={!!locked} onClick={runAgain}>{run.busy ? 'Running…' : 'Run again'}</Button>
        </div>
      )}
      {blocking > 0 && view!.summary.answered_waiting > 0 && <p className="mt-2 text-xs text-slate-600">Answer or dismiss every blocking item to run again.</p>}
      {run.result && <p className="mt-2 text-xs text-slate-700">Run finished: {String((run.result as any).stopped ?? 'done')}{(run.result as any).detail ? ' · ' + String((run.result as any).detail).split('\n')[0] : ''}</p>}
      {waitingCheckpoints.map(([cp]) => (
        <p key={cp} className="mt-3 text-xs text-slate-600">
          The {cp} checkpoint is waiting. <button type="button" className="min-h-11 underline" disabled={!!locked || skip.busy} onClick={() => approveAnyway(cp)}>Skip these and approve anyway…</button>
        </p>
      ))}
      {lr && lr.at && (
        <div className="mt-4 space-y-1 border-t border-slate-200 pt-3 text-sm">
          <h3 className="text-xs font-semibold uppercase text-slate-500">What the last run changed</h3>
          <p className="text-xs text-slate-600">{lr.kind === 'revise' ? `Revised the ledger from your answers (revision ${lr.revision})` : lr.kind === 'extract' ? `Extracted the ledger from the synopsis (${lr.events} events)` : 'Audited the synopsis again'}
            {lr.applied?.length ? ` · applied ${lr.applied.join(', ')}` : ''}</p>
          {(lr.added?.length ?? 0) > 0 && (
            <ul className="space-y-1 text-xs">{lr.added!.filter((e) => lr.kind === 'revise' || e.source === 'author').map((e) => <li key={e.id} className="break-words"><span className="font-medium text-emerald-800">+ {e.id}</span> ({e.source}) {e.text}</li>)}</ul>
          )}
          {(lr.revised?.length ?? 0) > 0 && (
            <ul className="space-y-1 text-xs">{lr.revised!.map((e) => <li key={e.id} className="break-words"><span className="font-medium text-amber-800">~ {e.id}</span> {e.before} → {e.after}</li>)}</ul>
          )}
          {(lr.new_questions?.length ?? 0) > 0 && <p className="text-xs text-amber-900">{lr.new_questions!.length} new item(s) above: {lr.new_questions!.join(', ')}.</p>}
          <p className="text-xs"><a className="underline" href={href({ series, book, tab: 'documents', id: 'ledger' })}>Open the ledger</a></p>
        </div>
      )}
      {handled.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="min-h-11 cursor-pointer py-2 text-slate-600">Handled ({handled.length})</summary>
          <ul className="space-y-3">{handled.map((it) => <ItemCard key={`${it.id}:${it.status}`} item={it} base={base} locked={!!locked} onDone={done} />)}</ul>
        </details>
      )}
    </Card>
  )
}
