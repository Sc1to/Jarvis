import { useEffect, useRef, useState } from 'react'
import { api, bookPath, post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import type { BookStatus, JobActivity, SceneRow } from '../lib/types'
import { href } from '../lib/route'
import { Button, Card, Dot, ErrorBanner, StatusBadge, fmtTime } from '../components/ui'

// The files to read before approving each checkpoint: [document key, label]
const REVIEW: Record<string, [string, string][]> = {
  direction: [['series_north_star', 'Series north star'], ['book_north_star', 'Book north star'], ['synopsis', 'Synopsis'], ['style_guide', 'Style guide (suggested)']],
  ledger: [['ledger', 'Story events'], ['synopsis', 'Synopsis']],
  structure: [['ledger', 'Story events'], ['acts', 'Acts'], ['chapters', 'Chapters'], ['scenes', 'Scene plans'], ['constants', 'Cast'], ['tracks', 'State tracks'], ['timeline', 'Timeline']],
  voice: [['style_guide', 'Style guide']],
}

const LAYERS = ['series_north_star', 'book_north_star', 'synopsis', 'ledger', 'acts', 'chapters', 'scenes', 'prose']

/** Write a planning layer again, optionally with a note on what to change. Nothing is deleted: the current files are committed first. */
function RedoPanel({ base, layer, onDone, onClose, locked }: { base: string; layer: string; onDone: () => void; onClose: () => void; locked: boolean }) {
  const plan = useApi<{ also_resets: string[] }>(`${base}/redo/${layer}`)
  const act = useAction()
  const [note, setNote] = useState('')
  const [cascade, setCascade] = useState(false)
  const also = plan.data?.also_resets ?? []
  const label = (l: string) => l.replace(/_/g, ' ')
  return (
    <div className="mt-2 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-sm text-slate-700">Write <strong>{label(layer)}</strong> again. What is there now is committed first, so it stays in the series history.</p>
      {plan.error && <ErrorBanner message={plan.error} />}
      {also.length > 0 && (
        <label className="flex items-start gap-2 text-sm text-slate-800">
          <input type="checkbox" checked={cascade} onChange={(e) => setCascade(e.target.checked)} className="mt-0.5 h-4 w-4" />
          <span>Also write again what was built on it: <strong>{also.map(label).join(', ')}</strong>.</span>
        </label>
      )}
      <p className="text-xs text-slate-600">The research those layers gathered (questions, facts, undecided decisions) is moved to the archive folder, not deleted, so they research from scratch. Decisions you made yourself stay.</p>
      <label className="block text-sm text-slate-700">What should change? (optional)
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="For example: darker, and keep Anna's job as a customs clerk."
          className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 text-sm" />
      </label>
      <ErrorBanner message={act.error} onClose={act.clear} />
      <div className="flex flex-wrap gap-2">
        <Button kind="primary" disabled={act.busy || locked || !plan.data || (also.length > 0 && !cascade)}
          onClick={async () => { if (await act.run(() => post(`${base}/redo`, { layer, note, cascade }))) { onDone(); onClose() } }}>Reset it, then press Run</Button>
        <Button disabled={act.busy} onClick={onClose}>Cancel</Button>
      </div>
    </div>
  )
}

const seconds = (ms: number) => Math.max(0, Math.round(ms / 1000))
const label = (s?: string | null) => (s ?? '').replace(/_/g, ' ')
const tokenLine = (a: JobActivity) => (a.prompt_tokens || a.completion_tokens)
  ? `${((a.prompt_tokens ?? 0) + (a.completion_tokens ?? 0)).toLocaleString()} tokens (${(a.prompt_tokens ?? 0).toLocaleString()} in · ${(a.completion_tokens ?? 0).toLocaleString()} out)` : null

/** Write scenes again: all of them or one chapter. Shows what would be reset before anything happens; nothing is lost from the Git history. */
function RewritePanel({ base, onDone, onClose, locked }: { base: string; onDone: () => void; onClose: () => void; locked: boolean }) {
  const scenes = useApi<SceneRow[]>(`${base}/scenes`)
  const [scope, setScope] = useState('all')
  const [force, setForce] = useState(false)
  const [voice, setVoice] = useState(false)
  const act = useAction()
  const plan = useApi<{ reset: string[]; kept: string[]; by_status: Record<string, number> }>(`${base}/rewrite-plan?targets=${encodeURIComponent(scope)}&force=${force}`)
  const chapters = [...new Set((scenes.data ?? []).map((s) => s.chapter))]
  const touchesFirst = scope === 'all' || scope === chapters[0]
  const counts = plan.data ? Object.entries(plan.data.by_status).map(([k, n]) => `${n} ${k}`).join(', ') : ''
  const n = plan.data?.reset.length ?? 0
  return (
    <div className="mt-2 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-sm text-slate-700">Write scenes again. Their text, summaries, checks and findings are removed so the next Run writes them from scratch; everything already written stays in the series history.</p>
      <label className="block text-xs font-medium text-slate-700">Which scenes
        <select value={scope} onChange={(e) => { setScope(e.target.value); setVoice(false) }} disabled={act.busy || locked}
          className="mt-1 block min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm font-normal">
          <option value="all">All scenes of the book</option>
          {chapters.map((c) => <option key={c} value={c}>Chapter {c.split('.').pop()?.replace('ch', '')} only ({c})</option>)}
        </select>
      </label>
      {plan.error && <ErrorBanner message={plan.error} />}
      {plan.data && <p className="text-sm text-slate-800"><strong>{n} scene(s)</strong> will be reset{counts ? ` (${counts})` : ''}.{plan.data.kept.length > 0 && ` ${plan.data.kept.length} scene(s) with text you wrote yourself are kept.`}</p>}
      <label className="flex items-start gap-2 text-sm text-slate-800">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} className="mt-0.5 h-4 w-4" disabled={act.busy || locked} />
        <span>Also discard text I wrote myself</span>
      </label>
      {touchesFirst && (
        <label className="flex items-start gap-2 text-sm text-slate-800">
          <input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} className="mt-0.5 h-4 w-4" disabled={act.busy || locked} />
          <span>Ask me to approve the voice again: the next Run writes chapter 1 only and waits for me.</span>
        </label>
      )}
      <ErrorBanner message={act.error} onClose={act.clear} />
      <div className="flex flex-wrap gap-2">
        <Button kind="danger" disabled={act.busy || locked || !plan.data || n === 0}
          onClick={async () => {
            if (!window.confirm(`Write ${n} scene(s) again? The current text is removed from the working folder (it stays in the series history).`)) return
            if (await act.run(() => post(`${base}/rewrite`, { targets: [scope], force, reset_voice: voice }))) { onDone(); onClose() }
          }}>Reset them, then press Run</Button>
        <Button disabled={act.busy} onClick={onClose}>Cancel</Button>
      </div>
    </div>
  )
}

