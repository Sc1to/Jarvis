import { useRef, useState } from 'react'
import { api, bookPath } from '../lib/api'
import { useAction, useApi, useJob } from '../lib/hooks'
import { href } from '../lib/route'
import type { BookStatus, DocumentFull, DocumentInfo, SeriesInfo, StyleState } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, Markdown } from '../components/ui'
import RedoPanel from '../components/RedoPanel'

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

/** Suggest a style guide from the genre: the model names successful titles of the same genre, reads what the web says about their prose style, and writes a guide to edit. */
function StyleSuggest({ series, book, onDone }: { series: string; book: string; onDone: () => void }) {
  const base = bookPath(series, book)
  const state = useApi<StyleState>(`${base}/style`)
  const status = useApi<BookStatus>(`${base}/status`)
  const written = Object.entries(status.data?.scenes ?? {}).some(([k, n]) => k !== 'total' && k !== 'pending' && Number(n) > 0)
  const job = useJob<{ file: string; words: number; verified: string[]; web: boolean; problems: string[] }>(base)
  const s = state.data
  const sug = s?.suggestion
  const start = async (replace: boolean) => {
    if (replace && !window.confirm('Replace your style guide with a new suggestion? What is there now is kept in the series history.' + (written ? ' Scenes already written with the old guide will be marked out of date.' : ''))) return
    await job.run('/style/suggest', { replace })
    state.reload(); onDone()
  }
  return (
    <Card title="Suggested style guide">
      <p className="text-sm text-slate-700">Bookforge names the genre, picks successful titles of the same genre, reads what critics and readers say about their prose style, and writes a guide in its own words. It never copies their sentences, and you edit the result.</p>
      <ErrorBanner message={job.error} />
      <div className="mt-2 flex flex-wrap gap-2">
        <Button disabled={job.busy} kind="primary" onClick={() => start(false)}>{job.busy ? 'Reading the web and writing…' : s?.has_guide ? 'Suggest another (kept beside yours)' : 'Suggest a style guide'}</Button>
        {s?.has_guide && <Button disabled={job.busy} onClick={() => start(true)} title={written ? 'Scenes already written with the old guide will be marked out of date' : undefined}>Replace mine with a suggestion</Button>}
      </div>
      {s?.has_guide && <p className="mt-2 text-xs text-slate-600">A suggestion is kept beside your guide and changes nothing that is written. Replacing your guide{written ? ' marks the scenes already written as out of date' : ' is possible at any time'}.</p>}
      {job.busy && <p className="mt-2 text-xs text-slate-600">This searches the web and reads several pages; it can take a few minutes. You can leave the page.</p>}
      {sug && (
        <div className="mt-3 space-y-1 border-t border-slate-200 pt-3 text-sm">
          <p><span className="font-medium">{sug.genre}</span>{sug.subgenres.length > 0 && ` (${sug.subgenres.join(', ')})`}{sug.intended_style && `: ${sug.intended_style}`}</p>
          {sug.verified_titles.length > 0
            ? <ul className="list-disc space-y-0.5 pl-5 text-xs">{sug.verified_titles.map((t) => <li key={t.title}><span className="font-medium">{t.title}</span> by {t.author}: {t.why}</li>)}</ul>
            : <p className="text-xs text-slate-600">{sug.web ? 'No title could be checked on the web, so none is named.' : 'The web was not used, so no title is named.'}</p>}
          <p className="text-xs text-slate-600">Written to {sug.file} ({sug.words} words) from {sug.sources.length} page(s).</p>
          {sug.problems.length > 0 && <p className="break-words text-xs text-amber-800">Not everything worked: {sug.problems.slice(0, 3).join('; ')}</p>}
        </div>
      )}
    </Card>
  )
}

const LAYER_OF: Record<string, string> = {
  series_north_star: 'series_north_star', book_north_star: 'book_north_star', synopsis: 'synopsis', ledger: 'ledger', acts: 'acts', chapters: 'chapters', scenes: 'scenes',
}

/** Write a document again with the model, at any time it is safe: only when nothing is built on it and no scene is written, so no fact already written is invalidated. */
function WriteAgain({ series, book, docKey }: { series: string; book: string; docKey: string }) {
  const layer = LAYER_OF[docKey]
  const base = bookPath(series, book)
  const status = useApi<BookStatus>(layer ? `${base}/status` : null)
  const plan = useApi<{ also_resets: string[] }>(layer ? `${base}/redo/${layer}` : null)
  const all = useApi<SeriesInfo[]>(layer === 'series_north_star' ? '/series' : null)
  const [open, setOpen] = useState(false)
  if (!layer || !status.data || !plan.data) return null
  const item = status.data.layers.find((l) => l.name === layer)
  if (!item || item.status === 'pending') return null
  const written = Object.entries(status.data.scenes).some(([k, n]) => k !== 'total' && k !== 'pending' && Number(n) > 0)
  const also = plan.data.also_resets
  const shared = layer === 'series_north_star' && (all.data?.find((x) => x.name === series)?.books.length ?? 2) > 1
  const why = written ? 'Scenes are already written, so planning layers cannot be written again here (use Write again in the Overview).'
    : also.length > 0 ? `Other layers are built on it (${also.map((l) => l.replace(/_/g, ' ')).join(', ')}). Writing it again would reset them, so it is not offered here; the Overview has Redo with that choice.`
    : shared ? 'Other books of this series were built on it.' : ''
  return (
    <Card title="Write it again">
      {why ? <p className="text-sm text-slate-600">{why}</p> : (
        <>
          <p className="text-sm text-slate-700">Nothing is built on this yet, so it can be written again without invalidating anything. Tell the model what to change (or not), then press Run in the Overview.</p>
          {!open && <div className="mt-2"><Button onClick={() => setOpen(true)}>Write it again…</Button></div>}
          {open && <RedoPanel base={base} layer={layer} locked={false} onClose={() => setOpen(false)} onDone={() => { status.reload(); plan.reload() }} />}
        </>
      )}
    </Card>
  )
}

/** A Suggest button on the style guide's row of the list: starts the suggestion without opening the document. */
function SuggestRow({ series, book, onDone }: { series: string; book: string; onDone: () => void }) {
  const base = bookPath(series, book)
  const job = useJob(base)
  return (
    <Button disabled={job.busy} onClick={async () => { await job.run('/style/suggest', { replace: false }); onDone() }}
      title="Suggest a style guide from the genre and what the web says about successful books' prose style. A guide you have is kept; the suggestion goes beside it.">
      {job.busy ? 'Suggesting…' : job.error ? 'Suggest failed' : 'Suggest'}
    </Button>
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
        {(d.key === 'style_guide' || d.key === 'style_suggested') && <StyleSuggest series={series} book={book} onDone={doc.reload} />}
        {LAYER_OF[d.key] && <WriteAgain series={series} book={book} docKey={d.key} />}
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
                  {d.key === 'style_guide' && <SuggestRow series={series} book={book} onDone={list.reload} />}
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
