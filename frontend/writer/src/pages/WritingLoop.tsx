import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { runJob, startJob, pollJob, sleep } from '@/lib/jobs'
import { API } from '@/lib/api'
import { Play, CheckCircle, Loader2, Lock, AlertTriangle, Expand, RotateCcw, FileText, Zap, ChevronLeft, ChevronRight } from 'lucide-react'

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
    total_planned: number
    active_chapter_job: { chapter: number; step: 'write' | 'approve'; started_at: string } | null
  }>({
    queryKey: ['phase3-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase3/status`).then(r => r.json()),
    refetchInterval: (query) => query.state.data?.active_chapter_job ? 3000 : false,
  })

  const [activeChapter, setActiveChapter] = useState<number | null>(null)
  const [writing, setWriting] = useState(false)
  const [approving, setApproving] = useState(false)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [chapterDone, setChapterDone] = useState(false)
  const [rewriteScene, setRewriteScene] = useState<number | null>(null)
  const [rewriteDirective, setRewriteDirective] = useState('')
  const [rewriting, setRewriting] = useState(false)
  // Text op panel state
  const [sceneProse, setSceneProse] = useState('')
  const [textOpRunning, setTextOpRunning] = useState(false)
  const [editorialNotes, setEditorialNotes] = useState('')
  const [rephraseInstruction, setRephraseInstruction] = useState('')
  const [showRephrase, setShowRephrase] = useState(false)
  // Beats mode: scenes that should use beat-based expansion on rewrite
  const [beatScenes, setBeatScenes] = useState<Set<number>>(new Set())
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  // ── Auto-write job state (server-side, tab-safe) ──────────────────────────────
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<string | null>(null)
  const [jobLog, setJobLog] = useState<string[]>([])
  const [jobError, setJobError] = useState<string | null>(null)

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

  // When switching chapters, reset writing state (but not if background job is for this chapter)
  useEffect(() => {
    setEvents([])
    setChapterDone(false)
    setRewriteScene(null)
  }, [activeChapter])

  // On mount/status change: detect any running chapter write/approve job and sync UI
  const reconnectRef = useRef(false)
  useEffect(() => {
    if (!status?.active_chapter_job || reconnectRef.current) return
    const aj = status.active_chapter_job
    reconnectRef.current = true
    setActiveChapter(aj.chapter)
    if (aj.step === 'write' && !writing) {
      runWriteChapter(aj.chapter, true)
    } else if (aj.step === 'approve' && !approving) {
      runApproveChapter(aj.chapter, true)
    }
  }, [status?.active_chapter_job?.chapter, status?.active_chapter_job?.step])

  // Pre-fill scene prose when rewrite panel opens
  useEffect(() => {
    if (rewriteScene !== null && chapterData?.content) {
      setSceneProse(extractSceneProse(chapterData.content, rewriteScene))
      setEditorialNotes('')
      setRephraseInstruction('')
      setShowRephrase(false)
    }
  }, [rewriteScene, chapterData?.content])

  function extractSceneProse(content: string, scene: number): string {
    const parts = content.split('## Scene ')
    for (const part of parts.slice(1)) {
      const newlineIdx = part.indexOf('\n')
      if (newlineIdx === -1) continue
      const header = part.slice(0, newlineIdx).trim()
      if (header === String(scene)) {
        return part.slice(newlineIdx + 1).replace(/\n\n---\n\n$/, '').trim()
      }
    }
    return ''
  }

  async function doExpand() {
    if (!sceneProse.trim() || !bookId) return
    setTextOpRunning(true)
    try {
      const state = await runJob(`${API}/books/${bookId}/text-ops/expand`, { scene_prose: sceneProse })
      if (state.status === 'done' && state.result) setSceneProse(state.result)
    } finally {
      setTextOpRunning(false)
    }
  }

  async function doRephrase() {
    if (!sceneProse.trim() || !rephraseInstruction.trim() || !bookId) return
    setTextOpRunning(true)
    try {
      const state = await runJob(`${API}/books/${bookId}/text-ops/rephrase`, { scene_prose: sceneProse, instruction: rephraseInstruction })
      if (state.status === 'done' && state.result) setSceneProse(state.result)
      setShowRephrase(false)
      setRephraseInstruction('')
    } finally {
      setTextOpRunning(false)
    }
  }

  async function doEditorialNotes() {
    if (!sceneProse.trim() || !bookId) return
    setTextOpRunning(true)
    try {
      const resp = await fetch(`${API}/books/${bookId}/text-ops/editorial-notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_prose: sceneProse }),
      })
      const data = await resp.json()
      setEditorialNotes(data.notes || '')
    } finally {
      setTextOpRunning(false)
    }
  }

  function toggleBeats(scene: number) {
    setBeatScenes(prev => {
      const next = new Set(prev)
      next.has(scene) ? next.delete(scene) : next.add(scene)
      return next
    })
  }

  async function runWriteChapter(chapter: number, isReconnect = false) {
    setWriting(true)
    if (!isReconnect) {
      setEvents([])
      setChapterDone(false)
    }

    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/write-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter }),
      })
      if (!resp.ok) return
      const { job_id } = await resp.json()

      let shownCount = 0
      while (true) {
        await sleep(2000)
        const state = await pollJob(job_id)
        const evts = (state.meta?.events as ProgressEvent[] | undefined) ?? []
        if (evts.length > shownCount) {
          setEvents(evts)
          shownCount = evts.length
        }
        if (state.status !== 'running') {
          if (state.status === 'done') {
            setChapterDone(true)
            reconnectRef.current = false
            await refetchStatus()
            await refetchChapter()
          }
          break
        }
      }
    } catch {
      // Connection dropped — background task continues on server
    } finally {
      const st = await refetchStatus()
      if (!st.data?.active_chapter_job) {
        setWriting(false)
        reconnectRef.current = false
      }
    }
  }

  function writeChapter(chapter: number) {
    return runWriteChapter(chapter, false)
  }

  async function runApproveChapter(chapter: number, isReconnect = false) {
    setApproving(true)
    if (!isReconnect) {
      setEvents([])
    }

    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/chapter/${chapter}/approve`, { method: 'POST' })
      if (!resp.ok) return
      const { job_id } = await resp.json()

      let shownCount = 0
      while (true) {
        await sleep(2000)
        const state = await pollJob(job_id)
        const evts = (state.meta?.events as ProgressEvent[] | undefined) ?? []
        if (evts.length > shownCount) {
          setEvents(evts)
          shownCount = evts.length
        }
        if (state.status !== 'running') {
          if (state.status === 'done') {
            reconnectRef.current = false
            await refetchStatus()
            await refetchChapter()
            qc.invalidateQueries({ queryKey: ['bible', bookId] })
          }
          break
        }
      }
    } catch {
      // Connection dropped — background task continues on server
    } finally {
      const st = await refetchStatus()
      if (!st.data?.active_chapter_job) {
        setApproving(false)
        reconnectRef.current = false
      }
    }
  }

  function approveChapter(chapter: number) {
    return runApproveChapter(chapter, false)
  }

  const jobLocalKey = `aw_job_${bookId}`

  function startJobPolling(id: string) {
    if (jobPollRef.current) clearInterval(jobPollRef.current)
    jobPollRef.current = setInterval(async () => {
      try {
        const data = await fetch(`${API}/books/${bookId}/phase3/auto-write/status?job_id=${id}`).then(r => r.json())
        setJobLog(data.log ?? [])
        setJobStatus(data.status)
        setJobError(data.error ?? null)
        if (data.status !== 'running') {
          clearInterval(jobPollRef.current!)
          jobPollRef.current = null
          localStorage.removeItem(jobLocalKey)
          await refetchStatus()
          await refetchChapter()
          qc.invalidateQueries({ queryKey: ['bible', bookId] })
        }
      } catch { /* ignore transient fetch errors */ }
    }, 4000)
  }

  // Clear polling interval on unmount to prevent accumulating intervals across remounts
  useEffect(() => {
    return () => {
      if (jobPollRef.current) {
        clearInterval(jobPollRef.current)
        jobPollRef.current = null
      }
    }
  }, [])

  // Reconnect to a running job if the tab was closed and reopened
  useEffect(() => {
    const stored = localStorage.getItem(jobLocalKey)
    if (!stored) return
    fetch(`${API}/books/${bookId}/phase3/auto-write/status?job_id=${stored}`)
      .then(r => r.json())
      .then(data => {
        if (data.status === 'running') {
          setJobId(stored)
          setJobStatus('running')
          setJobLog(data.log ?? [])
          startJobPolling(stored)
        } else {
          localStorage.removeItem(jobLocalKey)
        }
      })
      .catch(() => localStorage.removeItem(jobLocalKey))
  }, [bookId])

  async function startAutoWrite() {
    const data = await fetch(`${API}/books/${bookId}/phase3/auto-write`, { method: 'POST' }).then(r => r.json())
    const id = data.job_id
    localStorage.setItem(jobLocalKey, id)
    setJobId(id)
    setJobStatus('running')
    setJobLog([])
    setJobError(null)
    startJobPolling(id)
  }

  async function cancelAutoWrite() {
    if (!jobId) return
    await fetch(`${API}/books/${bookId}/phase3/auto-write/cancel?job_id=${jobId}`, { method: 'POST' })
    setJobStatus('cancelled')
    clearInterval(jobPollRef.current!)
    jobPollRef.current = null
    localStorage.removeItem(jobLocalKey)
  }

  async function doRewrite(chapter: number, scene: number) {
    if (!rewriteDirective.trim()) return
    setRewriting(true)
    setEvents([])

    const useBeats = beatScenes.has(scene)
    const endpoint = useBeats
      ? `${API}/books/${bookId}/phase3/chapter/${chapter}/scene/${scene}/write-with-beats`
      : `${API}/books/${bookId}/phase3/chapter/${chapter}/scene/${scene}/rewrite`

    try {
      const jobId = await startJob(endpoint, { directive: rewriteDirective })
      let shownCount = 0
      while (true) {
        await sleep(1000)
        const state = await pollJob(jobId)
        const evts = (state.meta?.events as ProgressEvent[] | undefined) ?? []
        if (evts.length > shownCount) {
          setEvents(evts)
          shownCount = evts.length
        }
        if (state.status !== 'running') {
          if (state.status === 'done') {
            setRewriteScene(null)
            setRewriteDirective('')
            await refetchChapter()
          }
          break
        }
      }
    } finally {
      setRewriting(false)
    }
  }

  const chapters = status?.chapters ?? []
  const nextChapter = status?.next_chapter ?? null
  const totalPlanned = status?.total_planned ?? 0
  const isLocked = !status?.phase2_approved

  const meta = chapterData?.meta
  const scenes = meta?.scenes ?? []
  const isWritten = !!chapterData?.content
  const isApproved = meta?.status === 'approved'
  const autoWriting = jobStatus === 'running'
  const busy = writing || approving || rewriting || autoWriting

  // Show writing progress OR chapter content
  const showProgress = writing || approving || (events.length > 0 && !chapterDone)
  const showProse = isWritten && !showProgress

  return (
    <div className="flex h-full">
      {/* Left: chapter list — hidden on mobile */}
      <div className={cn(
        'hidden md:flex md:flex-col md:shrink-0 border-r border-border transition-all duration-200',
        leftCollapsed ? 'md:w-8' : 'md:w-44',
      )}>
        {leftCollapsed ? (
          <button
            onClick={() => setLeftCollapsed(false)}
            className="flex-1 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Show chapters"
          >
            <ChevronRight size={14} />
          </button>
        ) : (
          <>
            <div className="px-3 py-4 border-b border-border flex items-center justify-between gap-1">
              <div className="min-w-0">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Chapters</h3>
                {totalPlanned > 0 && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {chapters.filter(c => c.approved).length} / {totalPlanned} approved
                  </p>
                )}
              </div>
              <button
                onClick={() => setLeftCollapsed(true)}
                className="p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded transition-colors"
                title="Hide chapters"
              >
                <ChevronLeft size={13} />
              </button>
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
          </>
        )}
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

          {/* Auto-write all */}
          {!isLocked && (
            autoWriting
              ? <button
                  onClick={cancelAutoWrite}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-destructive text-destructive hover:bg-destructive/10 transition-colors"
                >
                  <Loader2 size={11} className="animate-spin" />Stop
                </button>
              : <button
                  onClick={startAutoWrite}
                  disabled={busy}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Play size={11} />Auto-write all
                </button>
          )}

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

        {(jobLog.length > 0 || jobError) && !writing && !approving && (
          <div className="px-6 py-3 space-y-1.5 border-t border-border shrink-0">
            {jobError && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                <span className="flex-1">⚠ {jobError}</span>
                <button onClick={() => setJobError(null)} className="shrink-0 hover:opacity-70 leading-none">✕</button>
              </div>
            )}
            {jobLog.length > 0 && (
              <pre className="text-xs font-mono text-muted-foreground bg-muted/30 rounded-md px-3 py-2 max-h-24 overflow-y-auto whitespace-pre-wrap">
                {jobLog.join('\n')}{autoWriting && <span className="animate-pulse"> ▋</span>}
              </pre>
            )}
          </div>
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
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setRewriteScene(null)}>← Back</Button>
                    <span className="text-sm font-medium">Scene {rewriteScene}</span>
                  </div>

                  {/* Prose textarea + text op toolbar */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-xs text-muted-foreground mr-1">Edit prose:</span>
                      <Button
                        variant="outline" size="sm"
                        onClick={doExpand}
                        disabled={textOpRunning || !sceneProse.trim()}
                        className="h-6 px-2 text-xs gap-1"
                      >
                        {textOpRunning ? <Loader2 size={10} className="animate-spin" /> : <Expand size={10} />}
                        Expand
                      </Button>
                      <Button
                        variant="outline" size="sm"
                        onClick={() => setShowRephrase(v => !v)}
                        disabled={textOpRunning}
                        className="h-6 px-2 text-xs gap-1"
                      >
                        <RotateCcw size={10} />Rephrase
                      </Button>
                      <Button
                        variant="outline" size="sm"
                        onClick={doEditorialNotes}
                        disabled={textOpRunning || !sceneProse.trim()}
                        className="h-6 px-2 text-xs gap-1"
                      >
                        {textOpRunning ? <Loader2 size={10} className="animate-spin" /> : <FileText size={10} />}
                        Notes
                      </Button>
                    </div>

                    {showRephrase && (
                      <div className="flex gap-2">
                        <input
                          value={rephraseInstruction}
                          onChange={e => setRephraseInstruction(e.target.value)}
                          placeholder="e.g. more tense, cut by half, more physical detail…"
                          className="flex-1 rounded-md border border-input bg-transparent px-2 py-1 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          onKeyDown={e => e.key === 'Enter' && doRephrase()}
                        />
                        <Button
                          size="sm" variant="outline"
                          onClick={doRephrase}
                          disabled={!rephraseInstruction.trim() || textOpRunning}
                          className="h-7 px-2 text-xs"
                        >
                          {textOpRunning ? <Loader2 size={10} className="animate-spin" /> : 'Apply'}
                        </Button>
                      </div>
                    )}

                    <textarea
                      value={sceneProse}
                      onChange={e => setSceneProse(e.target.value)}
                      rows={10}
                      className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm font-serif leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />

                    {editorialNotes && (
                      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap">
                        {editorialNotes}
                      </div>
                    )}
                  </div>

                  <Separator />

                  {/* Writer-agent rewrite */}
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">Or rewrite via Writer agent:</p>
                    <textarea
                      value={rewriteDirective}
                      onChange={e => setRewriteDirective(e.target.value)}
                      placeholder="Describe what to change in this scene…"
                      rows={2}
                      className="w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        onClick={() => doRewrite(activeChapter, rewriteScene)}
                        disabled={!rewriteDirective.trim() || rewriting}
                        className="gap-2"
                      >
                        {rewriting ? <><Loader2 size={12} className="animate-spin" />Rewriting…</> : 'Rewrite scene'}
                      </Button>
                      <button
                        onClick={() => toggleBeats(rewriteScene)}
                        className={cn(
                          'flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors',
                          beatScenes.has(rewriteScene)
                            ? 'border-amber-400 text-amber-500 bg-amber-50 dark:bg-amber-950/20'
                            : 'border-border text-muted-foreground hover:border-foreground'
                        )}
                        title="Use beat-based expansion for this rewrite"
                      >
                        <Zap size={10} />Beats
                      </button>
                    </div>
                  </div>
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
      <div className={cn(
        'hidden md:flex md:flex-col md:shrink-0 border-l border-border transition-all duration-200',
        rightCollapsed ? 'md:w-8' : 'md:w-72',
      )}>
        {rightCollapsed ? (
          <button
            onClick={() => setRightCollapsed(false)}
            className="flex-1 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Show scenes"
          >
            <ChevronLeft size={14} />
          </button>
        ) : (
          <>
            <div className="px-4 py-4 border-b border-border flex items-center justify-between gap-2">
              <div className="min-w-0">
                <h3 className="text-sm font-medium">Scenes</h3>
                <p className="text-xs text-muted-foreground">
                  {scenes.length > 0 ? `${scenes.length} scenes · ${scenes.reduce((a, s) => a + s.word_count, 0).toLocaleString()} words` : 'No scenes yet'}
                </p>
              </div>
              <button
                onClick={() => setRightCollapsed(true)}
                className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded transition-colors"
                title="Hide scenes"
              >
                <ChevronRight size={13} />
              </button>
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
          </>
        )}
      </div>
    </div>
  )
}
