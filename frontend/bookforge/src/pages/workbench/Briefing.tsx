import { useState } from 'react'
import { bookPath } from '../../lib/api'
import { useApi, useJob } from '../../lib/hooks'
import type { BriefingPreview, SceneRow, XrayResult } from '../../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading } from '../../components/ui'
import Checks from './Checks'

const SEV = { problem: 'text-red-700', warn: 'text-amber-800', info: 'text-slate-600' }
const CAUSE: Record<string, string> = {
  missing_input: 'Missing input: the writer was not given something the scene needed.',
  weak_prompt: 'Weak prompt: the inputs are complete, but you rewrote the prompt.',
  model_limit: 'Model limit: complete inputs and the shipped prompt, and the model still fell short.',
  none: 'Nothing points to a problem.',
}
const COLORS = ['bg-sky-400', 'bg-violet-400', 'bg-teal-400', 'bg-rose-400', 'bg-lime-500', 'bg-orange-400', 'bg-indigo-400', 'bg-cyan-500']

export default function Briefing({ series, book }: { series: string; book: string }) {
  const base = bookPath(series, book)
  const scenes = useApi<SceneRow[]>(`${base}/scenes`)
  const [scene, setScene] = useState('')
  const preview = useApi<BriefingPreview>(scene ? `${base}/workbench/briefing/${encodeURIComponent(scene)}` : null)
  const inputs = useApi<XrayResult>(scene ? `${base}/workbench/xray/${encodeURIComponent(scene)}` : null)
  const beats = useJob<XrayResult>(base)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const x = beats.result ?? inputs.data

  return (
    <div className="space-y-3">
      <Checks series={series} book={book} />
      <select value={scene} onChange={(e) => { setScene(e.target.value); beats.reset() }} aria-label="Scene" className="min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
        <option value="">choose a scene</option>
        {scenes.data?.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.status}</option>)}
      </select>
      {!scene && <Empty>Choose a scene to see exactly what the writer is given for it.</Empty>}
      {scene && preview.error && <ErrorBanner message={preview.error} />}
      {scene && !preview.data && !preview.error && <Loading />}
      {preview.data && (
        <Card title={`Briefing: about ${preview.data.tokens} of ${preview.data.budget} tokens`}>
          <div className="flex h-4 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="How the token budget splits across parts">
            {preview.data.sections.map((s, i) => <div key={s.heading} title={`${s.heading}: ${s.tokens}`} className={COLORS[i % COLORS.length]} style={{ width: `${(100 * s.tokens) / preview.data!.budget}%` }} />)}
          </div>
          {preview.data.trimmed.length > 0 && <p className="mt-2 text-xs text-amber-800">Cut to fit: {preview.data.trimmed.join('; ')}</p>}
          <ul className="mt-2 divide-y divide-slate-100">
            {preview.data.sections.map((s, i) => (
              <li key={s.heading}>
                <button onClick={() => setOpen({ ...open, [s.heading]: !open[s.heading] })} aria-expanded={!!open[s.heading]} className="flex min-h-11 w-full items-center gap-2 py-2 text-left text-sm">
                  <span className={`h-3 w-3 shrink-0 rounded-sm ${COLORS[i % COLORS.length]}`} />
                  <span className="min-w-0 flex-1">{s.heading}</span>
                  <span className="text-xs tabular-nums text-slate-500">{s.tokens}</span>
                </button>
                {open[s.heading] && <pre className="mb-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-2 text-xs">{s.text}</pre>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {x && (
        <Card title="X-ray" right={<Button disabled={beats.busy} onClick={() => beats.run(`/workbench/xray/${encodeURIComponent(scene)}`, { beats: true })} title="Ask the planner model which planned beats are on the page">{beats.busy ? 'Checking…' : 'Check the beats'}</Button>}>
          <ErrorBanner message={beats.error} />
          <p className="rounded-md bg-slate-50 p-2 text-sm font-medium">{CAUSE[x.diagnosis.cause]}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{x.diagnosis.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          {x.beats_error && <p className="mt-2 text-xs text-slate-600">Beats not checked: {x.beats_error}</p>}
          {x.beats && (
            <ol className="mt-3 space-y-1 text-sm">{x.beats.map((b) => (
              <li key={b.n} className={b.happens ? 'text-emerald-800' : 'font-medium text-red-700'}>
                {b.happens ? '✓' : '✗'} Beat {b.n}: {b.beat}{b.happens ? <span className="block text-xs italic text-slate-600">“{b.evidence}”</span> : ' never happened on the page'}
              </li>
            ))}</ol>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">What was given</h3>
          <ul className="mt-1 space-y-1 text-sm">{x.findings.map((f, i) => <li key={i} className={SEV[f.severity]}>{f.severity === 'info' ? '·' : '!'} {f.message}</li>)}</ul>
        </Card>
      )}
    </div>
  )
}
