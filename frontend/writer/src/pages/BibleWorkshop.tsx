import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'
import { API } from '@/lib/api'
import { ChevronRight, Play, CheckCircle, Lock, Loader2, BookOpen, MapPin, Users } from 'lucide-react'

const TIERS = [
  { id: 1, label: 'Book',     question: 'What happens in this book?' },
  { id: 2, label: 'Acts',     question: 'What happens in each act?' },
  { id: 3, label: 'Chapters', question: 'What happens in each chapter?' },
  { id: 4, label: 'Scenes',   question: 'What happens in each scene?' },
]

type TierStatus = 'locked' | 'active' | 'running' | 'review' | 'approved'
type P2Step = 'idle' | 'consolidating' | 'researching' | 'done'

interface TierEntry { content: string | null; approved: boolean; draft?: string | null }
interface BibleEntity {
  type: string; name: string; aliases?: string[]
  coreFacts?: Record<string, string>
  eventLog?: { act: number; chapter: number; event: string }[]
  lifecycle?: number[]
}
interface Bible { ledger: Record<string, BibleEntity>; metadata?: Record<string, unknown> }

const TYPE_ICON: Record<string, typeof BookOpen> = {
  character: Users,
  location: MapPin,
  faction: Users,
  object: BookOpen,
}

export default function BibleWorkshopPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()

  const { data: savedTiers } = useQuery<TierEntry[]>({
    queryKey: ['bible-tiers', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/bible/tiers`).then(r => r.json()),
  })

  const { data: phase2Status, refetch: refetchP2Status } = useQuery({
    queryKey: ['phase2-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase2/status`).then(r => r.json()),
    refetchInterval: false,
  })

  const { data: bible, refetch: refetchBible } = useQuery<Bible>({
    queryKey: ['bible', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/bible`).then(r => r.json()),
    enabled: !!phase2Status?.bible_exists,
  })

  const [contents, setContents] = useState<(string | null)[]>([null, null, null, null])
  const [statuses, setStatuses] = useState<TierStatus[]>(['active', 'locked', 'locked', 'locked'])
  const [activeTier, setActiveTier] = useState(0)
  const [streaming, setStreaming] = useState(false)
  const [directive, setDirective] = useState('')

  // Phase 2 state
  const [p2Step, setP2Step] = useState<P2Step>('idle')
  const [p2Log, setP2Log] = useState('')

  const allTiersApproved = statuses.every(s => s === 'approved')

  // Restore tiers from server
  useEffect(() => {
    if (!savedTiers) return
    const next: TierStatus[] = ['active', 'locked', 'locked', 'locked']
    let firstUnapproved = -1
    for (let i = 0; i < 4; i++) {
      if (savedTiers[i]?.approved) {
        next[i] = 'approved'
      } else {
        firstUnapproved = firstUnapproved === -1 ? i : firstUnapproved
        const unlocked = i === 0 || next[i - 1] === 'approved'
        if (unlocked) next[i] = savedTiers[i]?.draft ? 'review' : 'active'
      }
    }
    setStatuses(next)
    setContents(savedTiers.map(t => t.content ?? t.draft ?? null))
    const active = firstUnapproved !== -1 ? firstUnapproved : 3
    setActiveTier(active)
  }, [savedTiers])

  // Sync p2Step from server state
  useEffect(() => {
    if (!phase2Status) return
    const s = phase2Status.phase2_status
    if (s === 'approved') setP2Step('done')
    else if (s === 'researched') setP2Step('done')
    else if (s === 'consolidated') setP2Step('done')
  }, [phase2Status])

  async function runTier(idx: number) {
    setStatuses(prev => { const n = [...prev]; n[idx] = 'running'; return n })
    setContents(prev => { const n = [...prev]; n[idx] = ''; return n })
    setStreaming(true)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/bible/run-tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: idx + 1 }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setContents(prev => { const n = [...prev]; n[idx] = text; return n })
        } else if (event.type === 'error') {
          setContents(prev => { const n = [...prev]; n[idx] = `⚠ ${event.message}`; return n })
          break
        }
      }
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } catch {
      setContents(prev => { const n = [...prev]; n[idx] = '⚠ Connection error — is the server running?'; return n })
      setStatuses(prev => { const n = [...prev]; n[idx] = 'active'; return n })
    } finally {
      setStreaming(false)
    }
  }

  async function approveTier(idx: number) {
    const content = contents[idx] ?? ''
    await fetch(`${API}/books/${bookId}/phase1/bible/approve-tier`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: idx + 1, content }),
    })
    setStatuses(prev => {
      const n = [...prev]
      n[idx] = 'approved'
      if (idx + 1 < 4) n[idx + 1] = 'active'
      return n
    })
    setActiveTier(idx + 1 < 4 ? idx + 1 : idx)
    qc.invalidateQueries({ queryKey: ['bible-tiers', bookId] })
    refetchP2Status()
  }

  async function injectAndRerun() {
    if (!directive.trim()) return
    await fetch(`${API}/books/${bookId}/phase1/bible/directive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directive }),
    })
    setDirective('')
    runTier(activeTier)
  }

  async function editTier(idx: number) {
    if (!directive.trim()) return
    const d = directive
    setDirective('')
    setStatuses(prev => { const n = [...prev]; n[idx] = 'running'; return n })
    setContents(prev => { const n = [...prev]; n[idx] = ''; return n })
    setStreaming(true)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/bible/edit-tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: idx + 1, directive: d }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setContents(prev => { const n = [...prev]; n[idx] = text; return n })
        } else if (event.type === 'error') {
          setContents(prev => { const n = [...prev]; n[idx] = `⚠ ${event.message}`; return n })
          break
        }
      }
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } catch {
      setContents(prev => { const n = [...prev]; n[idx] = '⚠ Connection error — is the server running?'; return n })
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } finally {
      setStreaming(false)
    }
  }

  async function runP2(endpoint: string, _label: string, nextStep: P2Step) {
    setP2Step(nextStep)
    setP2Log('')
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase2/${endpoint}`, { method: 'POST' })
      for await (const event of readSSE(resp)) {
        if (event.type === 'token') {
          setP2Log(prev => prev + event.content)
        } else if (event.type === 'status') {
          setP2Log(prev => prev + `\n[${event.message}]\n`)
        } else if (event.type === 'saved') {
          setP2Log(prev => prev + `\n\n✓ Saved — ${event.entity_count} entities`)
          await refetchP2Status()
          await refetchBible()
        } else if (event.type === 'error') {
          setP2Log(prev => prev + `\n⚠ ${event.message}`)
          setP2Step('idle')
          return
        }
      }
    } catch {
      setP2Log(prev => prev + '\n⚠ Connection error')
      setP2Step('idle')
    }
  }

  async function approveP2() {
    await fetch(`${API}/books/${bookId}/phase2/approve`, { method: 'POST' })
    await refetchP2Status()
    qc.invalidateQueries({ queryKey: ['bible', bookId] })
  }

  // Group entities by type for sidebar
  const ledger = bible?.ledger ?? {}
  const byType: Record<string, [string, BibleEntity][]> = {}
  for (const [id, entity] of Object.entries(ledger)) {
    const t = entity.type ?? 'other'
    ;(byType[t] ??= []).push([id, entity])
  }
  const typeOrder = ['character', 'location', 'faction', 'object']
  const sortedTypes = [...new Set([...typeOrder, ...Object.keys(byType)])].filter(t => byType[t])

  const p2Approved = phase2Status?.phase2_approved
  const p2Status = phase2Status?.phase2_status ?? 'idle'
  const bibleExists = phase2Status?.bible_exists
  const entityCount = phase2Status?.entity_count ?? 0

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Tier stepper */}
        <div className="flex items-center gap-2 px-6 py-4 border-b border-border">
          {TIERS.map((tier, i) => (
            <div key={tier.id} className="flex items-center gap-2">
              <button
                className={cn(
                  'flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md transition-colors',
                  statuses[i] === 'approved' ? 'text-emerald-500'
                    : i === activeTier ? 'bg-accent text-accent-foreground font-medium'
                    : statuses[i] === 'locked' ? 'text-muted-foreground/40 cursor-not-allowed'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => statuses[i] !== 'locked' && !streaming && setActiveTier(i)}
                disabled={statuses[i] === 'locked' || streaming}
              >
                {statuses[i] === 'approved' && <CheckCircle size={13} />}
                {tier.label}
              </button>
              {i < TIERS.length - 1 && <ChevronRight size={14} className="text-muted-foreground/40" />}
            </div>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
          {/* ── Phase 1: Active tier ── */}
          <div className="flex items-start justify-between">
            <div>
              <h2 className="font-semibold">Tier {TIERS[activeTier].id} — {TIERS[activeTier].label}</h2>
              <p className="text-sm text-muted-foreground">{TIERS[activeTier].question}</p>
            </div>
            <div className="flex gap-2">
              {statuses[activeTier] === 'active' && (
                <Button size="sm" onClick={() => runTier(activeTier)} className="gap-2" disabled={streaming}>
                  <Play size={13} />Run agent
                </Button>
              )}
              {statuses[activeTier] === 'running' && (
                <Badge variant="secondary" className="gap-1.5">
                  <Loader2 size={12} className="animate-spin" />Agent running…
                </Badge>
              )}
              {statuses[activeTier] === 'review' && (
                <>
                  <Button size="sm" variant="outline" onClick={() => runTier(activeTier)} disabled={streaming}>Re-run</Button>
                  <Button size="sm" onClick={() => approveTier(activeTier)} className="gap-2" disabled={streaming}>
                    <Lock size={13} />Approve tier
                  </Button>
                </>
              )}
              {statuses[activeTier] === 'approved' && <Badge variant="success">Approved</Badge>}
            </div>
          </div>

          <Card className="min-h-[300px]">
            <CardContent className="p-5">
              {statuses[activeTier] === 'locked' && (
                <p className="text-sm text-muted-foreground italic">Complete the tier above to unlock this one.</p>
              )}
              {statuses[activeTier] === 'active' && !contents[activeTier] && (
                <p className="text-sm text-muted-foreground italic">Run the agent to generate this tier.</p>
              )}
              {contents[activeTier] && (
                <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                  {contents[activeTier]}
                  {statuses[activeTier] === 'running' && <span className="animate-pulse">▋</span>}
                </pre>
              )}
            </CardContent>
          </Card>

          {statuses[activeTier] === 'review' && (
            <div className="space-y-2">
              <Separator />
              <p className="text-xs text-muted-foreground pt-2">
                Inject a directive — saved to directives.md, agent re-runs incorporating it.
              </p>
              <div className="flex gap-2">
                <textarea
                  value={directive}
                  onChange={e => setDirective(e.target.value)}
                  placeholder='e.g. "Add a merchant who joins in Acre and dies in Constantinople…"'
                  rows={2}
                  disabled={streaming}
                  className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <Button variant="outline" size="sm" onClick={() => editTier(activeTier)} disabled={!directive.trim() || streaming}>
                  Edit current
                </Button>
                <Button variant="outline" size="sm" onClick={injectAndRerun} disabled={!directive.trim() || streaming}>
                  Inject &amp; re-run
                </Button>
              </div>
            </div>
          )}

          {/* ── Phase 2 panel (appears when all tiers approved) ── */}
          {allTiersApproved && (
            <>
              <Separator className="my-4" />
              <div className="space-y-4">
                <div>
                  <h2 className="font-semibold">Phase 2 — Research &amp; Entity Completion</h2>
                  <p className="text-sm text-muted-foreground">
                    Consolidate the bible into a structured entity ledger, then enrich every entity.
                  </p>
                </div>

                {/* Step 1: Consolidate */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        'flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                        bibleExists ? 'bg-emerald-500/20 text-emerald-500' : 'bg-muted text-muted-foreground'
                      )}>1</span>
                      <span className="text-sm font-medium">Consolidate entity ledger</span>
                      {bibleExists && <CheckCircle size={13} className="text-emerald-500" />}
                    </div>
                    {!p2Approved && (
                      <Button
                        size="sm"
                        variant={bibleExists ? 'outline' : 'default'}
                        disabled={p2Step === 'consolidating' || p2Step === 'researching'}
                        onClick={() => runP2('consolidate', 'Consolidating…', 'consolidating')}
                      >
                        {p2Step === 'consolidating'
                          ? <><Loader2 size={12} className="animate-spin mr-1" />Running…</>
                          : bibleExists ? 'Re-run' : 'Run'}
                      </Button>
                    )}
                  </div>
                  {bibleExists && <p className="text-xs text-muted-foreground pl-7">{entityCount} entities in ledger</p>}
                </div>

                {/* Step 2: Research */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        'flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                        (p2Status === 'researched' || p2Status === 'approved') ? 'bg-emerald-500/20 text-emerald-500'
                          : bibleExists ? 'bg-muted text-foreground' : 'bg-muted text-muted-foreground/40'
                      )}>2</span>
                      <span className={cn('text-sm font-medium', !bibleExists && 'text-muted-foreground/40')}>
                        Research &amp; complete entities
                      </span>
                      {(p2Status === 'researched' || p2Status === 'approved') && <CheckCircle size={13} className="text-emerald-500" />}
                    </div>
                    {!p2Approved && bibleExists && (
                      <Button
                        size="sm"
                        variant={(p2Status === 'researched') ? 'outline' : 'default'}
                        disabled={p2Step === 'consolidating' || p2Step === 'researching'}
                        onClick={() => runP2('run', 'Researching…', 'researching')}
                      >
                        {p2Step === 'researching'
                          ? <><Loader2 size={12} className="animate-spin mr-1" />Running…</>
                          : (p2Status === 'researched' || p2Status === 'approved') ? 'Re-run' : 'Run'}
                      </Button>
                    )}
                  </div>
                </div>

                {/* Step 3: Approve */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      'flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                      p2Approved ? 'bg-emerald-500/20 text-emerald-500'
                        : (p2Status === 'researched') ? 'bg-muted text-foreground' : 'bg-muted text-muted-foreground/40'
                    )}>3</span>
                    <span className={cn('text-sm font-medium', !bibleExists && 'text-muted-foreground/40')}>
                      Approve &amp; unlock Writing Loop
                    </span>
                    {p2Approved && <CheckCircle size={13} className="text-emerald-500" />}
                  </div>
                  {!p2Approved && p2Status === 'researched' && (
                    <Button size="sm" onClick={approveP2} className="gap-2">
                      <Lock size={13} />Approve Phase 2
                    </Button>
                  )}
                  {p2Approved && <Badge variant="success">Writing Loop unlocked</Badge>}
                </div>

                {/* Streaming log */}
                {p2Log && (
                  <Card className="bg-muted/30">
                    <CardContent className="p-4">
                      <pre className="text-xs font-mono whitespace-pre-wrap leading-relaxed text-muted-foreground max-h-48 overflow-y-auto">
                        {p2Log}
                        {(p2Step === 'consolidating' || p2Step === 'researching') && (
                          <span className="animate-pulse">▋</span>
                        )}
                      </pre>
                    </CardContent>
                  </Card>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Entity ledger sidebar */}
      <div className="w-72 border-l border-border flex flex-col">
        <div className="px-4 py-4 border-b border-border">
          <h3 className="text-sm font-medium">Entity Ledger</h3>
          <p className="text-xs text-muted-foreground">
            {entityCount > 0 ? `${entityCount} entities` : 'Populated in Phase 2'}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {sortedTypes.length === 0 ? (
            ['Characters', 'Locations', 'Factions'].map(type => (
              <div key={type}>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">{type}</p>
                <Card className="bg-muted/30">
                  <CardContent className="px-3 py-2">
                    <p className="text-xs text-muted-foreground italic">Populated in Phase 2</p>
                  </CardContent>
                </Card>
              </div>
            ))
          ) : (
            sortedTypes.map(type => {
              const Icon = TYPE_ICON[type] ?? BookOpen
              const entities = byType[type]
              return (
                <div key={type}>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">
                    {type}s ({entities.length})
                  </p>
                  <div className="space-y-1">
                    {entities.map(([id, entity]) => (
                      <div key={id} className="flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 transition-colors">
                        <Icon size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium truncate">{entity.name}</p>
                          {entity.aliases && entity.aliases.length > 0 && (
                            <p className="text-[10px] text-muted-foreground truncate">
                              {entity.aliases.slice(0, 2).join(', ')}
                            </p>
                          )}
                        </div>
                        <span className="text-[9px] text-muted-foreground/60 ml-auto shrink-0">{id}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
