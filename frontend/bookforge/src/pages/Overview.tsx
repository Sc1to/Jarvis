import { useState } from 'react'
import { bookPath, post } from '../lib/api'
import { useAction } from '../lib/hooks'
import type { BookStatus } from '../lib/types'
import { href } from '../lib/route'
import { Button, Card, Dot, ErrorBanner, StatusBadge, fmtTime } from '../components/ui'

// The files to read before approving each checkpoint: [document key, label]
const REVIEW: Record<string, [string, string][]> = {
  direction: [['series_north_star', 'Series north star'], ['book_north_star', 'Book north star'], ['synopsis', 'Synopsis']],
  structure: [['acts', 'Acts'], ['chapters', 'Chapters'], ['scenes', 'Scene plans'], ['constants', 'Cast'], ['tracks', 'State tracks'], ['timeline', 'Timeline']],
  voice: [['style_guide', 'Style guide']],
}

const LAYERS = ['series_north_star', 'book_north_star', 'synopsis', 'acts', 'chapters', 'scenes', 'prose']

export default function Overview({ series, book, status, reload }: { series: string; book: string; status: BookStatus; reload: () => void }) {
  const act = useAction()
  const [until, setUntil] = useState('')
  const base = bookPath(series, book)
  const busy = status.job?.status === 'running'
  const waiting = Object.entries(status.checkpoints).filter(([, v]) => v === 'waiting').map(([k]) => k)
  const s = status.scenes
  const total = s.total || 1

  const go = async (fn: () => Promise<unknown>) => { await act.run(fn); reload() }

  return (
    <div className="space-y-3">
      <ErrorBanner message={act.error} onClose={act.clear} />

      {status.job && (
        <Card title={`${status.job.kind} ${status.job.status}`} tone={busy ? undefined : 'warn'}>
          <p className="text-sm text-slate-700">Started {fmtTime(status.job.started)}. {busy && 'Updating every few seconds; the page can be closed, the run continues.'}</p>
        </Card>
      )}

      {waiting.map((cp) => (
        <Card key={cp} title={`The ${cp} checkpoint is waiting for you`} tone="warn">
          <p className="mb-2 text-sm text-slate-700">Read these, then approve to let the run continue.</p>
          <div className="mb-3 flex flex-wrap gap-2">
            {(REVIEW[cp] ?? []).map(([key, label]) => (
              <a key={key} href={href({ series, book, tab: 'documents', id: key })} className="inline-flex min-h-10 items-center rounded-md border border-slate-300 bg-white px-3 text-sm underline">{label}</a>
            ))}
            {cp === 'voice' && <a href={href({ series, book, tab: 'tree' })} className="inline-flex min-h-10 items-center rounded-md border border-slate-300 bg-white px-3 text-sm underline">Chapter 1 scenes (Progress)</a>}
            {cp === 'final' && <a href={href({ series, book, tab: 'read' })} className="inline-flex min-h-10 items-center rounded-md border border-slate-300 bg-white px-3 text-sm underline">The manuscript (Read)</a>}
          </div>
          <Button kind="primary" disabled={act.busy || busy}
            onClick={() => window.confirm(`Approve the ${cp} checkpoint?`) && go(() => post(`${base}/approve/${cp}`))}>Approve {cp}</Button>
        </Card>
      ))}

      <Card title="Run">
        <div className="flex flex-wrap items-center gap-2">
          <select value={until} onChange={(e) => setUntil(e.target.value)} className="min-h-10 rounded-md border border-slate-300 bg-white px-2 text-sm" aria-label="Stop after layer">
            <option value="">to the next checkpoint</option>
            {LAYERS.map((l) => <option key={l} value={l}>until {l.replace(/_/g, ' ')}</option>)}
          </select>
          <Button kind="primary" disabled={act.busy || busy} onClick={() => go(() => post(`${base}/run`, until ? { until } : {}))}>{busy ? 'Running…' : 'Run'}</Button>
          <Button disabled={act.busy || busy} title="Join the accepted scenes into one manuscript"
            onClick={() => go(() => post(`${base}/assemble`, {}))}>Assemble</Button>
        </div>
      </Card>

      <Card title="Scenes">
        <div className="flex h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden>
          {(['accepted', 'flagged', 'stale', 'drafted', 'checked'] as const).map((k) => (
            s[k] ? <div key={k} className={{ accepted: 'bg-emerald-500', flagged: 'bg-red-500', stale: 'bg-amber-500', drafted: 'bg-sky-400', checked: 'bg-sky-500' }[k]} style={{ width: `${(100 * s[k]) / total}%` }} /> : null
          ))}
        </div>
        <p className="mt-2 text-sm text-slate-700">
          {s.total ? ['accepted', 'flagged', 'stale', 'drafted', 'checked', 'pending'].filter((k) => s[k]).map((k) => `${s[k]} ${k}`).join(', ') : 'No scenes planned yet.'}
        </p>
        {status.pending_changes > 0 && <p className="mt-1 text-sm text-amber-800">{status.pending_changes} change request(s) waiting in the inbox.</p>}
      </Card>

      <Card title="Layers">
        <ul className="divide-y divide-slate-100">
          {status.layers.map((l) => (
            <li key={l.name} className="flex items-start gap-2 py-2">
              <div className="mt-1"><Dot status={l.status} /></div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{l.name.replace(/_/g, ' ')}</span>
                  <StatusBadge status={l.status} />
                  {l.checkpoint && <span className="text-xs text-slate-500">[{l.checkpoint}]</span>}
                </div>
                {l.note && <p className="mt-0.5 break-words text-xs text-slate-500">{l.note}</p>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
