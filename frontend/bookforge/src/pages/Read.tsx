import { useState } from 'react'
import { bookPath, post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import type { Job } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Markdown, fmtTime } from '../components/ui'

interface ExportRecord { name: string; draft: boolean; created: string | null; files: string[]; skipped: Record<string, string>; warnings: string[]; sha256: string }

const FORMATS: [string, string][] = [['docx', 'Word manuscript'], ['epub', 'EPUB'], ['pdf', 'Print PDF'], ['companion', 'Companion book']]

function Exports({ series, book }: { series: string; book: string }) {
  const base = bookPath(series, book)
  const list = useApi<ExportRecord[]>(`${base}/exports`, 8000)
  const jobs = useApi<Job[]>(`${base}/jobs`, 8000)
  const act = useAction()
  const [picked, setPicked] = useState<string[]>(FORMATS.map(([k]) => k))
  const [draft, setDraft] = useState(false)
  const last = jobs.data?.find((j) => j.kind === 'export')
  const running = jobs.data?.some((j) => j.status === 'running')

  const start = async () => {
    if (await act.run(() => post(`${base}/export`, { formats: picked, draft }))) { jobs.reload(); list.reload() }
  }

  return (
    <Card title="Export">
      <div className="space-y-3">
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1">
          <legend className="sr-only">Formats</legend>
          {FORMATS.map(([k, label]) => (
            <label key={k} className="flex min-h-10 items-center gap-1 text-sm">
              <input type="checkbox" checked={picked.includes(k)} onChange={(e) => setPicked(e.target.checked ? [...picked, k] : picked.filter((x) => x !== k))} />{label}
            </label>
          ))}
        </fieldset>
        <label className="flex min-h-10 items-center gap-1 text-sm"><input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
          Draft (the final checkpoint need not be approved)</label>
        <ErrorBanner message={act.error} onClose={act.clear} />
        <Button kind="primary" disabled={act.busy || !!running || !picked.length} onClick={start}>{running ? 'Working…' : 'Export'}</Button>
        {last && last.status === 'failed' && <ErrorBanner message={`Last export failed: ${last.error}`} />}
        {last && last.status === 'running' && <p className="text-sm text-slate-600">Exporting since {fmtTime(last.started)}…</p>}
        {list.data && !list.data.length && <Empty>Nothing exported yet.</Empty>}
        <ul className="space-y-3">
          {list.data?.map((x) => (
            <li key={x.name} className="rounded-md border border-slate-200 p-2 text-sm">
              <p className="font-medium">{x.name}{x.draft && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">draft</span>}</p>
              <p className="text-xs text-slate-500">{fmtTime(x.created)} · text {x.sha256.slice(0, 8)}</p>
              <ul className="mt-1 flex flex-wrap gap-2">
                {x.files.map((f) => (
                  <li key={f}><a className="inline-flex min-h-10 items-center rounded-md border border-slate-300 px-3 underline"
                    href={`${import.meta.env.BASE_URL}api${base}/exports/${encodeURIComponent(x.name)}/${encodeURIComponent(f)}`} download>{f}</a></li>
                ))}
              </ul>
              {Object.entries(x.skipped).map(([k, why]) => <p key={k} className="mt-1 text-xs text-amber-800">Skipped {k}: {why}</p>)}
              {x.warnings.map((w) => <p key={w} className="mt-1 text-xs text-slate-600">Note: {w}</p>)}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

export default function Read({ series, book }: { series: string; book: string }) {
  const [partial, setPartial] = useState(false)
  const m = useApi<{ markdown: string }>(`${bookPath(series, book)}/manuscript${partial ? '?partial=true' : ''}`)
  return (
    <div className="space-y-3">
      <Exports series={series} book={book} />
      <div className="flex gap-2">
        <Button kind={partial ? 'plain' : 'primary'} onClick={() => setPartial(false)}>Manuscript</Button>
        <Button kind={partial ? 'primary' : 'plain'} onClick={() => setPartial(true)}>Partial</Button>
      </div>
      {m.error && <Empty>{m.error}. Use Assemble on the overview once every scene is accepted.</Empty>}
      {m.data && <article className="rounded-lg border border-slate-200 bg-white p-4 font-serif"><Markdown text={m.data.markdown} /></article>}
    </div>
  )
}
