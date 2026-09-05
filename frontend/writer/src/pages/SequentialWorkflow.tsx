import { useState, useEffect, useRef, forwardRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API } from '@/lib/api'
import { runJob as doRunJob, sleep } from '@/lib/jobs'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, AlertCircle } from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────────

interface SceneProgress {
  number: number; title: string
  brief_has_content: boolean; brief_approved: boolean
  prose_written: boolean; prose_approved: boolean
}
interface ChapterProgress {
  number: number; title: string
  plan_has_content: boolean; plan_approved: boolean
  scenes: SceneProgress[]
}
interface ActProgress {
  number: number; title: string
  approved: boolean; consolidated: boolean
  chapters: ChapterProgress[]
}
interface Current {
  act: number | null; chapter: number | null; scene: number | null
  step: string; content?: string; brief?: string
}
interface Progress {
  ready: boolean; reason?: string
  acts: ActProgress[]; current: Current
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function StatusDot({ done, active, partial }: { done: boolean; active?: boolean; partial?: boolean }) {
  if (done) return <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
  if (active) return <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0 animate-pulse" />
  if (partial) return <span className="w-2 h-2 rounded-full bg-amber-400/50 shrink-0" />
  return <span className="w-2 h-2 rounded-full bg-muted-foreground/25 shrink-0" />
}

const StreamDisplay = forwardRef<HTMLDivElement, { text: string }>(({ text }, ref) => (
  <div
    ref={ref}
    className="h-72 overflow-y-auto p-3 bg-muted rounded-md text-xs font-mono whitespace-pre-wrap border border-border"
  >
    {text || <span className="text-muted-foreground italic">Generating…</span>}
  </div>
))

// ── Progress tree ──────────────────────────────────────────────────────────────

function ProgressTree({ acts, current }: { acts: ActProgress[]; current: Current }) {
  const initExpanded = new Set<string>()
  if (current.act) initExpanded.add(`a${current.act}`)
  if (current.chapter) initExpanded.add(`c${current.chapter}`)
  const [expanded, setExpanded] = useState(initExpanded)
  const toggle = (k: string) => setExpanded(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n })

