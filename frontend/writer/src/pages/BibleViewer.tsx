import { useState } from 'react'
import { API } from '@/lib/api'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { Search, ArrowUpToLine, Loader2 } from 'lucide-react'

type EntityType = 'all' | 'character' | 'location' | 'faction' | 'object'

const TYPE_LABELS: Record<string, string> = {
  character: 'Character', location: 'Location', faction: 'Faction', object: 'Object',
}

interface Entity {
  type: string
  name: string
  aliases?: string[]
  series_source?: boolean
  series_facts?: Record<string, string>
  book_facts?: Record<string, string>
  eventLog?: { act: number; chapter: number; description: string }[]
  coreFacts?: Record<string, string>
}

export default function BibleViewerPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<EntityType>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [promoting, setPromoting] = useState<string | null>(null)
  const [promoted, setPromoted] = useState<Set<string>>(new Set())

  const { data: bible } = useQuery({
    queryKey: ['bible', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/bible`).then(r => r.json()),
    refetchInterval: 10_000,
  })

  const { data: book } = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}`).then(r => r.json()),
  })

  const ledger: Record<string, Entity> = bible?.ledger ?? {}

  const entries = Object.entries(ledger).filter(([, e]) => {
    if (filter !== 'all' && e.type !== filter) return false
    if (search && !e.name.toLowerCase().includes(search.toLowerCase()) &&
        !e.aliases?.some(a => a.toLowerCase().includes(search.toLowerCase()))) return false
    return true
  })

  async function promote(entityId: string) {
    setPromoting(entityId)
    try {
      await fetch(`${API}/books/${bookId}/promote-entity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_id: entityId }),
      })
      setPromoted(prev => new Set(prev).add(entityId))
      qc.invalidateQueries({ queryKey: ['bible', bookId] })
    } finally {
      setPromoting(null)
    }
  }

  const inSeries = book?.series_id

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-4 px-6 py-4 border-b border-border">
        <h2 className="font-semibold shrink-0">Bible Viewer</h2>
        <div className="relative flex-1 max-w-sm">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search entities, aliases…" className="pl-8 h-8 text-xs" />
        </div>
        <div className="flex gap-1">
          {(['all', 'character', 'location', 'faction', 'object'] as EntityType[]).map(t => (
            <button key={t} onClick={() => setFilter(t)} className={cn('text-xs px-3 py-1 rounded-md transition-colors capitalize', filter === t ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground')}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {entries.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-sm text-muted-foreground">
              {Object.keys(ledger).length === 0 ? 'No bible loaded yet — complete Phase 1 to populate the ledger.' : 'No entities match your search.'}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {entries.map(([id, entity]) => {
              const isSeriesSource = entity.series_source === true
              const hasSeriesFacts = entity.series_facts && Object.keys(entity.series_facts).length > 0
              const hasBookFacts = entity.book_facts && Object.keys(entity.book_facts).length > 0
              const legacyFacts = entity.coreFacts

              return (
                <Card key={id} className={cn('cursor-pointer transition-colors hover:bg-accent/30', expanded === id && 'ring-1 ring-ring')} onClick={() => setExpanded(expanded === id ? null : id)}>
                  <CardHeader className="py-3 px-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-sm">{entity.name}</CardTitle>
                        <Badge variant="outline" className="text-xs capitalize">{TYPE_LABELS[entity.type] ?? entity.type}</Badge>
                        {isSeriesSource && <Badge variant="secondary" className="text-xs">Series</Badge>}
                      </div>
                      <div className="flex items-center gap-2">
                        {inSeries && !isSeriesSource && !promoted.has(id) && (
                          <Button
                            size="sm" variant="ghost"
                            className="h-6 gap-1 text-xs opacity-60 hover:opacity-100"
                            onClick={e => { e.stopPropagation(); promote(id) }}
                            disabled={promoting === id}
                          >
                            {promoting === id ? <Loader2 size={11} className="animate-spin" /> : <ArrowUpToLine size={11} />}
                            Promote
                          </Button>
                        )}
                        {promoted.has(id) && <span className="text-xs text-emerald-500">✓ In series</span>}
                        <span className="text-xs font-mono text-muted-foreground">{id}</span>
                      </div>
                    </div>
                    {entity.aliases && entity.aliases.length > 0 && <p className="text-xs text-muted-foreground">Also: {entity.aliases.join(', ')}</p>}
                  </CardHeader>
                  {expanded === id && (
                    <CardContent className="px-4 pb-4 space-y-3">
                      {hasSeriesFacts && (
                        <div>
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Series facts (permanent)</p>
                          {Object.entries(entity.series_facts!).map(([k, v]) => <p key={k} className="text-xs"><span className="text-muted-foreground">{k}:</span> {v}</p>)}
                        </div>
                      )}
                      {hasBookFacts && (
                        <div>
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">In this book</p>
                          {Object.entries(entity.book_facts!).map(([k, v]) => <p key={k} className="text-xs"><span className="text-muted-foreground">{k}:</span> {v}</p>)}
                        </div>
                      )}
                      {!hasSeriesFacts && !hasBookFacts && legacyFacts && (
                        <div>
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Core facts</p>
                          {Object.entries(legacyFacts).map(([k, v]) => <p key={k} className="text-xs"><span className="text-muted-foreground">{k}:</span> {v}</p>)}
                        </div>
                      )}
                      {entity.eventLog && entity.eventLog.length > 0 && (
                        <div>
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Event log</p>
                          {entity.eventLog.map((ev, i) => (
                            <div key={i} className="flex gap-2 text-xs py-0.5">
                              <span className="text-muted-foreground shrink-0">Act {ev.act}, Ch {ev.chapter}</span>
                              <span>{ev.description}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  )}
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
