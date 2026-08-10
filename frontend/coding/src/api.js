import axios from 'axios'

const api = axios.create({ baseURL: '/coding/api' })

export const getHealth = () => api.get('/health')
export const getTokenStatus = () => api.get('/github/token-status')
export const saveToken = (token) => api.post('/github/token', { token })
export const getProjects = () => api.get('/projects')
export const createProject = (data) => api.post('/projects', data)
export const deleteProject = (id) => api.delete(`/projects/${id}`)
export const getFileTree = (id) => api.get(`/projects/${id}/tree`)
export const getGitStatus = (id) => api.get(`/projects/${id}/git-status`)
export const pushProject = (id, data) => api.post(`/projects/${id}/push`, data)
export const createPR = (id, data) => api.post(`/projects/${id}/create-pr`, data)

/**
 * Stream a chat message. Calls onEvent({type, ...}) for each SSE event.
 * Returns a promise that resolves when the stream ends.
 */
export function streamChat({ projectId, message, history, model = 'qwen2.5-coder:32b', onEvent }) {
  return fetch('/coding/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, message, history, model }),
  }).then(async (resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
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
        if (!line.startsWith('data: ')) continue
        try { onEvent(JSON.parse(line.slice(6))) } catch {}
      }
    }
  })
}