/** What the running job is doing now. Times come from the server's clock (`server_time` of the last poll), not from this device's. */
function ActivityPanel({ activity, serverTime }: { activity?: JobActivity; serverTime?: string }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [])
  const received = useRef({ at: Date.now(), server: serverTime })
  if (received.current.server !== serverTime) received.current = { at: Date.now(), server: serverTime }
  const serverNow = serverTime ? Date.parse(serverTime) + (Date.now() - received.current.at) : Date.now()
  const a = activity ?? {}
  if (!a.layer && !a.calls) return <p className="mt-2 text-sm text-slate-600">Starting…</p>
  const waiting = a.call_started ? seconds(serverNow - Date.parse(a.call_started)) : null
  const idle = !a.call_started && a.last_call_finished ? seconds(serverNow - Date.parse(a.last_call_finished)) : null
  return (
    <div className="mt-2 space-y-1 text-sm text-slate-700" aria-live="polite">
      <p><span className="text-slate-500">Working on:</span> {[label(a.layer), a.scene, a.step].filter(Boolean).join(' · ') || '…'}</p>
      <p className="text-xs text-slate-600">Model calls this run: {a.calls ?? 0}{a.scenes_done !== undefined ? ` · scenes finished this run: ${a.scenes_done}` : ''}</p>
      {tokenLine(a) && <p className="text-xs text-slate-600">Tokens spent this run: {tokenLine(a)}</p>}
      {waiting !== null && (
        <p className="break-words text-xs text-slate-600">Waiting for the model for {waiting} s{a.call_label ? `: “${a.call_label}”` : ''}</p>
      )}
      {idle !== null && <p className="text-xs text-slate-600">Last model call finished {idle} s ago.</p>}
      {waiting !== null && waiting > 180 && (
        <p className="text-xs text-amber-800">A scene draft usually takes 70 to 90 seconds on this model, so this one is slow. Pause is above if you want to end it; the next Run continues from here.</p>
      )}
    </div>
  )
}

