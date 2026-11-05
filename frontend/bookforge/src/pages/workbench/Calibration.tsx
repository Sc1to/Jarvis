import { useState } from 'react'
import { api, bookPath } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import type { CalibrationReport, SceneRow } from '../../lib/types'
import { Button, Card, ErrorBanner, Loading } from '../../components/ui'

const CRITERIA = ['stakes', 'voice', 'show_dont_tell', 'pacing', 'dialogue', 'beats_covered']

export default function Calibration({ series, book }: { series: string; book: string }) {
  const base = `${bookPath(series, book)}/workbench/calibration`
  const report = useApi<CalibrationReport>(base)
  const scenes = useApi<SceneRow[]>(`${bookPath(series, book)}/scenes`)
  const [scene, setScene] = useState('')
  const [scores, setScores] = useState<Record<string, number>>(Object.fromEntries(CRITERIA.map((c) => [c, 3])))
  const act = useAction()

  const save = async () => { if (await act.run(() => api(`${base}/${encodeURIComponent(scene)}`, { method: 'PUT', body: { scores } }))) report.reload() }
  if (report.error) return <ErrorBanner message={report.error} />
  if (!report.data) return <Loading />
  const r = report.data
  const written = scenes.data?.filter((s) => s.words > 0) ?? []

  return (
    <div className="space-y-3">
      <Card title="Score a scene yourself" >
        <p className="mb-2 text-sm text-slate-600">Read a written scene and give it 1–5 on the critic's six criteria (3 is acceptable). Do this for about five chapter-1 scenes.</p>
        <select value={scene} onChange={(e) => { setScene(e.target.value); const mine = r.scenes.find((s) => s.scene === e.target.value)?.yours; if (mine) setScores(mine) }} aria-label="Scene" className="min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
          <option value="">choose a scene</option>{written.map((s) => <option key={s.id} value={s.id}>{s.id}{r.scenes.some((x) => x.scene === s.id) ? ' · scored' : ''}</option>)}
        </select>
        {scene && (
          <div className="mt-3 space-y-2">
            {CRITERIA.map((c) => (
              <label key={c} className="flex items-center gap-3 text-sm">
                <span className="w-32 shrink-0 text-slate-700">{c.replace(/_/g, ' ')}</span>
                <input type="range" min={1} max={5} step={1} value={scores[c]} onChange={(e) => setScores({ ...scores, [c]: Number(e.target.value) })} className="h-10 min-w-0 flex-1" />
                <span className="w-4 text-right tabular-nums">{scores[c]}</span>
              </label>
            ))}
            <ErrorBanner message={act.error} onClose={act.clear} />
            <Button kind="primary" onClick={save} disabled={act.busy}>Save my scores</Button>
          </div>
        )}
      </Card>

      <Card title="You against the critic" tone={r.needs_recalibration ? 'warn' : undefined}>
        <p className="text-sm">{r.advice}</p>
        {r.compared > 0 && <p className="mt-1 text-xs text-slate-600">{r.compared} scene(s) scored by both; the rankings disagree on {r.ranking_disagreements} pair(s).</p>}
        <ul className="mt-3 space-y-2">
          {CRITERIA.map((c) => {
            const s = r.criteria[c]
            return (
              <li key={c} className="text-sm">
                <div className="flex justify-between"><span>{c.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-slate-500">{s ? `off by ${s.mean_abs_diff} on average, ${s.bias > 0 ? 'you score higher' : s.bias < 0 ? 'the critic scores higher' : 'no bias'} (${s.bias > 0 ? '+' : ''}${s.bias}), within 1 on ${Math.round(s.within_one * 100)}%` : 'no pairs yet'}</span></div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden>
                  {s && <div className={`h-full ${s.mean_abs_diff >= 1.5 ? 'bg-red-500' : s.mean_abs_diff >= 0.75 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(100, (s.mean_abs_diff / 4) * 100)}%` }} />}
                </div>
              </li>
            )
          })}
        </ul>
        {r.scenes.length > 0 && (
          <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs">
            <thead><tr className="text-slate-500"><th className="py-1 pr-2">Scene</th>{CRITERIA.map((c) => <th key={c} className="px-1" title={c}>{c.slice(0, 3)}</th>)}</tr></thead>
            <tbody>{r.scenes.map((s) => (
              <tr key={s.scene} className="border-t border-slate-100">
                <td className="py-1 pr-2 font-mono">{s.scene.split('.').slice(1).join('.')}</td>
                {CRITERIA.map((c) => <td key={c} className="px-1 tabular-nums">{s.yours[c]}{s.critic && <span className={s.critic[c] === s.yours[c] ? 'text-slate-400' : 'text-red-600'}> / {s.critic[c]}</span>}</td>)}
              </tr>))}
            </tbody></table><p className="mt-1 text-xs text-slate-500">yours / the critic's</p></div>
        )}
      </Card>
    </div>
  )
}
