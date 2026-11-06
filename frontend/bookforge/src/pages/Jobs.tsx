import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import type { Job } from '../lib/types'
import { Empty, ErrorBanner, Loading, fmtTime } from '../components/ui'

const TONE: Record<string, string> = { done: 'bg-emerald-100 text-emerald-800', failed: 'bg-red-100 text-red-800', running: 'bg-sky-100 text-sky-800', interrupted: 'bg-amber-100 text-amber-900', cancelled: 'bg-slate-200 text-slate-700' }

export default function Jobs({ series, book }: { series: string; book: string }) {
  const jobs = useApi<Job[]>(`${bookPath(series, book)}/jobs`, 10000)
  if (jobs.error) return <ErrorBanner message={jobs.error} />
  if (!jobs.data) return <Loading />
  if (!jobs.data.length) return <Empty>No jobs yet.</Empty>
  return (
    <ul className="space-y-2">
      {jobs.data.map((j) => (
        <li key={j.id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{j.kind}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${TONE[j.status]}`}>{j.status}</span>
          </div>
          <p className="text-xs text-slate-500">{fmtTime(j.started)}{j.finished ? ` → ${fmtTime(j.finished)}` : ''}</p>
          {j.error && <p className="mt-1 break-words text-xs text-red-700">{j.error}</p>}
          {j.result?.detail && <p className="mt-1 whitespace-pre-line break-words text-xs text-slate-700">{String(j.result.detail)}</p>}
          {(j.result?.ran?.length ?? 0) > 0 && <p className="mt-1 text-xs text-slate-600">Layers accepted: {(j.result?.ran as string[]).join(', ')}</p>}
          {j.result?.report && <p className="mt-1 break-all text-xs text-slate-500">Report: {j.result.report}</p>}
        </li>
      ))}
    </ul>
  )
}
