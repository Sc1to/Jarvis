import { bookPath, post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, ChangeRequest, StaleReport } from '../lib/types'
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

export default function Inbox({ series, book, status, reload }: { series: string; book: string; status: BookStatus; reload: () => void }) {
  const base = bookPath(series, book)
  const report = useApi<{ markdown: string }>(`${base}/report`, status.job ? 10000 : undefined)
  const changes = useApi<ChangeRequest[]>(`${base}/changes`)
  const stale = useApi<StaleReport>(`${base}/stale`)
  const fix = useAction()
  const locked = status.job?.status === 'running'
  const pending = changes.data?.filter((c) => c.status === 'pending') ?? []
  const rejectedOpen = changes.data?.filter((c) => c.status === 'rejected' && !c.fixed) ?? []
  const staleAny = (stale.data?.scenes.length ?? 0) > 0

  return (
    <div className="space-y-3">
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