export default function Overview({ series, book, status, reload }: { series: string; book: string; status: BookStatus; reload: () => void }) {
  const act = useAction()
  const [until, setUntil] = useState('')
  const [redoing, setRedoing] = useState<string | null>(null)
  const [rewriting, setRewriting] = useState(false)
  const base = bookPath(series, book)
  const busy = status.job?.status === 'running'
  const waiting = Object.entries(status.checkpoints).filter(([, v]) => v === 'waiting').map(([k]) => k)
  const s = status.scenes
  const total = s.total || 1

  const go = async (fn: () => Promise<unknown>) => { await act.run(fn); reload() }

  return (
    <div className="space-y-3">
      <ErrorBanner message={act.error} onClose={act.clear} />

      {status.planned_words && (
        <p className="rounded-md border border-slate-200 bg-white p-2 text-sm text-slate-700" title="Worked out from the beats of every scene. It is a result of the plan, not a target.">
          The plan: {status.planned_words.chapters} chapters, {status.planned_words.scenes} scenes, about {status.planned_words.low.toLocaleString()} to {status.planned_words.high.toLocaleString()} words (from the beats).
        </p>
      )}
      {status.resume_text && !busy && <p className="rounded-md border border-slate-200 bg-white p-2 text-sm text-slate-700">{status.resume_text}</p>}
      {status.job && (
        <Card title={`${status.job.kind} ${status.job.status}`} tone={busy ? undefined : 'warn'}>
          <p className="text-sm text-slate-700">Started {fmtTime(status.job.started)}. {busy && 'Updating every few seconds; the page can be closed, the run continues.'}</p>
          {busy && <ActivityPanel activity={status.job.activity} serverTime={status.server_time} />}
          {busy && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button kind="danger" disabled={act.busy || status.job.cancel_requested}
                onClick={() => window.confirm('Pause this job? It pauses at the next model call; accepted scenes, drafts and passed checks are kept, and the next Run continues from there.') && go(() => post(`${base}/jobs/${status.job!.id}/cancel`))}>
                {status.job.cancel_requested ? 'Pausing…' : 'Pause'}
              </Button>
              {status.job.cancel_requested && <span className="text-xs text-slate-600">It stops after the model call that is running now, which can take a minute.</span>}
            </div>
          )}
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
        {status.pending_needs > 0 && <p className="mt-1 text-sm text-amber-800">{status.pending_needs} decision(s) about the story's world waiting in the inbox.</p>}
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
                {redoing === l.name && <RedoPanel base={base} layer={l.name} locked={busy} onClose={() => setRedoing(null)} onDone={reload} />}
                {l.name === 'prose' && rewriting && <RewritePanel base={base} locked={busy} onClose={() => setRewriting(false)} onDone={reload} />}
              </div>
              {l.name !== 'prose' && l.status !== 'pending' && redoing !== l.name && (
                <Button disabled={busy} onClick={() => setRedoing(l.name)} title="Write this layer again, with a note on what to change">Redo…</Button>
              )}
              {l.name === 'prose' && !rewriting && (status.scenes.total ?? 0) > 0 && (
                <Button disabled={busy} onClick={() => setRewriting(true)} title="Write all scenes, or one chapter, again">Write again…</Button>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Delete this book">
        <p className="mb-2 text-sm text-slate-600">Removes the book's folder and its entries in the shared story-bible files (tracks, timeline). The cast, rules, style and other books stay. Git keeps the history, so it can be restored.</p>
        <Button kind="danger" disabled={act.busy || busy} title={busy ? 'A job is running on this series' : undefined}
          onClick={async () => {
            if (window.confirm(`Delete the book ${book} from ${series}?`) && (await act.run(() => api(base, { method: 'DELETE' })))) window.location.hash = '#/'
          }}>Delete book {book}</Button>
      </Card>
    </div>
  )
}
