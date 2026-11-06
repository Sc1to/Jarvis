import { bookPath, post } from '../lib/api'
import { useState } from 'react'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, ChangeRequest, Need, Stance, StaleReport } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, Markdown } from '../components/ui'

export function ChangeDiff({ cr, series, book, onDone, locked }: { cr: ChangeRequest; series: string; book: string; onDone: () => void; locked: boolean }) {
  const act = useAction()
  const base = `${bookPath(series, book)}/changes/${cr.id}`
  const decide = async (what: 'approve' | 'reject') => {
    const msg = what === 'approve' ? 'Change the plan to match the prose?' : 'Keep the plan? The scene will be patched to agree with it.'
    if (window.confirm(msg) && (await act.run(() => post(`${base}/${what}`)))) onDone()
  }
  return (
    <div className="space-y-2">
      <p className="text-sm"><a className="font-medium underline" href={href({ series, book, tab: 'scene', id: cr.proposed_by })}>{cr.proposed_by}</a>
        {' '}· {cr.entity || cr.track} · {cr.affects.length} scene(s) affected · {cr.scope === 'within_chapter' ? 'inside one chapter' : 'reaches later chapters'}</p>
      <div className="overflow-hidden rounded-md border border-slate-200 font-mono text-xs">
        <div className="whitespace-pre-wrap break-words bg-red-50 p-2 text-red-900">− plan: {cr.planned}</div>
        <div className="whitespace-pre-wrap break-words bg-emerald-50 p-2 text-emerald-900">+ prose: {cr.observed}</div>
      </div>
      {cr.evidence && <blockquote className="border-l-4 border-slate-300 pl-3 text-xs italic text-slate-600">“{cr.evidence}”</blockquote>}
      <ErrorBanner message={act.error} onClose={act.clear} />
      {cr.status === 'pending' ? (
        <div className="flex gap-2">
          <Button kind="primary" disabled={act.busy || locked} onClick={() => decide('approve')}>Approve (change the plan)</Button>
          <Button kind="danger" disabled={act.busy || locked} onClick={() => decide('reject')}>Reject (keep the plan)</Button>
        </div>
      ) : <p className="text-xs text-slate-500">{cr.status}{cr.decided_by ? ` by ${cr.decided_by}` : ''}{cr.fixed ? ', prose brought back in line' : ''}</p>}
    </div>
  )
}

const STANCES: { value: Stance; label: string; hint: string; field: string }[] = [
  { value: 'ground', label: 'Ground', hint: 'The real world must be right (looked up).', field: 'Note' },
  { value: 'extrapolate', label: 'Extrapolate', hint: 'A real basis, an imagined application.', field: 'What the story assumes' },
  { value: 'bend', label: 'Bend', hint: 'The truth is known and changed on purpose.', field: 'What changes, and why' },
  { value: 'invent', label: 'Invent', hint: 'Nothing real to look up: a rule of this world.', field: 'The rule' },
]

