import { useQuery } from '@tanstack/react-query'
import { API } from '@/lib/api'
import type { Provider } from '@/lib/agents'

export interface ModelInfo { id: string; name: string; free?: boolean }

interface ProviderKeys {
  geminiKey: string
  openrouterKey: string
  anthropicKey: string
  openaiKey: string
  ollamaHost: string
}

/** Live per-provider model lists, shared between the global Settings page and any
 * other UI (e.g. per-series overrides) that needs to pick a provider + model. */
export function useProviderModels({ geminiKey, openrouterKey, anthropicKey, openaiKey, ollamaHost }: ProviderKeys) {
  const geminiModels = useQuery({
    queryKey: ['models', 'gemini', geminiKey],
    queryFn: () => fetch(`${API}/models/gemini`).then(r => r.ok ? r.json() as Promise<ModelInfo[]> : Promise.reject()),
    enabled: geminiKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const orModels = useQuery({
    queryKey: ['models', 'openrouter', openrouterKey],
    queryFn: () => fetch(`${API}/models/openrouter`).then(r => r.ok ? r.json() as Promise<ModelInfo[]> : Promise.reject()),
    enabled: openrouterKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const anthropicModels = useQuery({
    queryKey: ['models', 'anthropic', anthropicKey],
    queryFn: () => fetch(`${API}/models/anthropic`).then(r => r.ok ? r.json() as Promise<ModelInfo[]> : Promise.reject()),
    enabled: anthropicKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const openaiModels = useQuery({
    queryKey: ['models', 'openai', openaiKey],
    queryFn: () => fetch(`${API}/models/openai`).then(r => r.ok ? r.json() as Promise<ModelInfo[]> : Promise.reject()),
    enabled: openaiKey.length > 10,
    retry: false,
    staleTime: 60_000,
  })
  const ollamaModels = useQuery({
    queryKey: ['models', 'ollama', ollamaHost],
    queryFn: () => fetch(`${API}/models/ollama`).then(r => r.ok ? r.json() as Promise<ModelInfo[]> : Promise.reject()),
    retry: false,
    refetchInterval: 30_000,
    staleTime: 30_000,
  })

  function modelsForProvider(provider: Provider): ModelInfo[] {
    if (provider === 'gemini')      return geminiModels.data ?? []
    if (provider === 'openrouter')  return orModels.data ?? []
    if (provider === 'anthropic')   return anthropicModels.data ?? []
    if (provider === 'openai')      return openaiModels.data ?? []
    if (provider === 'ollama')      return ollamaModels.data ?? []
    return []
  }

  function isLoadingForProvider(provider: Provider): boolean {
    if (provider === 'gemini')      return geminiModels.isLoading
    if (provider === 'openrouter')  return orModels.isLoading
    if (provider === 'anthropic')   return anthropicModels.isLoading
    if (provider === 'openai')      return openaiModels.isLoading
    if (provider === 'ollama')      return ollamaModels.isLoading
    return false
  }

  const availableProviders: { value: Provider; label: string }[] = [
    ...(anthropicKey.length > 10  ? [{ value: 'anthropic'   as Provider, label: 'Anthropic (Claude)' }] : []),
    ...(openaiKey.length > 10     ? [{ value: 'openai'      as Provider, label: 'OpenAI'              }] : []),
    ...(geminiKey.length > 10     ? [{ value: 'gemini'      as Provider, label: 'Google Gemini'       }] : []),
    ...(openrouterKey.length > 10 ? [{ value: 'openrouter'  as Provider, label: 'OpenRouter'          }] : []),
    { value: 'ollama' as Provider, label: 'Ollama (local)' },
  ]

  return {
    geminiModels, orModels, anthropicModels, openaiModels, ollamaModels,
    modelsForProvider, isLoadingForProvider, availableProviders,
  }
}
