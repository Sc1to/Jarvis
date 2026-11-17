import { useEffect, useRef, useState } from 'react'
import { post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { Button, ErrorBanner } from './ui'

/** Write a planning layer again, optionally with a note on what to change. Nothing is deleted: the current files are committed first. */
export default function RedoPanel({ base, layer, onDone, onClose, locked }: { base: string; layer: string; onDone: () => void; onClose: () => void; locked: boolean }) {
  const plan = useApi<{ also_resets: string[]; prose_written?: { scenes: number; own: number } }>(`${base}/redo/${layer}`)
  const act = useAction()
  const [note, setNote] = useState('')
  const [cascade, setCascade] = useState(false)
  const [discard, setDiscard] = useState(false)
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [])
  const written = plan.data?.prose_written?.scenes ?? 0
  const own = plan.data?.prose_written?.own ?? 0
  const also = plan.data?.also_resets ?? []
  const label = (l: string) => l.replace(/_/g, ' ')
  return (
    <div ref={ref} className="mt-2 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-sm text-slate-700">Write <strong>{label(layer)}</strong> again. What is there now is committed first, so it stays in the series history.</p>
      {plan.error && <ErrorBanner message={plan.error} />}
      {written > 0 && (
        <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          <p><strong>{written} scene(s) of written text exist.</strong> Planning again resets them; their text stays in the series history.</p>
          <label className="flex items-start gap-2"><input type="checkbox" checked={discard} onChange={(e) => setDiscard(e.target.checked)} className="mt-0.5 h-4 w-4" />
            <span>Also discard the written scenes</span></label>
          {own > 0 && <label className="flex items-start gap-2"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} className="mt-0.5 h-4 w-4" />
            <span>Also discard text I wrote myself ({own} scene(s))</span></label>}
        </div>
      )}
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
      {result && <p className="rounded-md border border-emerald-300 bg-emerald-50 p-2 text-sm text-emerald-900">{result}</p>}
      <div className="flex flex-wrap gap-2">
        <Button kind="primary" disabled={act.busy || locked || !plan.data || !!result || (also.length > 0 && !cascade) || (written > 0 && (!discard || (own > 0 && !force)))}
          onClick={async () => {
            let out: { reset: string[]; scenes_discarded?: number } | undefined
            const ok = await act.run(async () => { out = await post(`${base}/redo`, { layer, note, cascade, discard_prose: discard, force }) as typeof out })
            if (ok && out) { setResult(`Reset: ${out.reset.map(label).join(', ')}${out.scenes_discarded ? `; ${out.scenes_discarded} written scene(s) discarded` : ''}. Press Run to write them again.`); onDone() }
          }}>Reset it, then press Run</Button>
        <Button disabled={act.busy} onClick={onClose}>{result ? 'Close' : 'Cancel'}</Button>
      </div>
    </div>
  )
}
