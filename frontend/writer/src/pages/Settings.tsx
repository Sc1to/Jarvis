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
import { AGENTS, type Provider, type AgentAssignment } from '@/lib/agents'
import { useProviderModels } from '@/lib/useProviderModels'

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

// ponytail: stable empty object so useEffect([saved]) doesn't loop while query loads
const EMPTY_SETTINGS: Record<string, string> = {}

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
  const { data: saved = EMPTY_SETTINGS } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const mutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })

  const [geminiKey, setGeminiKey]           = useState('')
  const [openrouterKey, setOpenrouterKey]   = useState('')
  const [anthropicKey, setAnthropicKey]     = useState('')
  const [openaiKey, setOpenaiKey]           = useState('')
  const [ollamaHost, setOllamaHost]         = useState('http://localhost:11434')
  const [qaRetryManual, setQaRetryManual] = useState(false)
  const [qaStyleCheckEvery, setQaStyleCheckEvery] = useState('3')
  const [qaStopAutoWriteOnUnresolved, setQaStopAutoWriteOnUnresolved] = useState(false)
  const [agents, setAgents] = useState<Record<string, AgentAssignment>>(() =>
    Object.fromEntries(AGENTS.map(a => [a.key, { provider: '' as Provider, model: '' }]))
  )

  useEffect(() => {
    if (saved.gemini_api_key)     setGeminiKey(saved.gemini_api_key)
    if (saved.openrouter_api_key) setOpenrouterKey(saved.openrouter_api_key)
    if (saved.anthropic_api_key)  setAnthropicKey(saved.anthropic_api_key)
    if (saved.openai_api_key)     setOpenaiKey(saved.openai_api_key)
    if (saved.ollama_host)        setOllamaHost(saved.ollama_host)
    if (saved.qa_retry_manual)    setQaRetryManual(saved.qa_retry_manual === 'true')
    if (saved.qa_style_check_every_n_scenes) setQaStyleCheckEvery(saved.qa_style_check_every_n_scenes)
    if (saved.qa_stop_auto_write_on_unresolved) setQaStopAutoWriteOnUnresolved(saved.qa_stop_auto_write_on_unresolved === 'true')
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
  const {
    geminiModels, orModels, anthropicModels, openaiModels, ollamaModels,
    modelsForProvider, isLoadingForProvider, availableProviders,
  } = useProviderModels({ geminiKey, openrouterKey, anthropicKey, openaiKey, ollamaHost })

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
      qa_retry_manual:     String(qaRetryManual),
      qa_style_check_every_n_scenes: String(Math.max(1, parseInt(qaStyleCheckEvery, 10) || 3)),
      qa_stop_auto_write_on_unresolved: String(qaStopAutoWriteOnUnresolved),
      ...agentSettings,
    })
  }

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
            const loading = isLoadingForProvider(assignment.provider)

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
          <CardDescription>Controls how Phase 3 runs QA on scenes.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium">Retry failed QA on manual writes</p>
              <p className="text-xs text-muted-foreground">
                When off, <span className="font-medium">Write Chapter</span> keeps the first draft of a scene that fails QA
                and shows you what was flagged so you can decide. <span className="font-medium">Auto-write all</span> always retries (up to 3 attempts).
              </p>
            </div>
            <Switch checked={qaRetryManual} onCheckedChange={setQaRetryManual} />
          </div>

          <Separator />

          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium">Stop auto-write on unresolved QA</p>
              <p className="text-xs text-muted-foreground">
                When on, <span className="font-medium">Auto-write all</span> stops the run if a scene still fails QA
                after 3 attempts, instead of continuing past it. The chapter is saved in progress so you can
                review the flagged scene and resume from the Writing Loop.
              </p>
            </div>
            <Switch checked={qaStopAutoWriteOnUnresolved} onCheckedChange={setQaStopAutoWriteOnUnresolved} />
          </div>

          <Separator />

          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium">Series style check cadence</p>
              <p className="text-xs text-muted-foreground">
                For books in a series, QA checks the scene against the series style sheet every Nth scene
                instead of every scene, to keep the QA prompt from growing on every check.
              </p>
            </div>
            <Input
              id="qa-style-check-every"
              type="number"
              min={1}
              value={qaStyleCheckEvery}
              onChange={e => setQaStyleCheckEvery(e.target.value)}
              className="w-20 text-center"
            />
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