  return (
    <div className="text-sm space-y-0.5">
      {acts.map(act => {
        const actDone = act.approved && act.consolidated && act.chapters.every(c => c.scenes.length > 0 && c.scenes.every(s => s.prose_approved))
        const actActive = current.act === act.number
        const aKey = `a${act.number}`
        const aOpen = expanded.has(aKey)
        return (
          <div key={act.number}>
            <button
              onClick={() => toggle(aKey)}
              className="flex items-center gap-1.5 w-full px-2 py-1.5 rounded hover:bg-accent/50 text-left"
            >
              {aOpen ? <ChevronDown size={11} className="shrink-0 text-muted-foreground" /> : <ChevronRight size={11} className="shrink-0 text-muted-foreground" />}
              <StatusDot done={actDone} active={actActive} partial={act.approved && !actDone} />
              <span className={actActive ? 'font-medium text-foreground' : 'text-muted-foreground'}>{act.title}</span>
            </button>

            {aOpen && (
              <div className="ml-5 space-y-0.5">
                {act.chapters.map(ch => {
                  const chDone = ch.plan_approved && ch.scenes.length > 0 && ch.scenes.every(s => s.prose_approved)
                  const chActive = current.chapter === ch.number && current.act === act.number
                  const cKey = `c${ch.number}`
                  const cOpen = expanded.has(cKey)
                  return (
                    <div key={ch.number}>
                      <button
                        onClick={() => toggle(cKey)}
                        className="flex items-center gap-1.5 w-full px-2 py-1 rounded hover:bg-accent/50 text-left"
                      >
                        {cOpen ? <ChevronDown size={10} className="shrink-0 text-muted-foreground" /> : <ChevronRight size={10} className="shrink-0 text-muted-foreground" />}
                        <StatusDot done={chDone} active={chActive} partial={ch.plan_approved && !chDone} />
                        <span className={chActive ? 'font-medium text-foreground text-xs' : 'text-muted-foreground text-xs'}>Ch {ch.number}</span>
                        <span className="text-xs text-muted-foreground/60 truncate">{ch.title}</span>
                      </button>

                      {cOpen && (
                        <div className="ml-4 space-y-0.5 py-0.5">
                          {ch.scenes.map(sc => (
                            <div key={sc.number} className="flex items-center gap-1.5 px-2 py-0.5">
                              <StatusDot
                                done={sc.prose_approved}
                                active={current.scene === sc.number && current.chapter === ch.number}
                                partial={sc.brief_approved && !sc.prose_approved}
                              />
                              <span className={`text-xs ${current.scene === sc.number && current.chapter === ch.number ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
                                Sc {sc.number}
                              </span>
                              <span className="text-xs text-muted-foreground/50 truncate">{sc.title}</span>
                            </div>
                          ))}
                          {ch.plan_approved && ch.scenes.length === 0 && (
                            <p className="text-xs text-muted-foreground/50 px-2 py-0.5 italic">No scenes yet</p>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
                {act.approved && (
                  <div className="flex items-center gap-1.5 px-2 py-1">
                    <StatusDot done={act.consolidated} active={current.step === 'consolidate_act' && current.act === act.number} />
                    <span className="text-xs text-muted-foreground">Entity consolidation</span>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  generate_chapters: 'Generate chapter plan',
  approve_chapters: 'Review & approve chapter plan',
  generate_plan: 'Generate scene list',
  approve_plan: 'Review & approve scene list',
  write_brief: 'Generate scene brief',
  approve_brief: 'Review & approve scene brief',
  write_prose: 'Write scene prose',
  approve_prose: 'Review & approve scene prose',
  consolidate_act: 'Consolidate act entities',
  done: 'Complete',
}

export default function SequentialWorkflow() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()
  const base = `${API}/books/${bookId}`

  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  // For consolidate_act: 'idle' | 'consolidated' | 'run_done'
  const [phase2Step, setPhase2Step] = useState<'idle' | 'consolidated' | 'run_done'>('idle')
  const [directive, setDirective] = useState('')
  const streamRef = useRef<HTMLDivElement>(null)
  const prevStepKey = useRef<string>('')

  const { data: progress, isLoading } = useQuery<Progress>({
    queryKey: ['seq-progress', bookId],
    queryFn: () => fetch(`${base}/sequential/progress`).then(r => r.json()),
    refetchInterval: streaming ? false : 5000,
    enabled: !!bookId,
  })

  const current = progress?.current
  const stepKey = current ? `${current.step}|${current.act}|${current.chapter}|${current.scene}` : ''

  useEffect(() => {
    if (!stepKey || stepKey === prevStepKey.current) return
    prevStepKey.current = stepKey
    setStreamText('')
    setError(null)
    setEditContent(current?.content ?? '')
    setPhase2Step('idle')
    setDirective('')
  }, [stepKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const refetch = () => qc.invalidateQueries({ queryKey: ['seq-progress', bookId] })

  // Run a background job, streaming tokens to the stream display.
  async function runBackgroundJob(url: string, body?: Record<string, unknown>) {
    setStreaming(true)
    setStreamText('')
    setError(null)
    try {
      const state = await doRunJob(url, body ?? {}, (_, acc) => {
        setStreamText(acc)
        streamRef.current?.scrollTo(0, streamRef.current.scrollHeight)
      })
      if (state.status === 'error') setError(state.error ?? 'Generation failed')
    } catch (e) { setError(String(e)) }
    finally { setStreaming(false); refetch() }
  }

  // Run a background job with no token streaming (e.g. approve operations).
  async function runSilentJob(url: string, body?: Record<string, unknown>) {
    setStreaming(true)
    setError(null)
    try {
      const state = await doRunJob(url, body ?? {})
      if (state.status === 'error') setError(state.error ?? 'Operation failed')
      else refetch()
    } catch (e) { setError(String(e)) }
    finally { setStreaming(false) }
  }

  // Post to a phase2 endpoint and poll phase2/status until the job finishes.
  async function runPhase2Step(endpoint: string, nextStep: 'consolidated' | 'run_done') {
    setStreaming(true)
    setStreamText('')
    setError(null)
    try {
      const resp = await fetch(`${base}/phase2/${endpoint}`, { method: 'POST' })
      if (!resp.ok) { const d = await resp.json().catch(() => ({})); setError(d.detail ?? 'Request failed'); return }
      let attempts = 0
      while (attempts++ < 150) {
        await sleep(2000)
        const status = await fetch(`${base}/phase2/status`).then(r => r.json())
        if (!status.active_job) break
      }
      setPhase2Step(nextStep)
    } catch (e) { setError(String(e)) }
    finally { setStreaming(false) }
  }

  async function post(url: string, body?: object) {
    setError(null)
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!resp.ok) { const d = await resp.json().catch(() => ({})); setError(d.detail ?? 'Request failed'); return false }
      refetch(); return true
    } catch (e) { setError(String(e)); return false }
  }

  if (isLoading) return <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Loading…</div>
  if (!progress) return <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Could not load progress.</div>

  if (!progress.ready) return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 p-8 text-center max-w-md mx-auto">
      <p className="text-sm font-medium">Sequential mode not ready</p>
      <p className="text-sm text-muted-foreground">{progress.reason}</p>
      <p className="text-xs text-muted-foreground">Complete mini-consolidation in Bible Workshop first (Book → Acts → Consolidate).</p>
    </div>
  )

  const c = current!
  const { step, act, chapter, scene } = c
  const crumbs = [act && `Act ${act}`, chapter && `Chapter ${chapter}`, scene && `Scene ${scene}`].filter(Boolean) as string[]

  return (
    <div className="flex h-full overflow-hidden">
      {/* Progress tree */}
      <aside className="w-60 shrink-0 border-r border-border overflow-y-auto p-3">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3 px-2">Progress</p>
        <ProgressTree acts={progress.acts} current={c} />
      </aside>

      {/* Step card */}
      <main className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-2xl mx-auto space-y-4">

          {step !== 'done' && (
            <div className="space-y-1">
              {crumbs.length > 0 && <p className="text-xs text-muted-foreground">{crumbs.join(' › ')}</p>}
              <h2 className="text-lg font-semibold">{STEP_LABELS[step] ?? step}</h2>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
              <AlertCircle size={15} className="shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {/* ── Done ── */}
          {step === 'done' && (
            <div className="text-center space-y-3 pt-16">
              <p className="text-4xl">✓</p>
              <h2 className="text-xl font-semibold">All done</h2>
              <p className="text-sm text-muted-foreground">Every act, chapter, and scene is defined and written. Check the Bible Viewer for the entity ledger.</p>
            </div>
          )}

          {/* ── Generate chapters ── */}
          {step === 'generate_chapters' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Generate the chapter breakdown for Act {act}.</p>
              {streaming
                ? <StreamDisplay ref={streamRef} text={streamText} />
                : <Button onClick={() => runBackgroundJob(`${base}/phase1/tier3/run-act`, { act })}>Generate chapters</Button>
              }
            </div>
          )}

          {/* ── Approve chapters ── */}
          {step === 'approve_chapters' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Review the chapter plan for Act {act}. Edit if needed.</p>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full h-96 p-3 text-sm font-mono rounded-md border border-input bg-background resize-y"
              />
              <Button onClick={() => post(`${base}/phase1/tier3/approve-act`, { act, content: editContent })}>
                Approve chapter plan
              </Button>
            </div>
          )}

          {/* ── Generate scene list ── */}
          {step === 'generate_plan' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Generate the scene list for Chapter {chapter}.</p>
              {streaming
                ? <StreamDisplay ref={streamRef} text={streamText} />
                : <Button onClick={() => runBackgroundJob(`${base}/phase1/tier4/run-chapter`, { chapter })}>Generate scene list</Button>
              }
            </div>
          )}

          {/* ── Approve scene list ── */}
          {step === 'approve_plan' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Review the scene list for Chapter {chapter}. Scenes must use <code className="text-xs">### Scene N — Title</code> format.
              </p>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full h-96 p-3 text-sm font-mono rounded-md border border-input bg-background resize-y"
              />
              <Button onClick={() => post(`${base}/phase1/tier4/approve-chapter`, { chapter, content: editContent })}>
                Approve scene list
              </Button>
            </div>
          )}

          {/* ── Generate scene brief ── */}
          {step === 'write_brief' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Generate a detailed planning brief for Scene {scene}.</p>
              {streaming
                ? <StreamDisplay ref={streamRef} text={streamText} />
                : (
                  <div className="space-y-2">
                    <textarea
                      value={directive}
                      onChange={e => setDirective(e.target.value)}
                      placeholder="Optional directive — e.g. 'raise tension', 'keep it brief', 'focus on character reaction'…"
                      className="w-full h-20 p-3 text-sm rounded-md border border-input bg-background resize-y placeholder:text-muted-foreground/50"
                    />
                    <Button onClick={() => runBackgroundJob(`${base}/phase1/tier4/chapter/${chapter}/run-scene`, directive.trim() ? { scene, directive } : { scene })}>
                      Generate brief
                    </Button>
                  </div>
                )
              }
            </div>
          )}

          {/* ── Approve scene brief ── */}
          {step === 'approve_brief' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Review the brief for Scene {scene}. Edit freely — this guides prose writing.</p>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full h-72 p-3 text-sm font-mono rounded-md border border-input bg-background resize-y"
              />
              <Button
                disabled={streaming}
                onClick={() => runSilentJob(
                  `${base}/phase1/tier4/chapter/${chapter}/scene/${scene}/approve`,
                  { content: editContent },
                )}
              >
                {streaming ? 'Approving…' : 'Approve brief & sync bible'}
              </Button>
            </div>
          )}

          {/* ── Write scene prose ── */}
          {step === 'write_prose' && (
            <div className="space-y-3">
              {c.brief && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">Scene brief (reference)</summary>
                  <pre className="mt-2 p-3 bg-muted rounded-md text-xs overflow-x-auto whitespace-pre-wrap">{c.brief}</pre>
                </details>
              )}
              <p className="text-sm text-muted-foreground">Write the prose for Scene {scene}.</p>
              {streaming
                ? <StreamDisplay ref={streamRef} text={streamText} />
                : (
                  <div className="space-y-2">
                    <textarea
                      value={directive}
                      onChange={e => setDirective(e.target.value)}
                      placeholder="Optional directive — e.g. 'make it tense', 'focus on subtext', 'cut the preamble'…"
                      className="w-full h-20 p-3 text-sm rounded-md border border-input bg-background resize-y placeholder:text-muted-foreground/50"
                    />
                    <Button onClick={() => runBackgroundJob(`${base}/phase3/chapter/${chapter}/scene/${scene}/write`, directive.trim() ? { directive } : {})}>
                      Write scene
                    </Button>
                  </div>
                )
              }
            </div>
          )}

          {/* ── Approve scene prose ── */}
          {step === 'approve_prose' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Review the prose for Scene {scene}. Use Writing Loop to rewrite if needed.
              </p>
              <pre className="p-4 bg-muted rounded-md text-sm whitespace-pre-wrap overflow-auto max-h-96 border border-border">
                {c.content || <span className="italic text-muted-foreground">No content yet</span>}
              </pre>
              <Button onClick={() => post(`${base}/sequential/chapter/${chapter}/scene/${scene}/approve-prose`)}>
                Approve prose
              </Button>
            </div>
          )}

          {/* ── Consolidate act ── */}
          {step === 'consolidate_act' && (
            <div className="space-y-5">
              <p className="text-sm text-muted-foreground">
                Update the entity ledger with everything written in Act {act}. Run both steps before marking complete.
              </p>

              {/* Step 1: consolidate */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Step 1 — Consolidate</p>
                {phase2Step === 'idle' && streaming && (
                  <StreamDisplay ref={streamRef} text={streamText} />
                )}
                <Button
                  disabled={streaming || phase2Step !== 'idle'}
                  variant={phase2Step !== 'idle' ? 'secondary' : 'default'}
                  onClick={() => runPhase2Step('consolidate', 'consolidated')}
                >
                  {streaming && phase2Step === 'idle' ? 'Consolidating…' : phase2Step !== 'idle' ? '✓ Consolidated' : 'Consolidate entities'}
                </Button>
              </div>

              {/* Step 2: research/enrich */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Step 2 — Enrich</p>
                {phase2Step === 'consolidated' && streaming && (
                  <StreamDisplay ref={streamRef} text={streamText} />
                )}
                <Button
                  disabled={streaming || phase2Step === 'idle' || phase2Step === 'run_done'}
                  variant={phase2Step === 'run_done' ? 'secondary' : 'default'}
                  onClick={() => { setStreamText(''); runPhase2Step('run', 'run_done') }}
                >
                  {streaming && phase2Step === 'consolidated' ? 'Enriching…' : phase2Step === 'run_done' ? '✓ Enriched' : 'Enrich entities'}
                </Button>
              </div>

              {/* Step 3: mark done */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Step 3 — Complete</p>
                <Button
                  disabled={streaming || phase2Step !== 'run_done'}
                  onClick={async () => {
                    const resp = await fetch(`${base}/sequential/mark-consolidated`, {
                      method: 'PATCH',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ act }),
                    })
                    if (resp.ok) refetch()
                    else setError('Failed to mark consolidated')
                  }}
                >
                  Mark Act {act} consolidated
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
