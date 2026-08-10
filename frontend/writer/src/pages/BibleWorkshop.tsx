import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'
import { ChevronRight, Play, CheckCircle, Lock, Loader2 } from 'lucide-react'

const TIERS = [
  { id: 1, label: 'Book',     question: 'What happens in this book?' },
  { id: 2, label: 'Acts',     question: 'What happens in each act?' },
  { id: 3, label: 'Chapters', question: 'What happens in each chapter?' },
  { id: 4, label: 'Scenes',   question: 'What happens in each scene?' },
]

type TierStatus = 'locked' | 'active' | 'running' | 'review' | 'approved'

interface TierEntry { content: string | null; approved: boolean }

export default function BibleWorkshopPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()

  const { data: savedTiers } = useQuery<TierEntry[]>({
    queryKey: ['bible-tiers', bookId],
    queryFn: () => fetch(`/api/books/${bookId}/phase1/bible/tiers`).then(r => r.json()),
  })

  // content[i] = what's currently displayed for tier i (may be streaming)
  const [contents, setContents] = useState<(string | null)[]>([null, null, null, null])
  const [statuses, setStatuses] = useState<TierStatus[]>(['active', 'locked', 'locked', 'locked'])
  const [activeTier, setActiveTier] = useState(0)
  const [streaming, setStreaming] = useState(false)
  const [directive, setDirective] = useState('')

  // Restore from server on load
  useEffect(() => {
    if (!savedTiers) return
    const next: TierStatus[] = ['active', 'locked', 'locked', 'locked']
    let firstUnapproved = -1
    for (let i = 0; i < 4; i++) {
      if (savedTiers[i]?.approved) {
        next[i] = 'approved'
      } else {
        firstUnapproved = firstUnapproved === -1 ? i : firstUnapproved
        if (i > 0 && next[i - 1] === 'approved') next[i] = 'active'
      }
    }
    setStatuses(next)
    setContents(savedTiers.map(t => t.content))
    const active = firstUnapproved !== -1 ? firstUnapproved : 3
    setActiveTier(active)
  }, [savedTiers])

  async function runTier(idx: number) {
    setStatuses(prev => { const n = [...prev]; n[idx] = 'running'; return n })
    setContents(prev => { const n = [...prev]; n[idx] = ''; return n })
    setStreaming(true)

    try {
      const resp = await fetch(`/api/books/${bookId}/phase1/bible/run-tier`, {
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
    await fetch(`/api/books/${bookId}/phase1/bible/approve-tier`, {
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
    const next = idx + 1 < 4 ? idx + 1 : idx
    setActiveTier(next)
    qc.invalidateQueries({ queryKey: ['bible-tiers', bookId] })
  }

  async function injectAndRerun() {
    if (!directive.trim()) return
    await fetch(`/api/books/${bookId}/phase1/bible/directive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directive }),
    })
    setDirective('')
    runTier(activeTier)
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col">
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

          {/* Output card */}
          <Card className="min-h-[300px]">
            <CardContent className="p-5">
              {(statuses[activeTier] === 'locked') && (
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

          {/* Directive injection (only when in review) */}
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
                <Button variant="outline" size="sm" onClick={injectAndRerun} disabled={!directive.trim() || streaming}>
                  Inject &amp; re-run
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Entity ledger sidebar — populated by Phase 2 */}
      <div className="w-72 border-l border-border flex flex-col">
        <div className="px-4 py-4 border-b border-border">
          <h3 className="text-sm font-medium">Entity Ledger</h3>
          <p className="text-xs text-muted-foreground">Single source of truth — never deleted</p>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {['Characters', 'Locations', 'Factions'].map(type => (
            <div key={type}>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">{type}</p>
              <Card className="bg-muted/30">
                <CardContent className="px-3 py-2">
                  <p className="text-xs text-muted-foreground italic">Populated in Phase 2</p>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
