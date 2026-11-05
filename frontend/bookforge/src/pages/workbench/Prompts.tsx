import { useEffect, useState } from 'react'
import { api, bookPath, post } from '../../lib/api'
import { useAction, useApi, useJob } from '../../lib/hooks'
import type { ExperimentSummary, PromptDetail, PromptInfo } from '../../lib/types'
import { Button, Card, ErrorBanner, Loading } from '../../components/ui'

const TESTABLE = ['prose', 'prose_system']

export default function Prompts({ series, book, onExperiment }: { series: string; book: string; onExperiment: (name: string) => void }) {
  const base = `${bookPath(series, book)}/workbench`
  const list = useApi<PromptInfo[]>(`${base}/prompts`)
  const [name, setName] = useState('')
  const detail = useApi<PromptDetail>(name ? `${base}/prompts/${name}` : null)
  const [text, setText] = useState('')
  const [check, setCheck] = useState<{ errors: string[]; warnings: string[] } | null>(null)
  const act = useAction()
  const ab = useJob<ExperimentSummary>(bookPath(series, book))

  useEffect(() => { if (detail.data) { setText(detail.data.effective); setCheck(null) } }, [detail.data])

  const runCheck = () => act.run(async () => setCheck(await post(`${base}/prompts/${name}/check`, { text })))
  const save = async () => { if (await act.run(() => api(`${base}/prompts/${name}`, { method: 'PUT', body: { text } }))) { detail.reload(); list.reload() } }
  const restore = async () => {
    if (window.confirm('Go back to the shipped prompt?') && (await act.run(() => api(`${base}/prompts/${name}`, { method: 'DELETE' })))) { detail.reload(); list.reload() }
  }

  if (list.error) return <ErrorBanner message={list.error} />
  if (!list.data) return <Loading />
  const changed = detail.data ? text !== detail.data.effective : false

  return (
    <div className="space-y-3">
      <Card title="Prompt templates">
        <ul className="grid gap-1 sm:grid-cols-2">
          {list.data.map((p) => (
            <li key={p.name}>
              <button onClick={() => setName(p.name)} aria-current={name === p.name}
                className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-md border px-3 text-left text-sm ${name === p.name ? 'border-slate-900 bg-slate-50' : 'border-slate-200'}`}>
                <span>{p.name}</span>{p.overridden && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">yours</span>}
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {name && detail.data && (
        <Card title={name} right={<span className="text-xs text-slate-500">{detail.data.override !== null ? 'your version' : 'the shipped version'}</span>}>
          <p className="mb-2 text-xs text-slate-600">Slots the code fills: {detail.data.slots.map((s) => <code key={s} className="mr-1 rounded bg-slate-100 px-1">{`{${s}}`}</code>)}{!detail.data.slots.length && 'none'}</p>
          <textarea value={text} onChange={(e) => { setText(e.target.value); setCheck(null) }} rows={16} spellCheck={false} aria-label="Template text"
            className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs" />
          <ErrorBanner message={act.error} onClose={act.clear} />
          {check && (
            <div className="mt-2 text-sm">
              {check.errors.map((e) => <p key={e} className="text-red-700">✗ {e}</p>)}
              {check.warnings.map((w) => <p key={w} className="text-amber-800">! {w}</p>)}
              {!check.errors.length && !check.warnings.length && <p className="text-emerald-800">✓ the template is valid</p>}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={runCheck} disabled={act.busy}>Check</Button>
            <Button kind="primary" onClick={save} disabled={act.busy || !changed}>Save as my version</Button>
            {detail.data.override !== null && <Button kind="danger" onClick={restore} disabled={act.busy}>Back to shipped</Button>}
            {TESTABLE.includes(name) && (
              <Button disabled={ab.busy || !changed} title="Run this text and the current prompt on the benchmark scenes and compare" onClick={async () => { await ab.run('/workbench/ab', { template: name, candidate: text }) }}>
                {ab.busy ? 'Running both prompts…' : 'A/B test this text'}
              </Button>
            )}
          </div>
          <ErrorBanner message={ab.error} />
          {ab.result && <p className="mt-2 text-sm">Done. <button className="font-medium underline" onClick={() => onExperiment(ab.result!.name)}>Open the experiment {ab.result.name}</button></p>}
          {detail.data.diff && (
            <details className="mt-3"><summary className="min-h-10 cursor-pointer text-sm">What differs from the shipped prompt</summary>
              <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-2 text-xs">{detail.data.diff}</pre>
            </details>
          )}
        </Card>
      )}
      {name && detail.loading && !detail.data && <Loading />}
    </div>
  )
}
