import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { API } from '@/lib/api'

async function fetchSettings(): Promise<Record<string, string>> {
  const r = await fetch(`${API}/settings`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function saveSettings(data: Record<string, string>) {
  await fetch(`${API}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

type Provider = 'gemini' | 'openrouter' | 'anthropic' | 'openai' | 'ollama' | ''

interface AgentAssignment { provider: Provider; model: string }

const AGENTS: { key: string; label: string; description: string; hint?: string }[] = [
  { key: 'story_architect',  label: 'Story Architect',            description: 'North Star creation conversation' },
  { key: 'bible_agent',      label: 'Bible Agent',                description: 'Tiered bible iteration passes',     hint: 'Long context recommended' },
  { key: 'research_agent',   label: 'Research & Completion',      description: 'Phase 2 enrichment and entity completion' },
  { key: 'writer_agent',     label: 'Writer Agent',               description: 'Scene prose generation' },
  { key: 'qa_agent',         label: 'QA Agent',                   description: 'Scene quality and consistency checking', hint: 'Largest context window available — see spec §6.1' },
  { key: 'bible_updater',    label: 'Bible Updater',              description: 'Structured bible updates post-scene', hint: 'Reliable JSON output recommended' },
]

function StatusDot({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="inline-block w-2 h-2 rounded-full bg-muted-foreground/40" />
  return ok
    ? <CheckCircle size={14} className="text-emerald-500" />
    : <XCircle size={14} className="text-red-500" />
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
        'flex h-9 w-full rounded-md border border-input bg-background text-foreground px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
    >
      {children}
    </select>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data: saved = {} } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const mutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })

  const [geminiKey, setGeminiKey]           = useState('')
  const [openrouterKey, setOpenrouterKey]   = useState('')
  const [anthropicKey, setAnthropicKey]     = useState('')
  const [openaiKey, setOpenaiKey]           = useState('')
  const [ollamaHost, setOllamaHost]         = useState('http://localhost:11434')
  const [autoMode, setAutoMode]         = useState(false)
  const [agents, setAgents] = useState<Record<string, AgentAssignment>>(() =>
    Object.fromEntries(AGENTS.map(a => [a.key, { provider: '' as Provider, model: '' }]))
  )

  useEffect(() => {
    if (saved.gemini_api_key)     setGeminiKey(saved.gemini_api_key)
    if (saved.openrouter_api_key) setOpenrouterKey(saved.openrouter_api_key)
    if (saved.anthropic_api_key)  setAnthropicKey(saved.anthropic_api_key)
    if (saved.openai_api_key)     setOpenaiKey(saved.openai_api_key)
    if (saved.ollama_host)        setOllamaHost(saved.ollama_host)
    if (saved.auto_mode)          setAutoMode(saved.auto_mode === 'true')
    // Restore agent assignments from saved settings
    setAgents(prev => {
      const next = { ...prev }
      for (const a of AGENTS) {
        next[a.key] = {
          provider: (saved[`agent_${a.key}_provider`] ?? '') as Provider,
          model:    saved[`agent_${a.key}_model`]    ?? '',
        }
      }
      return next
    })
  }, [saved])

  // Live model lists — fetched once keys are entered
  const geminiModels = useQuery({
    queryKey: ['models', 'gemini', geminiKey],
    queryFn: () => fetch(`${API}/models/gemini`).then(r => r.ok ? r.json() as Promise<{ id: string; name: string }[]> : Promise.reject()),
    enabled: geminiKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const orModels = useQuery({
    queryKey: ['models', 'openrouter', openrouterKey],
    queryFn: () => fetch(`${API}/models/openrouter`).then(r => r.ok ? r.json() as Promise<{ id: string; name: string; free: boolean }[]> : Promise.reject()),
    enabled: openrouterKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const anthropicModels = useQuery({
    queryKey: ['models', 'anthropic', anthropicKey],
    queryFn: () => fetch(`${API}/models/anthropic`).then(r => r.ok ? r.json() as Promise<{ id: string; name: string }[]> : Promise.reject()),
    enabled: anthropicKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const openaiModels = useQuery({
    queryKey: ['models', 'openai', openaiKey],
    queryFn: () => fetch(`${API}/models/openai`).then(r => r.ok ? r.json() as Promise<{ id: string; name: string }[]> : Promise.reject()),
    enabled: openaiKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const ollamaModels = useQuery({
    queryKey: ['models', 'ollama', ollamaHost],
    queryFn: () => fetch(`${API}/models/ollama`).then(r => r.ok ? r.json() as Promise<{ id: string; name: string }[]> : Promise.reject()),
    retry: false,
    refetchInterval: 30_000,
    staleTime: 30_000,
  })

  function modelsForProvider(provider: Provider): { id: string; name: string; free?: boolean }[] {
    if (provider === 'gemini')      return geminiModels.data ?? []
    if (provider === 'openrouter')  return orModels.data ?? []
    if (provider === 'anthropic')   return anthropicModels.data ?? []
    if (provider === 'openai')      return openaiModels.data ?? []
    if (provider === 'ollama')      return ollamaModels.data ?? []
    return []
  }

  function setAgent(key: string, field: 'provider' | 'model', value: string) {
    setAgents(prev => {
      const next = { ...prev, [key]: { ...prev[key], [field]: value } }
      // Reset model when provider changes
      if (field === 'provider') next[key].model = ''
      return next
    })
  }

  function handleSave() {
    const agentSettings: Record<string, string> = {}
    for (const a of AGENTS) {
      agentSettings[`agent_${a.key}_provider`] = agents[a.key].provider
      agentSettings[`agent_${a.key}_model`]    = agents[a.key].model
    }
    mutation.mutate({
      gemini_api_key:      geminiKey,
      openrouter_api_key:  openrouterKey,
      anthropic_api_key:   anthropicKey,
      openai_api_key:      openaiKey,
      ollama_host:         ollamaHost,
      auto_mode:           String(autoMode),
      ...agentSettings,
    })
  }

  const availableProviders: { value: Provider; label: string }[] = [
    ...(anthropicKey.length > 10  ? [{ value: 'anthropic'   as Provider, label: 'Anthropic (Claude)' }] : []),
    ...(openaiKey.length > 10     ? [{ value: 'openai'      as Provider, label: 'OpenAI'              }] : []),
    ...(geminiKey.length > 10     ? [{ value: 'gemini'      as Provider, label: 'Google Gemini'       }] : []),
    ...(openrouterKey.length > 10 ? [{ value: 'openrouter'  as Provider, label: 'OpenRouter'          }] : []),
    { value: 'ollama' as Provider, label: 'Ollama (local)' },
  ]

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Settings</h2>
        <p className="text-sm text-muted-foreground mt-1">Configure providers, then assign a model to each agent.</p>
      </div>

      {/* ── Provider configuration ── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Google Gemini</CardTitle>
          <CardDescription>Free-tier models available. Get your key at aistudio.google.com.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="gemini-key">API Key</Label>
            <div className="flex items-center gap-2">
              <Input id="gemini-key" type="password" value={geminiKey} onChange={e => setGeminiKey(e.target.value)} placeholder="AIza..." className="font-mono text-xs" />
              {geminiModels.isLoading
                ? <Loader2 size={14} className="animate-spin text-muted-foreground" />
                : <StatusDot ok={geminiKey.length > 10 ? !geminiModels.isError : null} />}
            </div>
          </div>
          {geminiModels.data && (
            <p className="text-xs text-muted-foreground">{geminiModels.data.length} models available</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">OpenRouter</CardTitle>
          <CardDescription>Real-time model list with pricing. Free models labelled clearly.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="or-key">API Key</Label>
            <div className="flex items-center gap-2">
              <Input id="or-key" type="password" value={openrouterKey} onChange={e => setOpenrouterKey(e.target.value)} placeholder="sk-or-..." className="font-mono text-xs" />
              {orModels.isLoading
                ? <Loader2 size={14} className="animate-spin text-muted-foreground" />
                : <StatusDot ok={openrouterKey.length > 10 ? !orModels.isError : null} />}
            </div>
          </div>
          {orModels.data && (
            <p className="text-xs text-muted-foreground">
              {orModels.data.length} models · {orModels.data.filter(m => m.free).length} free
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Anthropic (Claude)</CardTitle>
          <CardDescription>Claude models. Get your key at console.anthropic.com.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="anthropic-key">API Key</Label>
            <div className="flex items-center gap-2">
              <Input id="anthropic-key" type="password" value={anthropicKey} onChange={e => setAnthropicKey(e.target.value)} placeholder="sk-ant-..." className="font-mono text-xs" />
              {anthropicModels.isLoading
                ? <Loader2 size={14} className="animate-spin text-muted-foreground" />
                : <StatusDot ok={anthropicKey.length > 10 ? !anthropicModels.isError : null} />}
            </div>
          </div>
          {anthropicModels.data && (
            <p className="text-xs text-muted-foreground">{anthropicModels.data.length} models available</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">OpenAI</CardTitle>
          <CardDescription>GPT and o-series models. Get your key at platform.openai.com.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="openai-key">API Key</Label>
            <div className="flex items-center gap-2">
              <Input id="openai-key" type="password" value={openaiKey} onChange={e => setOpenaiKey(e.target.value)} placeholder="sk-..." className="font-mono text-xs" />
              {openaiModels.isLoading
                ? <Loader2 size={14} className="animate-spin text-muted-foreground" />
                : <StatusDot ok={openaiKey.length > 10 ? !openaiModels.isError : null} />}
            </div>
          </div>
          {openaiModels.data && (
            <p className="text-xs text-muted-foreground">{openaiModels.data.length} models available</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Local (Ollama)</CardTitle>
          <CardDescription>Models served from your local Ollama instance. No API key required.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="ollama-host">Host URL</Label>
            <div className="flex items-center gap-2">
              <Input id="ollama-host" value={ollamaHost} onChange={e => setOllamaHost(e.target.value)} placeholder="http://localhost:11434" className="font-mono text-xs" />
              {ollamaModels.isLoading
                ? <Loader2 size={14} className="animate-spin text-muted-foreground" />
                : <StatusDot ok={!ollamaModels.isError} />}
            </div>
          </div>
          {ollamaModels.isError && <p className="text-xs text-muted-foreground">Not reachable — optional until local hardware is available.</p>}
          {ollamaModels.data && <p className="text-xs text-muted-foreground">{ollamaModels.data.length} models available</p>}
        </CardContent>
      </Card>

      <Separator />

      {/* ── Agent model assignment ── */}
      <div>
        <h3 className="text-base font-semibold">Agent Models</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Each agent has an independent model assignment. Enter at least one API key above, then select provider and model per agent.
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          {AGENTS.map((agent, i) => {
            const assignment = agents[agent.key]
            const models = modelsForProvider(assignment.provider)
            const loading = assignment.provider === 'gemini'     ? geminiModels.isLoading
              : assignment.provider === 'openrouter' ? orModels.isLoading
              : assignment.provider === 'anthropic'  ? anthropicModels.isLoading
              : assignment.provider === 'openai'     ? openaiModels.isLoading
              : assignment.provider === 'ollama'     ? ollamaModels.isLoading
              : false

            return (
              <div key={agent.key} className={cn('px-5 py-4 space-y-3', i < AGENTS.length - 1 && 'border-b border-border')}>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{agent.label}</p>
                    {assignment.provider && assignment.model && (
                      <Badge variant="success" className="text-xs">{assignment.provider}</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{agent.description}</p>
                  {agent.hint && <p className="text-xs text-amber-500 mt-0.5">{agent.hint}</p>}
                </div>

                <div className="flex gap-2">
                  {/* Provider selector */}
                  <NativeSelect
                    value={assignment.provider}
                    onChange={v => setAgent(agent.key, 'provider', v)}
                    className="w-44 shrink-0 text-xs"
                  >
                    <option value="">— provider —</option>
                    {availableProviders.map(p => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </NativeSelect>

                  {/* Model selector */}
                  <div className="relative flex-1">
                    {loading && assignment.provider ? (
                      <div className="flex h-9 items-center px-3 rounded-md border border-input text-xs text-muted-foreground gap-2">
                        <Loader2 size={12} className="animate-spin" /> Loading models…
                      </div>
                    ) : (
                      <NativeSelect
                        value={assignment.model}
                        onChange={v => setAgent(agent.key, 'model', v)}
                        disabled={!assignment.provider || models.length === 0}
                        className="text-xs"
                      >
                        <option value="">
                          {!assignment.provider ? '— select provider first —'
                            : models.length === 0 ? '— save API key first —'
                            : '— select model —'}
                        </option>
                        {assignment.provider === 'openrouter'
                          ? <>
                              {models.filter((m: any) => m.free).length > 0 && (
                                <optgroup label="Free">
                                  {models.filter((m: any) => m.free).sort((a, b) => a.name.localeCompare(b.name)).map(m => (
                                    <option key={m.id} value={m.id}>{m.name}</option>
                                  ))}
                                </optgroup>
                              )}
                              <optgroup label="Paid">
                                {models.filter((m: any) => !m.free).sort((a, b) => a.name.localeCompare(b.name)).map(m => (
                                  <option key={m.id} value={m.id}>{m.name}</option>
                                ))}
                              </optgroup>
                            </>
                          : models.slice().sort((a, b) => a.name.localeCompare(b.name)).map(m => (
                              <option key={m.id} value={m.id}>{m.name}</option>
                            ))
                        }
                      </NativeSelect>
                    )}
                  </div>
                </div>

                {/* Show selected model clearly */}
                {assignment.model && (
                  <p className="text-xs font-mono text-muted-foreground truncate">{assignment.model}</p>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Separator />

      {/* ── Writing loop ── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Writing Loop</CardTitle>
          <CardDescription>Controls how Phase 3 advances between scenes.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Automatic mode</p>
              <p className="text-xs text-muted-foreground">When QA passes, advance to the next scene without approval.</p>
            </div>
            <Switch checked={autoMode} onCheckedChange={setAutoMode} />
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-3">
        {mutation.isSuccess && <p className="text-sm text-emerald-500 self-center">Saved.</p>}
        <Button onClick={handleSave} disabled={mutation.isPending}>
          {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
          Save settings
        </Button>
      </div>
    </div>
  )
}
