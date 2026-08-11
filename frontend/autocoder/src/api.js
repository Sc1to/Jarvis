import axios from 'axios'

const api = axios.create({ baseURL: '/autocoder/api' })

export const getSessions = () => api.get('/sessions')
export const getSession = (id) => api.get(`/sessions/${id}`)
export const getSessionLog = (id) => api.get(`/sessions/${id}/log`)
export const getSessionInternet = (id) => api.get(`/sessions/${id}/internet`)

export const getProjects = () => api.get('/projects')
export const getProject = (id) => api.get(`/projects/${id}`)
export const getProjectSessions = (id) => api.get(`/projects/${id}/sessions`)
export const getProjectCommits = (id) => api.get(`/projects/${id}/commits`)
export const getCommitDiff = (projectId, hash) => api.get(`/projects/${projectId}/commits/${hash}/diff`)
export const createProject = (name, description) => api.post('/projects', { name, description })
export const exportProject = (projectId, destPath) =>
  api.post(`/projects/${projectId}/export`, { dest_path: destPath })

export const getAgentsStatus = () => api.get('/agents/status')
export const getOllamaModels = () => api.get('/ollama/models')

export const startSession = (projectId, requirements, models, workPath) =>
  api.post('/session/start', {
    project_id: projectId,
    requirements_document: requirements,
    ...(models && Object.keys(models).length ? { models } : {}),
    ...(workPath ? { work_path: workPath } : {}),
  })

export function openSessionWs(sessionId, onEvent) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${proto}//${location.host}/autocoder/api/ws/session/${sessionId}`)
  ws.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch {}
  }
  return ws
}
