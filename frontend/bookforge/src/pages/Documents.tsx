import { useState } from 'react'
import { api, bookPath } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { DocumentFull, DocumentInfo } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, Markdown } from '../components/ui'

/** The files you review at the checkpoints. You can edit them here: an edit is checked first and refused, with the reason, if it breaks the structure. */
export default function Documents({ series, book, docKey }: { series: string; book: string; docKey?: string }) {
  const base = `${bookPath(series, book)}/documents`
  const list = useApi<DocumentInfo[]>(base)
  const doc = useApi<DocumentFull>(docKey ? `${base}/${encodeURIComponent(docKey)}` : null)
  const [draft, setDraft] = useState<string | null>(null)  // the text being edited, or null when just reading
  const save = useAction()

  if (docKey) {
    if (doc.error) return <div className="space-y-3"><ErrorBanner message={doc.error} /><a className="text-sm underline" href={href({ series, book, tab: 'documents' })}>All documents</a></div>
    if (!doc.data) return <Loading />
    const d = doc.data
    return (
      <div className="space-y-3">
        <a className="text-sm text-slate-600 underline" onClick={() => { setDraft(null); save.clear() }} href={href({ series, book, tab: 'documents' })}>← All documents</a>
        <Card title={d.title} right={<span className="text-xs text-slate-500">{d.group}</span>}>
          {draft !== null ? (
            <div className="space-y-2">
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={22} spellCheck={d.kind !== 'yaml'}
                aria-label={`Edit ${d.title}`} className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs leading-relaxed" />
              <ErrorBanner message={save.error} onClose={save.clear} />
              <div className="flex flex-wrap gap-2">
                <Button kind="primary" disabled={save.busy} onClick={async () => {
                  if (await save.run(() => api(`${base}/${encodeURIComponent(d.key)}`, { method: 'PUT', body: { text: draft } }))) { setDraft(null); doc.reload() }
                }}>{save.busy ? 'Saving…' : 'Save'}</Button>
                <Button disabled={save.busy} onClick={() => { setDraft(null); save.clear() }}>Cancel</Button>
              </div>
            </div>
          ) : (
            <>
              {!d.exists ? <Empty>Not written yet.{d.editable ? ' You can write it yourself, or the pipeline fills it in when it runs.' : ' It appears here once the pipeline has produced it.'}</Empty>
                : d.kind === 'markdown' ? <Markdown text={d.text} />
                : <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-800">{d.text}</pre>}
              {d.truncated && <p className="mt-2 text-xs text-amber-800">The file is long; only the first part is shown, so it cannot be edited here. Open it on the machine.</p>}
              {d.editable && !d.truncated && <div className="mt-3"><Button onClick={() => setDraft(d.exists ? d.text : '')}>{d.exists ? 'Edit' : 'Write it'}</Button></div>}
            </>
          )}
        </Card>
        <p className="text-xs text-slate-500">{d.editable
          ? 'Your edit is saved as soon as it passes the checks (the structure of a north star, valid YAML for the plan). It is not saved if it breaks them, and the reason is shown. Everything you save is kept in the series history.'
          : 'Read-only: the pipeline writes this one.'}</p>
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
