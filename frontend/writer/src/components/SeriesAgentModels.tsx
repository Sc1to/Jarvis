import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API } from '@/lib/api'
import { AGENTS, type Provider } from '@/lib/agents'
import { useProviderModels } from '@/lib/useProviderModels'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Loader2, SlidersHorizontal } from 'lucide-react'

interface AgentModelRow {
  provider: string | null
  model: string | null
  effective_provider: string | null
  effective_model: string | null
}

async function fetchGlobalSettings(): Promise<Record<string, string>> {
  const r = await fetch(`${API}/settings`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function fetchSeriesAgentModels(seriesId: string): Promise<Record<string, AgentModelRow>> {
  const r = await fetch(`${API}/series/${seriesId}/agent-models`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function saveSeriesAgentModel(seriesId: string, agent_key: string, provider: string | null, model: string | null) {
  const r = await fetch(`${API}/series/${seriesId}/agent-models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_key, provider, model }),
  })
  if (!r.ok) throw new Error('Failed to save')
}

function NativeSelect({ value, onChange, disabled, className, children }: {
  value: string; onChange: (v: string) => void; disabled?: boolean; className?: string; children: React.ReactNode
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      disabled={disabled}
      className={cn(
        'flex h-8 w-full rounded-md border border-input bg-background text-foreground px-2 py-1 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
    >
      {children}
    </select>
  )
}

interface RowProps {
  seriesId: string
  agentKey: string
  label: string
  description: string
  hint?: string
  row: AgentModelRow
  availableProviders: { value: Provider; label: string }[]
  modelsForProvider: (p: Provider) => { id: string; name: string; free?: boolean }[]
  isLoadingForProvider: (p: Provider) => boolean
}

function AgentModelRowEditor({ seriesId, agentKey, label, description, hint, row, availableProviders, modelsForProvider, isLoadingForProvider }: RowProps) {
  const qc = useQueryClient()
  const hasOverride = !!(row.provider && row.model)
  const [enabled, setEnabled] = useState(hasOverride)
  const [provider, setProvider] = useState<Provider>((row.provider ?? '') as Provider)
  const [model, setModel] = useState(row.model ?? '')

  // Re-sync local draft when the server row changes (e.g. after a save elsewhere)
  useEffect(() => {
    setEnabled(!!(row.provider && row.model))
    setProvider((row.provider ?? '') as Provider)
    setModel(row.model ?? '')
  }, [row.provider, row.model])

  const save = useMutation({
    mutationFn: (v: { provider: string | null; model: string | null }) =>
      saveSeriesAgentModel(seriesId, agentKey, v.provider, v.model),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['series-agent-models', seriesId] }),
  })

  const dirty = enabled
    ? (provider !== (row.provider ?? '') || model !== (row.model ?? ''))
    : hasOverride

  const models = modelsForProvider(provider)
  const loading = isLoadingForProvider(provider)

  function toggle(v: boolean) {
    setEnabled(v)
    if (!v) {
      setProvider('')
      setModel('')
    }
  }

  function handleSave() {
    if (enabled) {
      if (!provider || !model) return
      save.mutate({ provider, model })
    } else {
      save.mutate({ provider: null, model: null })
    }
  }

  return (
    <div className="px-5 py-4 space-y-2.5 border-b border-border last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <Switch checked={enabled} onCheckedChange={toggle} />
      </div>

      {!enabled ? (
        <p className="text-xs text-muted-foreground">
          Currently using: {row.effective_provider && row.effective_model
            ? <span className="font-mono">{row.effective_provider} / {row.effective_model}</span>
            : <span className="italic">not configured</span>}
          {hint && <span className="block text-amber-500 mt-0.5">{hint}</span>}
        </p>
      ) : (
        <div className="flex gap-2">
          <NativeSelect value={provider} onChange={v => { setProvider(v as Provider); setModel('') }} className="w-40 shrink-0">
            <option value="">— provider —</option>
            {availableProviders.map(p => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </NativeSelect>
          <div className="relative flex-1">
            {loading && provider ? (
              <div className="flex h-8 items-center px-2 rounded-md border border-input text-xs text-muted-foreground gap-2">
                <Loader2 size={11} className="animate-spin" /> Loading…
              </div>
            ) : (
              <NativeSelect value={model} onChange={setModel} disabled={!provider || models.length === 0}>
                <option value="">
                  {!provider ? '— select provider first —' : models.length === 0 ? '— no models —' : '— select model —'}
                </option>
                {models.slice().sort((a, b) => a.name.localeCompare(b.name)).map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </NativeSelect>
            )}
          </div>
        </div>
      )}

      {dirty && (
        <Button size="sm" onClick={handleSave} disabled={save.isPending || (enabled && (!provider || !model))} className="h-7 text-xs gap-1.5">
          {save.isPending && <Loader2 size={11} className="animate-spin" />}Save
        </Button>
      )}
    </div>
  )
}

export default function SeriesAgentModels({ seriesId }: { seriesId: string }) {
  const { data: globalSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: fetchGlobalSettings,
  })
  const { data: rows, isLoading } = useQuery({
    queryKey: ['series-agent-models', seriesId],
    queryFn: () => fetchSeriesAgentModels(seriesId),
  })

  const { modelsForProvider, isLoadingForProvider, availableProviders } = useProviderModels({
    geminiKey: globalSettings?.gemini_api_key ?? '',
    openrouterKey: globalSettings?.openrouter_api_key ?? '',
    anthropicKey: globalSettings?.anthropic_api_key ?? '',
    openaiKey: globalSettings?.openai_api_key ?? '',
    ollamaHost: globalSettings?.ollama_host ?? 'http://localhost:11434',
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={14} className="text-muted-foreground" />
        <h2 className="text-sm font-medium">Agent Models</h2>
      </div>
      <p className="text-xs text-muted-foreground pl-5">
        Override the model used for each agent for every book in this series. Anything left off uses the global default from Settings.
      </p>

      {isLoading || !rows ? (
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : (
        <div className="rounded-md border border-border overflow-hidden">
          {AGENTS.map(agent => (
            <AgentModelRowEditor
              key={agent.key}
              seriesId={seriesId}
              agentKey={agent.key}
              label={agent.label}
              description={agent.description}
              hint={agent.hint}
              row={rows[agent.key] ?? { provider: null, model: null, effective_provider: null, effective_model: null }}
              availableProviders={availableProviders}
              modelsForProvider={modelsForProvider}
              isLoadingForProvider={isLoadingForProvider}
            />
          ))}
        </div>
      )}
    </div>
  )
}
