import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'
import { API } from '@/lib/api'
import { Play, CheckCircle, Loader2, Lock, AlertTriangle } from 'lucide-react'

interface ChapterSummary {
  chapter: number
  status: 'written' | 'approved' | 'unknown'
  scene_count: number
  approved: boolean
  bible_updated: boolean
}

interface SceneResult {
  scene: number
  brief: string
  entry_state: string
  exit_state: string
  attempts: number
  qa_pass: boolean
  qa_notes: string
  word_count: number
}

interface ChapterMeta {
  chapter: number
  scene_count: number
  scenes: SceneResult[]
  status: string
  approved_at: string | null
  bible_updated: boolean
}

interface ProgressEvent {
  type: string
  scene?: number
  total?: number
  attempt?: number
  brief?: string
  pass?: boolean
  notes?: string
  issues?: { type: string; description: string; severity: string }[]
  word_count?: number
  scene_count?: number
  message?: string
  entity_count?: number
}


function EventFeed({ events }: { events: ProgressEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events.length])

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1 font-mono text-xs">
      {events.map((ev, i) => {
        if (ev.type === 'plan_done') return (
          <p key={i} className="text-muted-foreground">Extracted {ev.scene_count} scenes</p>
        )
        if (ev.type === 'scene_start') return (
          <p key={i} className="text-foreground font-medium mt-2">
            Scene {ev.scene}/{ev.total} — {ev.brief}
          </p>
        )
        if (ev.type === 'rewrite_start') return (
          <p key={i} className="text-amber-500">↩ Rewrite scene {ev.scene} (attempt {ev.attempt})</p>
        )
        if (ev.type === 'scene_written') return (
          <p key={i} className="text-muted-foreground">Written — {ev.word_count} words</p>
        )
        if (ev.type === 'qa_start') return (
          <p key={i} className="text-muted-foreground">QA checking…</p>
        )
        if (ev.type === 'qa_result') return (
          <p key={i} className={ev.pass ? 'text-emerald-500' : 'text-red-500'}>
            QA {ev.pass ? 'pass' : 'fail'} — {ev.notes}
          </p>
        )
        if (ev.type === 'chapter_done') return (
          <p key={i} className="text-emerald-500 font-medium mt-2">
            ✓ Chapter {ev.scene} complete — {ev.scene_count} scenes
          </p>
        )
        if (ev.type === 'status') return (
          <p key={i} className="text-muted-foreground">{ev.message}</p>
        )
        if (ev.type === 'saved') return (
          <p key={i} className="text-emerald-500">✓ Saved — {ev.entity_count} entities in ledger</p>
        )
        if (ev.type === 'error') return (
          <p key={i} className="text-red-500">⚠ {ev.message}</p>
        )
        return null
      })}
      <div ref={bottomRef} />
    </div>
  )
}

