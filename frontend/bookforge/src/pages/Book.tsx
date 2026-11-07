import { useEffect, useState } from 'react'
import { api, bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href, type Route } from '../lib/route'
import type { BookStatus } from '../lib/types'
import { ErrorBanner, Loading } from '../components/ui'
import Documents from './Documents'
import Inbox from './Inbox'
import Jobs from './Jobs'
import Models from './Models'
import Overview from './Overview'
import Read from './Read'
import Research from './Research'
import SceneView from './SceneView'
import Tracks from './Tracks'
import Tree from './Tree'
import Workbench from './Workbench'

const TABS: [string, string][] = [['overview', 'Overview'], ['documents', 'Documents'], ['tree', 'Progress'], ['inbox', 'Inbox'], ['tracks', 'Tracks'], ['research', 'Research'], ['read', 'Read'], ['jobs', 'Jobs'], ['models', 'Models'], ['workbench', 'Workbench']]

export default function Book({ route }: { route: Route }) {
  const { series, book } = route as Required<Pick<Route, 'series' | 'book'>>
  const tab = route.tab ?? 'overview'
  const [running, setRunning] = useState(false)
  const status = useApi<BookStatus>(`${bookPath(series, book)}/status`, running ? 4000 : 20000)
  const s = status.data
  useEffect(() => { setRunning(status.data?.job?.status === 'running') }, [status.data])

  if (status.error && !s) return <div className="space-y-3"><ErrorBanner message={status.error} /><a href="#/" className="text-sm underline">All series</a></div>
  if (!s) return <Loading />
  const inboxCount = s.pending_changes + (s.pending_needs ?? 0) + Object.values(s.checkpoints).filter((v) => v === 'waiting').length

  return (
    <div className="space-y-3">
      <div>
        <a href="#/" className="text-sm text-slate-600 underline">← All series</a>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold">{s.title || book} <span className="font-normal text-slate-500">· {series}{s.title ? ` / ${book}` : ''}</span></h1>
          <button type="button" className="min-h-10 rounded-md px-2 text-sm text-slate-600 underline" onClick={async () => {
            const next = window.prompt('Title of this book (its id, ' + book + ', stays the same):', s.title || '')
            if (next && next.trim() && next.trim() !== s.title) { try { await api(`${bookPath(series, book)}/title`, { method: 'PUT', body: { title: next.trim() } }); status.reload() } catch (e) { window.alert(String((e as Error).message)) } }
          }}>{s.title ? 'Rename' : 'Give it a title'}</button>
        </div>
      </div>
      <nav role="tablist" aria-label="Sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {TABS.map(([k, label]) => {
          const on = tab === k || (tab === 'scene' && k === 'tree')
          return (
            <a key={k} role="tab" aria-selected={on} href={href({ series, book, tab: k })}
              className={`flex min-h-10 shrink-0 items-center gap-1 rounded-md px-3 text-sm ${on ? 'bg-slate-900 text-white' : 'border border-slate-300 bg-white text-slate-800'}`}>
              {label}{k === 'inbox' && inboxCount > 0 && <span className="rounded-full bg-amber-400 px-1.5 text-xs text-slate-900">{inboxCount}</span>}
            </a>
          )
        })}
      </nav>
      {status.error && <ErrorBanner message={status.error} />}
      {tab === 'overview' && <Overview series={series} book={book} status={s} reload={status.reload} />}
      {tab === 'documents' && <Documents series={series} book={book} docKey={route.id} />}
      {tab === 'tree' && <Tree series={series} book={book} />}
      {tab === 'inbox' && <Inbox series={series} book={book} status={s} reload={status.reload} />}
      {tab === 'scene' && route.id && <SceneView series={series} book={book} id={route.id} status={s} reload={status.reload} />}
      {tab === 'tracks' && <Tracks series={series} book={book} />}
      {tab === 'research' && <Research series={series} book={book} />}
      {tab === 'read' && <Read series={series} book={book} />}
      {tab === 'jobs' && <Jobs series={series} book={book} />}
      {tab === 'models' && <Models series={series} running={running} />}
      {tab === 'workbench' && <Workbench series={series} book={book} />}
    </div>
  )
}
