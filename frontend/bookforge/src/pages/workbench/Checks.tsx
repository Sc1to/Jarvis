import { useState } from 'react'
import { bookPath, api } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import type { LedgerView, ValidationResult } from '../../lib/types'
import { Button, Card, ErrorBanner } from '../../components/ui'

const STAGES = ['ledger', 'acts', 'chapters', 'scenes', 'prose'] as const

/** What the validators found at each planning stage, and the ledger's open questions. Hard findings stop a stage; soft ones are for a look. */
export default function Checks({ series, book }: { series: string; book: string }) {
  const base = bookPath(series, book)
  const checks = useApi<ValidationResult>(`${base}/workbench/validation`)
  const ledger = useApi<LedgerView | null>(`${base}/workbench/ledger`)
  const [open, setOpen] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const act = useAction()
  const stages = checks.data?.stages
  const questions = ledger.data?.questions.filter((q) => q.status === 'open') ?? []

  return (
    <Card title="Stage checks">
      <ErrorBanner message={checks.error ?? act.error} />
      <ul className="divide-y divide-slate-100">
        {STAGES.map((st) => {
          const c = stages?.[st]
          const hard = c?.summary.hard ?? 0, soft = c?.summary.soft ?? 0
          return (
            <li key={st}>
              <button onClick={() => setOpen(open === st ? null : st)} aria-expanded={open === st} className="flex min-h-11 w-full items-center gap-2 py-2 text-left text-sm">
                <span className="w-20 shrink-0 capitalize">{st}</span>
                <span className={`rounded px-1.5 text-xs font-medium ${hard ? 'bg-red-100 text-red-800' : 'bg-emerald-100 text-emerald-800'}`}>{hard ? `${hard} hard` : 'clean'}</span>
                {soft > 0 && <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">{soft} soft</span>}
                {!c || (c.findings.length === 0 && !hard && !soft) ? <span className="text-xs text-slate-500">no findings saved</span> : null}
              </button>
              {open === st && c && (
                <ul className="mb-2 space-y-2 text-sm">
                  {st === 'ledger' && c.capacity?.estimated_chapters !== undefined && (
                    <li className="rounded-md bg-slate-50 p-2 text-xs">Capacity: {c.capacity.total_weight} weight / {c.capacity.weight_per_chapter} = {c.capacity.estimated_chapters} chapters (minimum {c.capacity.minimum_chapters}){c.capacity.thin ? ': thin' : ''}</li>
                  )}
                  {c.findings.length === 0 && <li className="text-slate-600">Nothing found.</li>}
                  {c.findings.map((f, i) => (
                    <li key={i} className={f.severity === 'hard' ? 'text-red-700' : 'text-amber-900'}>
                      <span className="font-medium">{f.code}</span> {f.items.length > 0 && <span className="text-xs">[{f.items.slice(0, 6).join(', ')}]</span>}
                      <span className="block break-words">{f.message}</span>
                      {f.evidence.map((e, j) => <span key={j} className="block break-words text-xs italic text-slate-600">“{e}”</span>)}
                      {f.severity === 'hard' && (
                        <span className="mt-1 block">
                          <Button disabled={act.busy} title="A false alarm? The finding stays in the report, marked accepted, and stops blocking this stage. Run again afterwards."
                            onClick={() => act.run(async () => { await api(`${base}/workbench/validation/accept`, { method: 'POST', body: { stage: st, code: f.code, items: f.items, message: f.message } }); checks.reload() })}>Accept this finding</Button>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      {(checks.data?.accepted?.length ?? 0) > 0 && (
        <div className="mt-3 space-y-2 border-t border-slate-200 pt-3">
          <h3 className="text-xs font-semibold uppercase text-slate-500">Findings you accepted</h3>
          <ul className="space-y-2 text-sm">
            {checks.data!.accepted!.map((a) => (
              <li key={a.fingerprint} className="flex items-start justify-between gap-2">
                <span className="min-w-0 break-words"><span className="font-medium">{a.code}</span> <span className="text-xs text-slate-600">[{a.items.slice(0, 4).join(', ')}] ({a.stage})</span></span>
                <Button disabled={act.busy} onClick={() => act.run(async () => { await api(`${base}/workbench/validation/unaccept`, { method: 'POST', body: { fingerprint: a.fingerprint } }); checks.reload() })}>Undo</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {questions.length > 0 && (
        <div className="mt-3 space-y-3 border-t border-slate-200 pt-3">
          <h3 className="text-xs font-semibold uppercase text-slate-500">Questions about the story's events</h3>
          {questions.map((q) => (
            <div key={q.id} className="space-y-1 text-sm">
              <p className="font-medium">{q.question}</p>
              <p className="text-xs text-slate-600">{q.why}</p>
              <ul className="list-disc pl-5 text-xs">{q.options.map((o) => <li key={o}><button className="text-left underline" onClick={() => setAnswers({ ...answers, [q.id]: o })}>{o}</button></li>)}</ul>
              <textarea value={answers[q.id] ?? ''} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} aria-label={`Answer to ${q.id}`} rows={2} className="w-full rounded-md border border-slate-300 p-2 text-sm" />
              <Button disabled={act.busy || !(answers[q.id] ?? '').trim()} onClick={() => act.run(async () => { await api(`${base}/workbench/ledger/questions/${q.id}/answer`, { method: 'POST', body: { answer: answers[q.id] } }); ledger.reload() })}>Save answer</Button>
            </div>
          ))}
          <p className="text-xs text-slate-600">Run the book again to revise the ledger from your answers.</p>
        </div>
      )}
    </Card>
  )
}