export default function WritingLoopPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()

  const { data: status, refetch: refetchStatus } = useQuery<{
    phase2_approved: boolean
    chapters: ChapterSummary[]
    next_chapter: number | null
  }>({
    queryKey: ['phase3-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase3/status`).then(r => r.json()),
  })

  const [activeChapter, setActiveChapter] = useState<number | null>(null)
  const [writing, setWriting] = useState(false)
  const [approving, setApproving] = useState(false)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [chapterDone, setChapterDone] = useState(false)
  const [rewriteScene, setRewriteScene] = useState<number | null>(null)
  const [rewriteDirective, setRewriteDirective] = useState('')
  const [rewriting, setRewriting] = useState(false)

  const { data: chapterData, refetch: refetchChapter } = useQuery<{ chapter: number; content: string; meta: ChapterMeta } | null>({
    queryKey: ['chapter', bookId, activeChapter],
    queryFn: () => activeChapter
      ? fetch(`${API}/books/${bookId}/phase3/chapter/${activeChapter}`).then(r => r.json())
      : Promise.resolve(null),
    enabled: activeChapter !== null,
  })

  // Auto-select first unwritten chapter on load
  useEffect(() => {
    if (!status || activeChapter !== null) return
    if (status.chapters.length > 0) {
      setActiveChapter(status.chapters[0].chapter)
    } else if (status.next_chapter) {
      setActiveChapter(status.next_chapter)
    }
  }, [status])

  // When switching chapters, reset writing state
  useEffect(() => {
    setEvents([])
    setChapterDone(false)
    setRewriteScene(null)
  }, [activeChapter])

  async function writeChapter(chapter: number) {
    setWriting(true)
    setEvents([])
    setChapterDone(false)

    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/write-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter }),
      })
      for await (const ev of readSSE(resp)) {
        const event = ev as ProgressEvent
        if (event.type !== 'token') {
          setEvents(prev => [...prev, event])
        }
        if (event.type === 'chapter_done') {
          setChapterDone(true)
          await refetchStatus()
          await refetchChapter()
        }
      }
    } finally {
      setWriting(false)
    }
  }

  async function approveChapter(chapter: number) {
    setApproving(true)
    setEvents([])

    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/chapter/${chapter}/approve`, { method: 'POST' })
      for await (const ev of readSSE(resp)) {
        const event = ev as ProgressEvent
        if (event.type !== 'token') {
          setEvents(prev => [...prev, event])
        }
        if (event.type === 'saved') {
          await refetchStatus()
          await refetchChapter()
          qc.invalidateQueries({ queryKey: ['bible', bookId] })
        }
      }
    } finally {
      setApproving(false)
    }
  }

  async function doRewrite(chapter: number, scene: number) {
    if (!rewriteDirective.trim()) return
    setRewriting(true)
    setEvents([])

    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/chapter/${chapter}/scene/${scene}/rewrite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directive: rewriteDirective }),
      })
      for await (const ev of readSSE(resp)) {
        const event = ev as ProgressEvent
        if (event.type !== 'token') {
          setEvents(prev => [...prev, event])
        }
        if (event.type === 'saved') {
          setRewriteScene(null)
          setRewriteDirective('')
          await refetchChapter()
        }
      }
    } finally {
      setRewriting(false)
    }
  }

  const chapters = status?.chapters ?? []
  const nextChapter = status?.next_chapter ?? null
  const isLocked = !status?.phase2_approved

  const meta = chapterData?.meta
  const scenes = meta?.scenes ?? []
  const isWritten = !!chapterData?.content
  const isApproved = meta?.status === 'approved'
  const busy = writing || approving || rewriting

  // Show writing progress OR chapter content
  const showProgress = writing || approving || (events.length > 0 && !chapterDone)
  const showProse = isWritten && !showProgress

  return (
    <div className="flex h-full">
      {/* Left: chapter list — hidden on mobile */}
      <div className="hidden md:flex md:flex-col md:w-44 md:shrink-0 border-r border-border">
        <div className="px-3 py-4 border-b border-border">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Chapters</h3>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {isLocked && (
            <p className="px-3 py-2 text-xs text-muted-foreground italic">Approve Phase 2 first.</p>
          )}
          {chapters.map(ch => (
            <button
              key={ch.chapter}
              onClick={() => !busy && setActiveChapter(ch.chapter)}
              disabled={busy}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors',
                activeChapter === ch.chapter ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/50',
                busy && 'opacity-50 cursor-not-allowed',
              )}
            >
              <span className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                ch.approved ? 'bg-emerald-500' : 'bg-amber-400',
              )} />
              Chapter {ch.chapter}
            </button>
          ))}
          {nextChapter && !isLocked && (
            <>
              {chapters.length > 0 && <Separator className="my-2" />}
              <button
                onClick={() => !busy && setActiveChapter(nextChapter)}
                disabled={busy}
                className={cn(
                  'w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted/50',
                  activeChapter === nextChapter && 'bg-accent text-accent-foreground',
                )}
              >
                + Chapter {nextChapter}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-border shrink-0">
          {/* Mobile chapter picker */}
          {!isLocked && (
            <select
              className="md:hidden text-xs bg-transparent border border-border rounded px-2 py-1 text-foreground disabled:opacity-50 shrink-0"
              value={activeChapter ?? ''}
              onChange={e => setActiveChapter(e.target.value ? Number(e.target.value) : null)}
              disabled={busy}
            >
              {!activeChapter && <option value="">Chapter…</option>}
              {chapters.map(ch => (
                <option key={ch.chapter} value={ch.chapter}>Ch.{ch.chapter}{ch.approved ? ' ✓' : ''}</option>
              ))}
              {nextChapter && <option value={nextChapter}>+ Ch.{nextChapter}</option>}
            </select>
          )}
          <div className="flex-1 min-w-0">
            <h2 className="font-semibold text-sm truncate">
              {activeChapter ? `Chapter ${activeChapter}` : 'Writing Loop'}
            </h2>
            <p className="text-xs text-muted-foreground">
              {isApproved ? 'Approved' : meta ? `${scenes.length} scenes` : activeChapter === nextChapter ? 'Not yet written' : ''}
            </p>
          </div>

          {activeChapter !== null && (
            <>
              {/* Write button (first write or already written chapter — can re-run) */}
              {activeChapter === nextChapter && !writing && (
                <Button size="sm" onClick={() => writeChapter(activeChapter)} className="gap-2" disabled={busy}>
                  <Play size={13} />Write Chapter {activeChapter}
                </Button>
              )}
              {writing && (
                <Badge variant="secondary" className="gap-1.5">
                  <Loader2 size={12} className="animate-spin" />Writing…
                </Badge>
              )}
              {/* Approve button — shown for written, unapproved chapters */}
              {isWritten && !isApproved && !approving && !writing && (
                <Button size="sm" onClick={() => approveChapter(activeChapter)} className="gap-2" disabled={busy}>
                  <Lock size={13} />Approve Chapter
                </Button>
              )}
              {approving && (
                <Badge variant="secondary" className="gap-1.5">
                  <Loader2 size={12} className="animate-spin" />Updating Bible…
                </Badge>
              )}
              {isApproved && <Badge variant="success">Approved</Badge>}
            </>
          )}
        </div>

        {/* Body */}
        {!activeChapter && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-muted-foreground">
              {isLocked ? 'Complete Phase 2 to unlock writing.' : 'Select a chapter to begin.'}
            </p>
          </div>
        )}

        {activeChapter && showProgress && (
          <EventFeed events={events} />
        )}

        {activeChapter && !showProgress && !isWritten && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-2">
              <p className="text-sm text-muted-foreground">Chapter {activeChapter} not yet written.</p>
              <Button size="sm" onClick={() => writeChapter(activeChapter)} disabled={busy} className="gap-2">
                <Play size={13} />Write now
              </Button>
            </div>
          </div>
        )}

        {activeChapter && showProse && (
          <div className="flex-1 overflow-y-auto px-8 py-6">
            <div className="max-w-2xl mx-auto">
              {rewriteScene !== null ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setRewriteScene(null)}>← Back</Button>
                    <span className="text-sm font-medium">Rewrite Scene {rewriteScene}</span>
                  </div>
                  <textarea
                    value={rewriteDirective}
                    onChange={e => setRewriteDirective(e.target.value)}
                    placeholder="Describe what to change in this scene…"
                    rows={3}
                    className="w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                  <Button
                    size="sm"
                    onClick={() => doRewrite(activeChapter, rewriteScene)}
                    disabled={!rewriteDirective.trim() || rewriting}
                    className="gap-2"
                  >
                    {rewriting ? <><Loader2 size={12} className="animate-spin" />Rewriting…</> : 'Rewrite scene'}
                  </Button>
                </div>
              ) : (
                <pre className="whitespace-pre-wrap font-serif text-base leading-relaxed text-foreground">
                  {chapterData?.content}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Right sidebar: scenes + QA — hidden on mobile */}
      <div className="hidden md:flex md:flex-col md:w-72 md:shrink-0 border-l border-border">
        <div className="px-4 py-4 border-b border-border">
          <h3 className="text-sm font-medium">Scenes</h3>
          <p className="text-xs text-muted-foreground">
            {scenes.length > 0 ? `${scenes.length} scenes · ${scenes.reduce((a, s) => a + s.word_count, 0).toLocaleString()} words` : 'No scenes yet'}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
          {scenes.length === 0 && (
            <p className="text-xs text-muted-foreground italic px-1">Write the chapter to see scene details.</p>
          )}
          {scenes.map(s => (
            <Card key={s.scene} className={cn('bg-muted/20', rewriteScene === s.scene && 'ring-1 ring-ring')}>
              <CardContent className="px-3 py-2 space-y-1.5">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-medium">Scene {s.scene}</span>
                  <div className="flex items-center gap-1">
                    {s.qa_pass
                      ? <CheckCircle size={11} className="text-emerald-500" />
                      : <AlertTriangle size={11} className="text-amber-400" />
                    }
                    {s.attempts > 1 && (
                      <Badge variant="outline" className="text-[10px] px-1 py-0">{s.attempts} attempts</Badge>
                    )}
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground leading-snug line-clamp-2">{s.brief}</p>
                {s.qa_notes && (
                  <p className="text-[10px] text-muted-foreground/70 italic line-clamp-2">{s.qa_notes}</p>
                )}
                <div className="flex items-center justify-between pt-0.5">
                  <span className="text-[10px] text-muted-foreground">{s.word_count.toLocaleString()} words</span>
                  {isWritten && !isApproved && (
                    <button
                      onClick={() => { setRewriteScene(s.scene); setRewriteDirective('') }}
                      className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Rewrite
                    </button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        {isApproved && (
          <div className="px-4 py-3 border-t border-border">
            <div className="flex items-center gap-2 text-xs text-emerald-500">
              <CheckCircle size={12} />
              <span>Bible updated — Chapter {activeChapter} locked</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
