import { useState } from 'react'
import { api, post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { SeriesInfo, TrashItem } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading, fmtTime } from '../components/ui'

export default function SeriesList() {
  const list = useApi<SeriesInfo[]>('/series', 10000)
  const create = useAction()
  const trash = useApi<TrashItem[]>('/trash')
  const del = useAction()
  const [name, setName] = useState('')
  const [premise, setPremise] = useState('')
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState<string | null>(null)  // the series a new book is being added to
  const [bookTitle, setBookTitle] = useState('')
  const [brief, setBrief] = useState('')
  const manage = useAction()

  const submit = async () => {
    const ok = await create.run(() => post('/series', { name: name.trim(), premise }))
    if (ok) { window.location.hash = href({ series: name.trim(), book: 'b1' }); setOpen(false); setName(''); setPremise('') }
  }

  const rename = async (name: string) => {
    const next = window.prompt(`New name for the series "${name}" (lowercase letters, digits, - and _):`, name)
    if (next && next.trim() && next.trim() !== name && (await manage.run(() => post(`/series/${encodeURIComponent(name)}/rename`, { name: next.trim() })))) list.reload()
  }
  const addBook = async (series: string) => {
    let made: { book: string } | null = null
    const ok = await manage.run(async () => { made = await post<{ book: string }>(`/series/${encodeURIComponent(series)}/books`, { title: bookTitle.trim(), brief }) })
    if (ok && made) { window.location.hash = href({ series, book: (made as { book: string }).book }); setAdding(null); setBookTitle(''); setBrief('') }
  }

  const remove = async (name: string) => {
    if (window.confirm(`Move the series "${name}" to the trash? You can restore it from the Trash list on this page.`)
      && (await del.run(() => api(`/series/${encodeURIComponent(name)}`, { method: 'DELETE' })))) { list.reload(); trash.reload() }
  }
  const restore = async (name: string) => { if (await del.run(() => post(`/trash/${encodeURIComponent(name)}/restore`))) { list.reload(); trash.reload() } }
  const emptyTrash = async () => {
    if (window.confirm('Permanently delete everything in the trash? This cannot be undone.') && (await del.run(() => post('/trash/empty')))) trash.reload()
  }

  return (
    <div className="space-y-3">
      <ErrorBanner message={del.error} onClose={del.clear} />
      <ErrorBanner message={manage.error} onClose={manage.clear} />
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Series</h1>
        <Button onClick={() => setOpen(!open)}>{open ? 'Cancel' : 'New series'}</Button>
      </div>
      {open && (
        <Card title="New series">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit() }}>
            <label className="block text-sm">Name
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="harbor-ledger" pattern="[a-z0-9][a-z0-9_\-]*" required
                className="mt-1 w-full rounded-md border border-slate-300 p-2" />
              <span className="text-xs text-slate-500">Lowercase letters, digits, - and _.</span>
            </label>
            <label className="block text-sm">Premise
              <textarea value={premise} onChange={(e) => setPremise(e.target.value)} rows={6} required
                placeholder="A few paragraphs: who, where, what goes wrong."
                className="mt-1 w-full rounded-md border border-slate-300 p-2" />
            </label>
            <ErrorBanner message={create.error} onClose={create.clear} />
            <Button type="submit" kind="primary" disabled={create.busy || !name || !premise.trim()}>{create.busy ? 'Creating…' : 'Create'}</Button>
          </form>
        </Card>
      )}
      {list.error && <ErrorBanner message={list.error} />}
      {list.loading && !list.data && <Loading />}
      {list.data?.length === 0 && <Empty>No series yet. Create one from a premise.</Empty>}
      <ul className="space-y-2">
        {list.data?.map((s) => (
          <li key={s.name} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{s.name}</span>
              {s.busy && <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800">{s.busy.kind} running</span>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {s.books.map((b) => (
                <a key={b} href={href({ series: s.name, book: b })} className="inline-flex min-h-10 items-center rounded-md border border-slate-300 px-3 text-sm hover:bg-slate-50">
                  {s.titles?.[b] ? <>{s.titles[b]} <span className="ml-1 text-xs text-slate-500">({b})</span></> : b}
                </a>
              ))}
              {!s.books.length && <span className="text-xs text-slate-500">no books</span>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button disabled={manage.busy || !!s.busy} onClick={() => { setAdding(adding === s.name ? null : s.name); setBookTitle(''); setBrief('') }}>{adding === s.name ? 'Cancel' : 'Add book'}</Button>
              <Button disabled={manage.busy || !!s.busy} title={s.busy ? 'A job is running on this series' : undefined} onClick={() => rename(s.name)}>Rename</Button>
              <span className="ml-auto"><Button kind="danger" disabled={del.busy || !!s.busy} onClick={() => remove(s.name)} title={s.busy ? 'A job is running on this series' : 'Move to the trash'}>Delete</Button></span>
            </div>
            {adding === s.name && (
              <form className="mt-3 space-y-3 border-t border-slate-100 pt-3" onSubmit={(e) => { e.preventDefault(); void addBook(s.name) }}>
                <label className="block text-sm">Title of the new book
                  <input value={bookTitle} onChange={(e) => setBookTitle(e.target.value)} required maxLength={120} className="mt-1 w-full rounded-md border border-slate-300 p-2" />
                </label>
                <label className="block text-sm">What this book is about
                  <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} required
                    placeholder="A few sentences: what happens to whom in this book. It gets its own north star; the series north star carries over."
                    className="mt-1 w-full rounded-md border border-slate-300 p-2" />
                </label>
                <Button type="submit" kind="primary" disabled={manage.busy || !bookTitle.trim() || !brief.trim()}>{manage.busy ? 'Adding…' : 'Add book'}</Button>
              </form>
            )}
          </li>
        ))}
      </ul>
      {trash.data && trash.data.length > 0 && (
        <Card title={`Trash (${trash.data.length})`} right={<Button kind="danger" disabled={del.busy} onClick={emptyTrash}>Empty trash</Button>}>
          <ul className="divide-y divide-slate-100">
            {trash.data.map((t) => (
              <li key={t.name} className="flex items-center justify-between gap-2 py-2">
                <span className="min-w-0 text-sm">
                  <span className="block truncate font-medium">{t.series}</span>
                  <span className="block text-xs text-slate-500">{t.books.length ? t.books.join(', ') : 'no books'} · deleted {fmtTime(t.deleted)}</span>
                </span>
                <Button disabled={del.busy} onClick={() => restore(t.name)}>Restore</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
