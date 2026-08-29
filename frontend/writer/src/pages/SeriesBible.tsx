import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { ChevronLeft, Plus, Loader2, User, MapPin, Users, Box, Star, Paintbrush, Sparkles } from 'lucide-react'

async function fetchSeriesText(seriesId: string, endpoint: string): Promise<{ content: string }> {
  const r = await fetch(`${API}/series/${seriesId}/${endpoint}`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function saveSeriesText(seriesId: string, endpoint: string, content: string) {
  const r = await fetch(`${API}/series/${seriesId}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!r.ok) throw new Error('Failed to save')
}

function TextSection({ icon: Icon, title, description, queryKey, seriesId, endpoint }: {
  icon: React.ElementType
  title: string
  description: string
  queryKey: string[]
  seriesId: string
  endpoint: string
}) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => fetchSeriesText(seriesId, endpoint),
  })
  const [draft, setDraft] = useState<string | null>(null)
  const current = draft ?? data?.content ?? ''

  const save = useMutation({
    mutationFn: (content: string) => saveSeriesText(seriesId, endpoint, content),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey })
      setDraft(null)
    },
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-muted-foreground" />
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      <p className="text-xs text-muted-foreground pl-5">{description}</p>
      <textarea
        value={isLoading ? '' : current}
        onChange={e => setDraft(e.target.value)}
        placeholder={isLoading ? 'Loading…' : `Write the ${title.toLowerCase()} here…`}
        className="w-full h-40 rounded-md border border-input bg-background px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-ring"
      />
      {draft !== null && draft !== (data?.content ?? '') && (
        <div className="flex gap-2">
          <Button size="sm" onClick={() => save.mutate(draft)} disabled={save.isPending} className="h-7 text-xs gap-1.5">
            {save.isPending && <Loader2 size={11} className="animate-spin" />}Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDraft(null)} className="h-7 text-xs">Discard</Button>
        </div>
      )}
    </div>
  )
}

interface Entity {
  id: string
  type?: string
  name?: string
  [key: string]: unknown
}

interface SeriesBible {
  metadata: { series_id?: string; title?: string; last_updated?: string }
  ledger: Record<string, Entity>
}

const TYPE_ICONS: Record<string, React.ElementType> = {
  character: User,
  location: MapPin,
  faction: Users,
  object: Box,
}

const TYPE_LABELS: Record<string, string> = {
  character: 'Characters',
  location: 'Locations',
  faction: 'Factions',
  object: 'Objects',
}

const ID_PREFIXES: Record<string, string> = {
  character: 'CHAR',
  location: 'LOC',
  faction: 'FRAC',
  object: 'OBJ',
}

async function fetchSeriesBible(seriesId: string): Promise<SeriesBible> {
  const r = await fetch(`${API}/series/${seriesId}/bible`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function upsertEntity(seriesId: string, entity_id: string, data: Entity) {
  const r = await fetch(`${API}/series/${seriesId}/bible/entity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_id, data }),
  })
  if (!r.ok) throw new Error('Failed to save entity')
  return r.json()
}

