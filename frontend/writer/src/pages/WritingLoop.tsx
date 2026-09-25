import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { startJob, pollJob, sleep } from '@/lib/jobs'
import { API } from '@/lib/api'
import { Play, CheckCircle, Loader2, Lock, AlertTriangle, Zap, ChevronLeft, ChevronRight, Save, PenLine, SlidersHorizontal, RefreshCw } from 'lucide-react'
import ProseEditor from '@/components/ProseEditor'
import SteeringPanel from '@/components/SteeringPanel'
import QaIssuesList, { type QaIssue } from '@/components/QaIssuesList'
import CopyButton from '@/components/CopyButton'

interface ChapterSummary {
  chapter: number
  status: 'written' | 'approved' | 'in_progress' | 'unknown'
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
  qa_issues?: QaIssue[]
  author_edited?: boolean
  word_target?: number
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
  issues?: QaIssue[]
  word_count?: number
  word_target?: number
  remaining?: number
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
          <p key={i} className="text-muted-foreground">
            Written — {ev.word_count} words{ev.word_target ? ` (target ~${ev.word_target})` : ''}
          </p>
        )
        if (ev.type === 'qa_start') return (
          <p key={i} className="text-muted-foreground">QA checking…</p>
        )
        if (ev.type === 'qa_result') return (
          <div key={i}>
            <p className={ev.pass ? 'text-emerald-500' : 'text-red-500'}>
              QA {ev.pass ? 'pass' : 'fail'} — {ev.notes}
            </p>
            {!ev.pass && (ev.issues ?? []).map((iss, j) => (
              <p key={j} className="pl-4 text-muted-foreground">· [{iss.severity}] {iss.description}</p>
            ))}
          </div>
        )
        if (ev.type === 'paused') return (
          <p key={i} className="text-sky-500 font-medium mt-2">
            ⏸ Paused after scene {ev.scene} — {ev.remaining} to go. Review, edit or rewrite it, then Continue writing.
          </p>
        )
        if (ev.type === 'qa_held') return (
          <p key={i} className="text-amber-500">⏸ Scene {ev.scene} kept for your review — no automatic retry</p>
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

function QaFindings({ scene, onUseAsDirective }: { scene: SceneResult; onUseAsDirective: (text: string) => void }) {
  const issues = scene.qa_issues ?? []
  const directive = [
    'Revise this scene to address the QA findings below. Make targeted, minimal changes — correct only what each finding flags and leave the rest of the prose as it is.',
    '',
    ...issues.map(i => {
      const lines = [`- ${i.description}`]
      if (i.quote) lines.push(`  Offending text: "${i.quote}"`)
      if (i.fix) lines.push(`  Fix: ${i.fix}`)
      return lines.join('\n')
    }),
    ...(issues.length === 0 && scene.qa_notes ? [`- ${scene.qa_notes}`] : []),
  ].join('\n')

  return (
    <div className="rounded-md border border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20 px-3 py-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
        <AlertTriangle size={12} />
        QA flagged this scene{scene.attempts > 1 ? ` (after ${scene.attempts} attempts)` : ''}
        {scene.author_edited && <span className="font-normal text-muted-foreground">— on the agent draft, before your edits</span>}
      </div>
      {scene.qa_notes && <p className="text-xs text-muted-foreground">{scene.qa_notes}</p>}
      <QaIssuesList issues={issues} />
      <p className="text-[11px] text-muted-foreground pt-0.5">
        Keep it as is, edit it below, or{' '}
        <button onClick={() => onUseAsDirective(directive)} className="underline hover:text-foreground">
          send these findings to the Writer agent
        </button>.
      </p>
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
  const [savedProse, setSavedProse] = useState('')
  const [savingProse, setSavingProse] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Beats mode: scenes that should use beat-based expansion on rewrite
  const [beatScenes, setBeatScenes] = useState<Set<number>>(new Set())
  const [showSteering, setShowSteering] = useState(false)
  const pauseKey = `pause_each_scene_${bookId}`
  const [pauseEachScene, setPauseEachScene] = useState(() => {
    try { return localStorage.getItem(pauseKey) === 'true' } catch { return false }
  })
  function togglePauseEachScene(v: boolean) {
    setPauseEachScene(v)
    try { localStorage.setItem(pauseKey, String(v)) } catch { /* storage unavailable */ }
  }
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  // ── Auto-write job state (server-side, tab-safe) ──────────────────────────────
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<string | null>(null)
  const [jobLog, setJobLog] = useState<string[]>([])
  const [jobError, setJobError] = useState<string | null>(null)

  const { data: chapterData, refetch: refetchChapter } = useQuery<{ chapter: number; content: string; meta: ChapterMeta; scene_word_target?: number } | null>({
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

  // Pre-fill scene prose when the edit panel opens (or the chapter reloads after a save/rewrite)
  useEffect(() => {
    if (rewriteScene !== null && chapterData?.content) {
      const prose = extractSceneProse(chapterData.content, rewriteScene)
      setSceneProse(prose)
      setSavedProse(prose)
      setSaveError(null)
    }
  }, [rewriteScene, chapterData?.content])

  const proseDirty = rewriteScene !== null && sceneProse !== savedProse

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

  async function saveSceneProse(chapter: number, scene: number) {
    if (!sceneProse.trim()) return
    setSavingProse(true)
    setSaveError(null)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase3/chapter/${chapter}/scene/${scene}/prose`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: sceneProse }),
      })
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}))
        setSaveError(d.detail ?? 'Save failed')
        return
      }
      setSavedProse(sceneProse)
      await refetchChapter()
    } catch (e) {
      setSaveError(String(e))
    } finally {
      setSavingProse(false)
    }
  }

  function closeSceneEditor() {
    if (proseDirty && !window.confirm('Discard unsaved edits to this scene?')) return
    setRewriteScene(null)
  }

  function toggleBeats(scene: number) {
    setBeatScenes(prev => {
      const next = new Set(prev)
      next.has(scene) ? next.delete(scene) : next.add(scene)
      return next
    })
  }

  // Starts (or reattaches to) a chapter write job. `regenerateAfter` replaces every scene after that one.
  async function runWriteChapter(chapter: number, isReconnect = false, regenerateAfter?: number) {
    setWriting(true)
    if (!isReconnect) {
      setEvents([])
      setChapterDone(false)
    }

    try {
      const resp = regenerateAfter !== undefined
        ? await fetch(`${API}/books/${bookId}/phase3/chapter/${chapter}/regenerate-after/${regenerateAfter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pause_after_scene: pauseEachScene }),
          })
        : await fetch(`${API}/books/${bookId}/phase3/write-chapter`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter, pause_after_scene: pauseEachScene }),
          })
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}))
        setEvents([{ type: 'error', message: d.detail ?? 'Could not start writing' }])
        return
      }
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

  function regenerateAfter(chapter: number, scene: number) {
    const later = scenes.filter(s => s.scene > scene).map(s => s.scene)
    if (proseDirty) { window.alert('Save or revert your edits to this scene first.'); return }
    if (!window.confirm(`Replace scene${later.length === 1 ? '' : 's'} ${later.join(', ')} with new ones written from Scene ${scene} as it is now?`)) return
    setRewriteScene(null)
    return runWriteChapter(chapter, false, scene)
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
  const isInProgress = meta?.status === 'in_progress'
  const sceneWordTarget = chapterData?.scene_word_target
  const flaggedScenes = scenes.filter(s => !s.qa_pass)
  const editingSceneMeta = rewriteScene !== null ? scenes.find(s => s.scene === rewriteScene) : undefined
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
        <div className="flex items-center gap-x-3 gap-y-2 flex-wrap px-4 sm:px-5 py-3 border-b border-border shrink-0">
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
              {isApproved ? 'Approved'
                : isInProgress ? `In progress — ${scenes.length} of ${meta?.scene_count ?? '?'} scenes`
                : meta ? `${scenes.length} scenes · ${scenes.reduce((a, s) => a + s.word_count, 0).toLocaleString()} words`
                : activeChapter === nextChapter ? 'Not yet written' : ''}
            </p>
          </div>

          <button
            onClick={() => setShowSteering(v => !v)}
            className={cn(
              'flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-colors',
              showSteering ? 'border-foreground text-foreground' : 'border-border text-muted-foreground hover:text-foreground hover:border-foreground',
            )}
            title="Length target and standing notes for the Writer"
          >
            <SlidersHorizontal size={11} />Length &amp; notes
          </button>

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
              {(activeChapter === nextChapter || isInProgress) && !writing && (
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none" title="Stop after each new scene so you can review, edit or rewrite it before the next one is written">
                  <input
                    type="checkbox"
                    checked={pauseEachScene}
                    onChange={e => togglePauseEachScene(e.target.checked)}
                    className="accent-current"
                  />
                  Pause each scene
                </label>
              )}
              {/* Write button (first write or already written chapter — can re-run) */}
              {activeChapter === nextChapter && !writing && (
                <Button size="sm" onClick={() => writeChapter(activeChapter)} className="gap-2" disabled={busy}>
                  <Play size={13} />Write Chapter {activeChapter}
                </Button>
              )}
              {isInProgress && !writing && (
                <Button size="sm" onClick={() => writeChapter(activeChapter)} className="gap-2" disabled={busy}>
                  <Play size={13} />Continue writing
                </Button>
              )}
              {writing && (
                <Badge variant="secondary" className="gap-1.5">
                  <Loader2 size={12} className="animate-spin" />Writing…
                </Badge>
              )}
              {/* Approve button — shown for written, unapproved chapters */}
              {isWritten && !isApproved && !isInProgress && !approving && !writing && (
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

        {showSteering && bookId && (
          <SteeringPanel
            bookId={bookId}
            chapter={activeChapter}
            sceneCount={meta?.scene_count ?? scenes.length}
            onClose={() => setShowSteering(false)}
          />
        )}

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
              <div className="space-y-1">
                <div className="flex justify-end">
                  <CopyButton text={jobLog.join('\n')} />
                </div>
                <pre className="text-xs font-mono text-muted-foreground bg-muted/30 rounded-md px-3 py-2 max-h-24 overflow-y-auto whitespace-pre-wrap">
                  {jobLog.join('\n')}{autoWriting && <span className="animate-pulse"> ▋</span>}
                </pre>
              </div>
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
                    <Button variant="ghost" size="sm" onClick={closeSceneEditor}>← Back</Button>
                    <span className="text-sm font-medium">Scene {rewriteScene}</span>
                  </div>

                  {editingSceneMeta && !editingSceneMeta.qa_pass && (
                    <QaFindings scene={editingSceneMeta} onUseAsDirective={setRewriteDirective} />
                  )}

                  {/* Hand-editable prose + text op toolbar */}
                  <ProseEditor
                    key={`${activeChapter}-${rewriteScene}`}
                    bookId={bookId!}
                    value={sceneProse}
                    onChange={setSceneProse}
                    disabled={savingProse || rewriting}
                    targetWords={editingSceneMeta?.word_target ?? sceneWordTarget}
                  />
                  <div className="flex items-center gap-2 flex-wrap">
                    <Button
                      size="sm"
                      onClick={() => saveSceneProse(activeChapter, rewriteScene)}
                      disabled={!proseDirty || !sceneProse.trim() || savingProse || rewriting}
                      className="gap-2"
                    >
                      {savingProse ? <><Loader2 size={12} className="animate-spin" />Saving…</> : <><Save size={12} />Save edits</>}
                    </Button>
                    {proseDirty && !savingProse && (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => setSceneProse(savedProse)}>Revert</Button>
                        <span className="text-xs text-amber-500">Unsaved changes</span>
                      </>
                    )}
                    {saveError && <span className="text-xs text-destructive">{saveError}</span>}
                    {scenes.some(s => s.scene > rewriteScene) && (
                      <Button
                        variant="outline" size="sm"
                        onClick={() => regenerateAfter(activeChapter, rewriteScene)}
                        disabled={savingProse || rewriting || busy}
                        className="gap-2 ml-auto"
                        title="Replace every later scene in this chapter with new ones that follow on from this scene as it is now"
                      >
                        <RefreshCw size={12} />Regenerate later scenes
                      </Button>
                    )}
                  </div>

                  <Separator />

                  {/* Writer-agent rewrite */}
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">Or rewrite via Writer agent{proseDirty && ' (replaces your unsaved edits)'}:</p>
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
                <>
                {flaggedScenes.length > 0 && !isApproved && (
                  <div className="mb-6 rounded-md border border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20 px-3 py-2 flex items-center gap-2 flex-wrap text-xs">
                    <AlertTriangle size={12} className="text-amber-500 shrink-0" />
                    <span className="text-amber-600 dark:text-amber-400 font-medium">
                      QA flagged {flaggedScenes.length === 1 ? '1 scene' : `${flaggedScenes.length} scenes`} — review before approving:
                    </span>
                    {flaggedScenes.map(s => (
                      <button
                        key={s.scene}
                        onClick={() => { setRewriteScene(s.scene); setRewriteDirective('') }}
                        className="px-2 py-0.5 rounded border border-amber-400/60 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
                      >
                        Scene {s.scene}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex justify-end mb-2">
                  <CopyButton text={chapterData?.content ?? ''} label="Copy chapter" />
                </div>
                <pre className="whitespace-pre-wrap font-serif text-base leading-relaxed text-foreground">
                  {chapterData?.content}
                </pre>
                </>
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
                        {s.author_edited && (
                          <span title="Edited by author — not re-checked by QA"><PenLine size={11} className="text-sky-500" /></span>
                        )}
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
                      <span className={cn(
                        'text-[10px]',
                        (s.word_target ?? sceneWordTarget) && s.word_count > (s.word_target ?? sceneWordTarget)! * 1.25
                          ? 'text-amber-500' : 'text-muted-foreground',
                      )}>
                        {s.word_count.toLocaleString()}{(s.word_target ?? sceneWordTarget) ? ` / ~${(s.word_target ?? sceneWordTarget)!.toLocaleString()}` : ''} words
                      </span>
                      {isWritten && !isApproved && (
                        <button
                          onClick={() => {
                            if (s.scene === rewriteScene) return
                            if (proseDirty && !window.confirm('Discard unsaved edits to this scene?')) return
                            setRewriteScene(s.scene); setRewriteDirective('')
                          }}
                          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                        >
                          Edit
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
