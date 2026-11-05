import { useState } from 'react'
import { post } from '../lib/api'
import { useAction, useApi } from '../lib/hooks'
import { href } from '../lib/route'
import type { SeriesInfo } from '../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading } from '../components/ui'

export default function SeriesList() {
  const list = useApi<SeriesInfo[]>('/series', 10000)
  const create = useAction()
  const [name, setName] = useState('')
  const [premise, setPremise] = useState('')
  const [open, setOpen] = useState(false)

  const submit = async () => {
    const ok = await create.run(() => post('/series', { name: name.trim(), premise }))
    if (ok) { window.location.hash = href({ series: name.trim(), book: 'b1' }); setOpen(false); setName(''); setPremise('') }
  }

  return (
    <div className="space-y-3">
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
            <div className="mt-2 flex flex-wrap gap-2">
              {s.books.map((b) => (
                <a key={b} href={href({ series: s.name, book: b })} className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50">{b}</a>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