function EntityEditor({ entity, onSave, onCancel }: {
  entity: Entity
  onSave: (updated: Entity) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(entity.name ?? '')
  const [notes, setNotes] = useState(
    typeof entity.series_facts === 'object' && entity.series_facts !== null
      ? JSON.stringify(entity.series_facts, null, 2)
      : ''
  )

  function handleSave() {
    let series_facts = {}
    try { series_facts = notes ? JSON.parse(notes) : {} } catch { /* leave empty */ }
    onSave({ ...entity, name, series_facts })
  }

  return (
    <div className="space-y-3 p-4 bg-accent/20 rounded-md border border-border">
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Name</label>
        <Input value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" />
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Series Facts — permanent (appearance, background, values, personality)</label>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          className="w-full h-28 rounded-md border border-input bg-background px-3 py-2 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="{}"
        />
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={handleSave} className="h-7 text-xs">Save</Button>
        <Button size="sm" variant="ghost" onClick={onCancel} className="h-7 text-xs">Cancel</Button>
      </div>
    </div>
  )
}

function nextEntityId(ledger: Record<string, Entity>, prefix: string): string {
  const existing = Object.keys(ledger)
    .filter(k => k.startsWith(prefix + '_'))
    .map(k => parseInt(k.split('_')[1] ?? '0', 10))
    .filter(n => !isNaN(n))
  const max = existing.length > 0 ? Math.max(...existing) : 0
  return `${prefix}_${String(max + 1).padStart(3, '0')}`
}

export default function SeriesBiblePage() {
  const { seriesId } = useParams<{ seriesId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [addingType, setAddingType] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractResult, setExtractResult] = useState<{ added: number } | null>(null)

  async function extractFromNorthStar() {
    setExtracting(true)
    setExtractResult(null)
    try {
      const r = await fetch(`${API}/series/${seriesId}/extract-entities`, { method: 'POST' })
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Unknown error' }))
        alert(err.detail ?? 'Extraction failed')
        return
      }
      const res = await r.json()
      setExtractResult({ added: res.added })
      qc.invalidateQueries({ queryKey: ['series-bible', seriesId] })
    } finally {
      setExtracting(false)
    }
  }

  const { data: bible, isLoading } = useQuery({
    queryKey: ['series-bible', seriesId],
    queryFn: () => fetchSeriesBible(seriesId!),
    enabled: !!seriesId,
  })

  const saveMutation = useMutation({
    mutationFn: ({ entity_id, data }: { entity_id: string; data: Entity }) =>
      upsertEntity(seriesId!, entity_id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['series-bible', seriesId] })
      setEditingId(null)
      setAddingType(null)
    },
  })

  if (isLoading || !bible) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  const ledger = bible.ledger ?? {}
  const byType: Record<string, Entity[]> = {}
  for (const [id, entity] of Object.entries(ledger)) {
    const t = (entity.type as string) ?? 'other'
    if (!byType[t]) byType[t] = []
    byType[t].push({ ...entity, id })
  }

  const entityTypes = ['character', 'location', 'faction', 'object']

  return (
    <div className="min-h-screen flex flex-col items-center justify-start pt-16 px-6 pb-16">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="space-y-1">
          <button
            onClick={() => navigate('/books')}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-3"
          >
            <ChevronLeft size={13} />All books
          </button>
          <h1 className="text-xl font-semibold tracking-tight">
            {bible.metadata?.title ?? 'Series'} — Series Bible
          </h1>
          {bible.metadata?.last_updated && (
            <p className="text-xs text-muted-foreground">
              Last updated {new Date(bible.metadata.last_updated).toLocaleString()}
            </p>
          )}
        </div>

        {/* Series North Star */}
        <TextSection
          icon={Star}
          title="Series North Star"
          description="The overarching premise, world rules, and thematic contract that holds across all books. Injected into the Story Architect when writing a new book in this series."
          queryKey={['series-north-star', seriesId!]}
          seriesId={seriesId!}
          endpoint="north-star"
        />

        {/* Series Style Sheet */}
        <TextSection
          icon={Paintbrush}
          title="Series Style Sheet"
          description="POV conventions, naming rules, prose rhythm, and recurring motifs. Used as baseline when synthesising writing preferences for a new book in this series."
          queryKey={['series-style-sheet', seriesId!]}
          seriesId={seriesId!}
          endpoint="style-sheet"
        />

        {/* Extract from North Star */}
        <div className="flex items-center gap-3">
          <Button
            variant="outline" size="sm"
            className="gap-2"
            onClick={extractFromNorthStar}
            disabled={extracting}
          >
            {extracting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {extracting ? 'Extracting…' : 'Extract entities from North Star'}
          </Button>
          {extractResult && (
            <span className="text-xs text-emerald-500">✓ {extractResult.added} entities added</span>
          )}
        </div>

        <div className="border-t border-border pt-4" />

        {/* Entity groups */}
        {entityTypes.map(type => {
          const Icon = TYPE_ICONS[type] ?? Box
          const entities = byType[type] ?? []
          const isAdding = addingType === type

          return (
            <div key={type} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon size={14} className="text-muted-foreground" />
                  <h2 className="text-sm font-medium">{TYPE_LABELS[type]}</h2>
                  <span className="text-xs text-muted-foreground">({entities.length})</span>
                </div>
                <Button
                  variant="ghost" size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => { setAddingType(isAdding ? null : type); setEditingId(null) }}
                >
                  <Plus size={12} />Add
                </Button>
              </div>

              {isAdding && (
                <EntityEditor
                  entity={{ id: nextEntityId(ledger, ID_PREFIXES[type] ?? type.toUpperCase()), type, name: '' }}
                  onSave={data => saveMutation.mutate({ entity_id: data.id as string, data })}
                  onCancel={() => setAddingType(null)}
                />
              )}

              {entities.length === 0 && !isAdding ? (
                <p className="text-xs text-muted-foreground pl-5">None yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {entities.map(entity => (
                    <Card key={entity.id} className="group">
                      <CardHeader
                        className="py-3 px-4 cursor-pointer"
                        onClick={() => { setEditingId(editingId === entity.id ? null : entity.id); setAddingType(null) }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <CardTitle className="text-sm">{entity.name ?? entity.id}</CardTitle>
                            <p className="text-xs text-muted-foreground font-mono">{entity.id}</p>
                          </div>
                        </div>
                      </CardHeader>
                      {editingId === entity.id && (
                        <CardContent className="pt-0 pb-3 px-4">
                          <EntityEditor
                            entity={entity}
                            onSave={data => saveMutation.mutate({ entity_id: entity.id, data })}
                            onCancel={() => setEditingId(null)}
                          />
                        </CardContent>
                      )}
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {Object.keys(ledger).length === 0 && (
          <div className="text-center py-12 space-y-2 border border-dashed border-border rounded-lg">
            <p className="text-sm text-muted-foreground">No entities yet.</p>
            <p className="text-xs text-muted-foreground">
              Add characters, locations, and other entities that span multiple books in this series.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
