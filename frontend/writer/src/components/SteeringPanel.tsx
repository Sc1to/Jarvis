import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { API } from '@/lib/api'
import { Loader2, X } from 'lucide-react'

interface Steering {
  target_chapter_words: number | null
  book_notes: string
  chapter_notes: Record<string, string>
}

interface Props {
  bookId: string
  chapter: number | null
  /** Scenes planned for the active chapter, for the per-scene estimate */
  sceneCount: number
  onClose: () => void
}

const inputClass =
  'w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'

/**
 * Per-book length target and standing notes. Notes are sent to the Writer and QA
 * with every scene until removed; the chapter target is split across its scenes.
 */
export default function SteeringPanel({ bookId, chapter, sceneCount, onClose }: Props) {
  const qc = useQueryClient()
  const { data } = useQuery<Steering>({
    queryKey: ['steering', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase3/steering`).then(r => r.json()).then(r => r.data),
  })

  const [target, setTarget] = useState('')
  const [bookNotes, setBookNotes] = useState('')
  const [chapterNotes, setChapterNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    setTarget(data.target_chapter_words ? String(data.target_chapter_words) : '')
    setBookNotes(data.book_notes)
    setChapterNotes(chapter ? data.chapter_notes[String(chapter)] ?? '' : '')
  }, [data, chapter])

  const targetNum = parseInt(target, 10)
  const perScene = targetNum > 0 && sceneCount > 0 ? Math.max(150, Math.round(targetNum / sceneCount)) : null

  async function save() {
    if (!data) return
    setSaving(true)
    setSaved(false)
    setError(null)
    const chapter_notes = { ...data.chapter_notes }
    if (chapter) chapter_notes[String(chapter)] = chapterNotes
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/steering`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_chapter_words: targetNum > 0 ? targetNum : null,
          book_notes: bookNotes,
          chapter_notes,
        }),
      })
      if (!resp.ok) { setError('Save failed'); return }
      await qc.invalidateQueries({ queryKey: ['steering', bookId] })
      await qc.invalidateQueries({ queryKey: ['chapter', bookId] })
      setSaved(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-b border-border bg-muted/20 px-4 sm:px-6 py-4 shrink-0 max-h-[60vh] overflow-y-auto">
      <div className="max-w-2xl mx-auto space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Length &amp; standing notes</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground" title="Close">
            <X size={14} />
          </button>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium">Target words per chapter</label>
          <div className="flex items-center gap-3 flex-wrap">
            <input
              type="number"
              min={0}
              value={target}
              onChange={e => { setTarget(e.target.value); setSaved(false) }}
              placeholder="e.g. 3000"
              className={`${inputClass} w-32`}
            />
            <span className="text-xs text-muted-foreground">
              {perScene
                ? `≈ ${perScene.toLocaleString()} words per scene${chapter ? ` in Chapter ${chapter}` : ''}`
                : 'Not set — scenes aim for about 750 words each'}
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Split evenly across the chapter's scenes. Over-length scenes are trimmed automatically in Auto-write
            and flagged for you in manual writes.
          </p>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium">Whole book</label>
          <textarea
            value={bookNotes}
            onChange={e => { setBookNotes(e.target.value); setSaved(false) }}
            rows={3}
            placeholder="e.g. The reader knows Mary's mission — never restate it. Keep chapters tight; no weather openings."
            className={`${inputClass} resize-y`}
          />
        </div>

        {chapter && (
          <div className="space-y-1">
            <label className="text-xs font-medium">Chapter {chapter} only</label>
            <textarea
              value={chapterNotes}
              onChange={e => { setChapterNotes(e.target.value); setSaved(false) }}
              rows={3}
              placeholder="e.g. Hamid does not learn about the ledger in this chapter. The storm has passed."
              className={`${inputClass} resize-y`}
            />
          </div>
        )}

        <p className="text-[11px] text-muted-foreground">
          Notes are sent to the Writer with every scene and checked by QA, until you remove them. Use them to course-correct:
          fix the direction here, then rewrite or regenerate the affected scenes.
        </p>

        <div className="flex items-center gap-3">
          <Button size="sm" onClick={save} disabled={saving || !data}>
            {saving ? <><Loader2 size={12} className="animate-spin" />Saving…</> : 'Save'}
          </Button>
          {saved && <span className="text-xs text-emerald-500">Saved — applies to the next scene written.</span>}
          {error && <span className="text-xs text-destructive">{error}</span>}
        </div>
      </div>
    </div>
  )
}
