import { useRef, useState } from 'react'
import { api, bookPath } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { DocumentFull, DocumentInfo } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, Markdown } from '../components/ui'

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {  // no clipboard permission or not a secure page: fall back to selecting a hidden text box
    const box = document.createElement('textarea')
    box.value = text; box.style.position = 'fixed'; box.style.opacity = '0'
    document.body.appendChild(box); box.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(box)
    if (!ok) throw new Error('Copying was blocked by the browser')
  }
}

/** Copies the text that `getText` returns (fetched when pressed, so a list row need not load every document). */
function CopyButton({ getText, label = 'Copy', title }: { getText: () => Promise<string> | string; label?: string; title?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const timer = useRef<number | undefined>(undefined)
  const press = async () => {
    try { await copyToClipboard(await getText()); setState('copied') } catch { setState('failed') }
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), 2000)
  }
  return (
    <button type="button" onClick={press} title={title ?? 'Copy the text of this document'} aria-live="polite"
      className="min-h-10 shrink-0 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-800 hover:bg-slate-50">
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : label}
    </button>
  )
}

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
        <Card title={d.title} right={<span className="flex items-center gap-2 text-xs text-slate-500">{d.group}
            {d.exists && <CopyButton getText={() => (draft !== null ? draft : d.text)} label={d.truncated ? 'Copy first part' : 'Copy'}
              title={d.truncated ? 'The file is long: only the part shown here is copied' : draft !== null ? 'Copy the text you are editing' : undefined} />}</span>}>
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
                <div className="flex items-center gap-2">
                  <a href={href({ series, book, tab: 'documents', id: d.key })} className="flex min-h-12 min-w-0 flex-1 items-center justify-between gap-2 py-2">
                    <span className={`min-w-0 flex-1 text-sm ${d.exists ? '' : 'text-slate-400'}`}>{d.title}</span>
                    <span className="shrink-0 text-xs text-slate-500">{d.exists ? `${d.words} words` : 'not written yet'}</span>
                  </a>
                  {d.exists && <CopyButton label="Copy" title={`Copy the text of ${d.title}`} getText={async () => (await api<DocumentFull>(`${base}/${encodeURIComponent(d.key)}`)).text} />}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}
