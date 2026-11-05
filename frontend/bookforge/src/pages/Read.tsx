import { useState } from 'react'
import { bookPath } from '../lib/api'
import { useApi } from '../lib/hooks'
import { Button, Empty, Markdown } from '../components/ui'

export default function Read({ series, book }: { series: string; book: string }) {
  const [partial, setPartial] = useState(false)
  const m = useApi<{ markdown: string }>(`${bookPath(series, book)}/manuscript${partial ? '?partial=true' : ''}`)
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button kind={partial ? 'plain' : 'primary'} onClick={() => setPartial(false)}>Manuscript</Button>
        <Button kind={partial ? 'primary' : 'plain'} onClick={() => setPartial(true)}>Partial</Button>
      </div>
      {m.error && <Empty>{m.error}. Use Assemble on the overview once every scene is accepted.</Empty>}
      {m.data && <article className="rounded-lg border border-slate-200 bg-white p-4 font-serif"><Markdown text={m.data.markdown} /></article>}
    </div>
  )
}