export function NeedDecision({ need, series, book, onDone, locked }: { need: Need; series: string; book: string; onDone: () => void; locked: boolean }) {
  const act = useAction()
  const [stance, setStance] = useState<Stance>(need.stance)
  const [rule, setRule] = useState(need.rule)
  const info = STANCES.find((x) => x.value === stance)!
  const changed = stance !== need.stance || rule !== need.rule
  const send = async (action?: 'approve' | 'reject') => {
    const body: Record<string, unknown> = {}
    if (action) body.action = action
    if (stance !== need.stance) body.stance = stance
    if (rule !== need.rule) body.rule = rule
    if (await act.run(() => post(`${bookPath(series, book)}/needs/${need.id}`, body))) onDone()
  }
  const needsRule = stance !== 'ground' && !rule.trim()
  return (
    <div className="space-y-2 rounded-md border border-slate-200 p-3">
      <p className="text-sm font-medium">{need.question}{need.sensitive && <span className="ml-1 text-xs font-normal text-amber-700">(sensitive: verify)</span>}</p>
      {need.reason && <p className="text-xs text-slate-600">Why: {need.reason}</p>}
      <label className="block text-xs font-medium text-slate-700">
        How to handle it
        <select value={stance} onChange={(e) => setStance(e.target.value as Stance)} disabled={act.busy || locked}
          className="mt-1 block min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm font-normal">
          {STANCES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
        </select>
        <span className="mt-1 block font-normal text-slate-600">{info.hint}</span>
      </label>
      <label className="block text-xs font-medium text-slate-700">
        {info.field}
        <textarea value={rule} onChange={(e) => setRule(e.target.value)} rows={3} disabled={act.busy || locked}
          className="mt-1 block w-full rounded-md border border-slate-300 p-2 text-sm font-normal" />
      </label>
      {need.fact_ids.length > 0 && <p className="text-xs text-slate-600">{need.fact_ids.length} researched fact(s) found for this ({need.fact_ids.join(', ')}); see the Research tab.</p>}
      {stance !== 'invent' && stance !== need.stance && !need.fact_ids.length && <p className="text-xs text-amber-800">Nothing is looked up when you change the handling here, so there are no facts for it yet.</p>}
      <ErrorBanner message={act.error} onClose={act.clear} />
      <div className="flex flex-wrap gap-2">
        <Button kind="primary" disabled={act.busy || locked || needsRule} onClick={() => send('approve')}>Approve{changed ? ' with my changes' : ''}</Button>
        <Button kind="danger" disabled={act.busy || locked} onClick={() => send('reject')}>Reject</Button>
        {changed && <Button disabled={act.busy || locked || needsRule} onClick={() => send()}>Save, decide later</Button>}
      </div>
    </div>
  )
}

export default function Inbox({ series, book, status, reload }: { series: string; book: string; status: BookStatus; reload: () => void }) {
  const base = bookPath(series, book)
  const report = useApi<{ markdown: string }>(`${base}/report`, status.job ? 10000 : undefined)
  const changes = useApi<ChangeRequest[]>(`${base}/changes`)
  const stale = useApi<StaleReport>(`${base}/stale`)
  const needs = useApi<Need[]>(`${base}/needs`)
  const fix = useAction()
  const locked = status.job?.status === 'running'
  const pending = changes.data?.filter((c) => c.status === 'pending') ?? []
  const rejectedOpen = changes.data?.filter((c) => c.status === 'rejected' && !c.fixed) ?? []
  const staleAny = (stale.data?.scenes.length ?? 0) > 0
  const waiting = needs.data?.filter((n) => n.status === 'proposed' && (n.rule || n.stance === 'invent')) ?? []
  const decided = needs.data?.filter((n) => n.decided_by === 'author') ?? []

  return (
    <div className="space-y-3">
      <Card title={`Decisions about the world (${waiting.length} waiting)`}>
        <p className="mb-2 text-xs text-slate-600">Rules, assumptions and deliberate changes the model proposes. Nothing here reaches the writer until you approve it.</p>
        {needs.error && <ErrorBanner message={needs.error} />}
        {!needs.data && <Loading />}
        {needs.data && !waiting.length && <Empty>Nothing to decide.</Empty>}
        <div className="space-y-3">
          {waiting.map((n) => (
            <NeedDecision key={`${n.id}:${n.stance}:${n.rule}`} need={n} series={series} book={book} locked={!!locked}
              onDone={() => { needs.reload(); stale.reload(); reload() }} />
          ))}
        </div>
        {decided.length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-slate-600">Decided by you ({decided.length})</summary>
            <ul className="mt-2 space-y-2">
              {decided.map((n) => (
                <li key={n.id} className="text-xs"><span className="font-medium">{n.status === 'approved' ? 'Approved' : 'Rejected'} · {n.stance}</span> · {n.question}
                  {n.rule && <span className="block text-slate-600">{n.rule}</span>}</li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      <Card title={`Change requests (${pending.length} waiting)`}>
        {changes.error && <ErrorBanner message={changes.error} />}
        {!changes.data && <Loading />}
        {changes.data && !pending.length && !rejectedOpen.length && <Empty>Nothing to decide.</Empty>}
        <div className="space-y-4">
          {[...pending, ...rejectedOpen].map((c) => (
            <ChangeDiff key={c.id} cr={c} series={series} book={book} locked={!!locked} onDone={() => { changes.reload(); stale.reload(); reload() }} />
          ))}
        </div>
      </Card>

      <Card title="Out of date" right={staleAny && (
        <Button kind="primary" disabled={fix.busy || !!locked} onClick={async () => { if (await fix.run(() => post(`${base}/stale/fix`, {}))) reload() }}>Fix all</Button>
      )}>
        <ErrorBanner message={fix.error} onClose={fix.clear} />
        {stale.error && <ErrorBanner message={stale.error} />}
        {!stale.data && <Loading />}
        {stale.data && !staleAny && !stale.data.plan.length && <Empty>Nothing is out of date.</Empty>}
        <ul className="space-y-2">
          {stale.data?.scenes.map((s) => (
            <li key={s.scene} className="text-sm">
              <a className="font-medium underline" href={href({ series, book, tab: 'scene', id: s.scene })}>{s.scene}</a>
              <span className="text-slate-500"> · start with {s.level}</span>
              <ul className="ml-4 list-disc text-xs text-slate-600">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </li>
          ))}
          {stale.data?.plan.map((p) => <li key={p.id} className="text-sm"><span className="font-medium">{p.id}</span> <span className="text-slate-600">plan out of date: {p.reason}</span></li>)}
        </ul>
      </Card>

      <Card title="Morning report" right={<Button onClick={report.reload}>Refresh</Button>}>
        {report.error && <ErrorBanner message={report.error} />}
        {!report.data ? <Loading /> : <Markdown text={report.data.markdown} />}
      </Card>
    </div>
  )
}
