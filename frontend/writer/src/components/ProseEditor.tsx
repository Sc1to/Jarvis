import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { runJob } from '@/lib/jobs'
import { API } from '@/lib/api'
import { Loader2, Expand, RotateCcw, FileText } from 'lucide-react'

interface Props {
  bookId: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  rows?: number
}

/**
 * Editable scene prose with the Expand / Rephrase / Notes text-op toolbar.
 * Text ops rewrite the local value only — the parent decides when to persist it.
 * Give it a `key` per scene so notes and rephrase state reset on scene change.
 */
export default function ProseEditor({ bookId, value, onChange, disabled = false, rows = 16 }: Props) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [showRephrase, setShowRephrase] = useState(false)
  const [instruction, setInstruction] = useState('')

  const busy = running || disabled

  async function withRunning(fn: () => Promise<void>) {
    setRunning(true)
    setError(null)
    try { await fn() }
    catch (e) { setError(String(e)) }
    finally { setRunning(false) }
  }

  const doExpand = () => withRunning(async () => {
    const state = await runJob(`${API}/books/${bookId}/text-ops/expand`, { scene_prose: value })
    if (state.status === 'done' && state.result) onChange(state.result)
    else if (state.status === 'error') setError(state.error ?? 'Expand failed')
  })

  const doRephrase = () => withRunning(async () => {
    const state = await runJob(`${API}/books/${bookId}/text-ops/rephrase`, { scene_prose: value, instruction })
    if (state.status === 'done' && state.result) onChange(state.result)
    else if (state.status === 'error') setError(state.error ?? 'Rephrase failed')
    setShowRephrase(false)
    setInstruction('')
  })

  const doNotes = () => withRunning(async () => {
    const resp = await fetch(`${API}/books/${bookId}/text-ops/editorial-notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scene_prose: value }),
    })
    const data = await resp.json()
    if (data.error) setError(data.error)
    else setNotes(data.notes || '')
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1 flex-wrap">
        <span className="text-xs text-muted-foreground mr-1">Edit prose:</span>
        <Button
          variant="outline" size="sm"
          onClick={doExpand}
          disabled={busy || !value.trim()}
          className="h-6 px-2 text-xs gap-1"
        >
          {running ? <Loader2 size={10} className="animate-spin" /> : <Expand size={10} />}
          Expand
        </Button>
        <Button
          variant="outline" size="sm"
          onClick={() => setShowRephrase(v => !v)}
          disabled={busy}
          className="h-6 px-2 text-xs gap-1"
        >
          <RotateCcw size={10} />Rephrase
        </Button>
        <Button
          variant="outline" size="sm"
          onClick={doNotes}
          disabled={busy || !value.trim()}
          className="h-6 px-2 text-xs gap-1"
        >
          {running ? <Loader2 size={10} className="animate-spin" /> : <FileText size={10} />}
          Notes
        </Button>
      </div>

      {showRephrase && (
        <div className="flex gap-2">
          <input
            value={instruction}
            onChange={e => setInstruction(e.target.value)}
            placeholder="e.g. more tense, cut by half, more physical detail…"
            className="flex-1 min-w-0 rounded-md border border-input bg-transparent px-2 py-1 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            onKeyDown={e => e.key === 'Enter' && instruction.trim() && !busy && doRephrase()}
          />
          <Button
            size="sm" variant="outline"
            onClick={doRephrase}
            disabled={!instruction.trim() || busy}
            className="h-7 px-2 text-xs"
          >
            {running ? <Loader2 size={10} className="animate-spin" /> : 'Apply'}
          </Button>
        </div>
      )}

      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        readOnly={busy}
        rows={rows}
        className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm font-serif leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring read-only:opacity-60"
      />

      {error && <p className="text-xs text-destructive">{error}</p>}

      {notes && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap">
          {notes}
        </div>
      )}
    </div>
  )
}
