import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { DocumentFull, DocumentInfo } from '../lib/types'
import { Card, Empty, ErrorBanner, Loading, Markdown } from '../components/ui'

/** Read-only: the files you review at the checkpoints. Editing stays in the files (they are kept as you leave them). */
export default function Documents({ series, book, docKey }: { series: string; book: string; docKey?: string }) {
  const base = `${bookPath(series, book)}/documents`
  const list = useApi<DocumentInfo[]>(base)
  const doc = useApi<DocumentFull>(docKey ? `${base}/${encodeURIComponent(docKey)}` : null)

  if (docKey) {
    if (doc.error) return <div className="space-y-3"><ErrorBanner message={doc.error} /><a className="text-sm underline" href={href({ series, book, tab: 'documents' })}>All documents</a></div>
    if (!doc.data) return <Loading />
    const d = doc.data
    return (
      <div className="space-y-3">
        <a className="text-sm text-slate-600 underline" href={href({ series, book, tab: 'documents' })}>← All documents</a>
        <Card title={d.title} right={<span className="text-xs text-slate-500">{d.group}</span>}>
          {!d.exists ? <Empty>Not written yet. It appears here once the pipeline has produced it.</Empty>
            : d.kind === 'markdown' ? <Markdown text={d.text} />
            : <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-800">{d.text}</pre>}
          {d.truncated && <p className="mt-2 text-xs text-amber-800">The file is long; only the first part is shown. Open it on the machine to see all of it.</p>}
        </Card>
        <p className="text-xs text-slate-500">Read-only here. To change it, edit the file on the machine; your edits are kept.</p>
      </div>
    )
  }

  if (list.error) return <ErrorBanner message={list.error} />
  if (!list.data) return <Loading />
  const groups = [...new Set(list.data.map((d) => d.group))]
  return (
    <div className="space-y-3">
      {groups.map((g) => (
        <Card key={g} title={g}>
          <ul className="divide-y divide-slate-100">
            {list.data!.filter((d) => d.group === g).map((d) => (
              <li key={d.key}>
                <a href={href({ series, book, tab: 'documents', id: d.key })} className="flex min-h-12 items-center justify-between gap-2 py-2">
                  <span className={`min-w-0 flex-1 text-sm ${d.exists ? '' : 'text-slate-400'}`}>{d.title}</span>
                  <span className="shrink-0 text-xs text-slate-500">{d.exists ? `${d.words} words` : 'not written yet'}</span>
                </a>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}
