import axios from 'axios'

const api = axios.create({ baseURL: '/admin/api' })

// System
export const getHealth = () => api.get('/health')
export const getStats = () => api.get('/stats')
export const getHealthCheck = () => api.get('/health-check')

// Apps
export const getApps = () => api.get('/apps')
export const createApp = (data) => api.post('/apps', data)
export const deleteApp = (id) => api.delete(`/apps/${id}`)
export const restartApp = (id) => api.post(`/apps/${id}/restart`)
export const getAppAgents = (appId) => api.get(`/apps/${appId}/agents`)

// Ollama
export const getModels = () => api.get('/ollama/models')
export const getRunningModels = () => api.get('/ollama/running')
export const deleteModel = (name) => api.delete(`/ollama/models/${encodeURIComponent(name)}`)
export const unloadModels = () => api.post('/ollama/unload')

// Tailscale
export const getTailscale = () => api.get('/tailscale/status')

// Updates
export const getUpdates = () => api.get('/updates/available')
export const applyUpdates = () => api.post('/updates/apply')
export const gitPull = () => api.post('/git/pull')
export const restartService = (app) => api.post(`/services/${app}/restart`)
export const deployService = (app) => api.post(`/services/${app}/deploy`)
export const getServiceHealth = (app) => api.get(`/services/${app}/health`)
export const getServicesStatus = () => api.get('/services/status')

// Agents
export const getAgents = () => api.get('/agents')
export const createAgent = (data) => api.post('/agents', data)
export const updateAgent = (id, data) => api.put(`/agents/${id}`, data)
export const deleteAgent = (id) => api.delete(`/agents/${id}`)
export const deployAgent = (id) => api.post(`/agents/${id}/deploy`)
export const stopAgent = (id) => api.post(`/agents/${id}/stop`)

// App prompts
export const getAppPrompts = () => api.get('/app-prompts')
export const updateAppPrompt = (app, key, system_prompt) => api.patch(`/app-prompts/${app}/${key}`, { system_prompt })

// Platform events
export const getPlatformEvents = (limit = 20) => api.get(`/platform-events?limit=${limit}`)

// Ollama pull — streaming via fetch (axios doesn't stream)
export function pullModel(name, onProgress) {
  return fetch('/admin/api/ollama/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }).then(async (resp) => {
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.trim()) continue
        try { onProgress(JSON.parse(line)) } catch {}
      }
    }
  })
}
