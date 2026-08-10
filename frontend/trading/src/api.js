import axios from 'axios'

const api = axios.create({ baseURL: '/trading/api' })
const auditorApi = axios.create({ baseURL: '/trading/audit' })

// Health & status
export const getHealth = () => api.get('/health')
export const getStatus = () => api.get('/status')

// Mode
export const getMode = () => api.get('/mode')
export const setMode = (mode, confirm = false) => api.post('/mode', { mode, confirm })

// Config
export const getConfig = () => api.get('/config')
export const setConfig = (key, value) => api.post(`/config/${key}`, { value })

// Positions
export const getPositions = (pool) =>
  api.get('/positions', { params: pool ? { pool } : {} })
export const getPositionHistory = (limit = 50) =>
  api.get('/positions/history', { params: { limit } })

// Signals
export const getSignals = (limit = 50, pool) =>
  api.get('/signals', { params: { limit, ...(pool ? { pool } : {}) } })
export const getConvictionSignals = (limit = 50, pool) =>
  api.get('/signals/conviction', { params: { limit, ...(pool ? { pool } : {}) } })

// Briefs
export const getBriefLatest = () => api.get('/briefs/latest')
export const getBriefs = (limit = 10) => api.get('/briefs', { params: { limit } })

// WSB
export const getWsbPosts = (limit = 25) => api.get('/wsb/posts', { params: { limit } })
export const getWsbTopMentions = (hours = 2, limit = 20) =>
  api.get('/wsb/top-mentions', { params: { hours, limit } })
export const getWsbCorrelation = (limit = 20) =>
  api.get('/wsb/correlation', { params: { limit } })
export const getWsbMentions = (ticker, limit = 50) =>
  api.get('/wsb/mentions', { params: { ticker, limit } })

// Catalysts
export const getCatalysts = (ticker) =>
  api.get('/catalysts', { params: ticker ? { ticker } : {} })
export const addCatalyst = (body) => api.post('/catalysts', body)
export const resolveCatalyst = (id, outcome, notes = '') =>
  api.post(`/catalysts/${id}/resolve`, { outcome, notes })

// Universe
export const getUniverse = (pool) =>
  api.get('/universe', { params: pool ? { pool } : {} })
export const addToUniverse = (pool, ticker) =>
  api.post(`/universe/${pool}/${ticker}`)
export const removeFromUniverse = (pool, ticker) =>
  api.delete(`/universe/${pool}/${ticker}`)

// Risk gate
export const getRiskGateLog = (limit = 50) =>
  api.get('/risk-gate-log', { params: { limit } })

// Learning
export const getLearningWeights = () => api.get('/learning/weights')

// Audit (separate service at port 8031)
export const getAuditLatest = () => auditorApi.get('/audit/latest')
export const getAuditHistory = (limit = 20) =>
  auditorApi.get('/audit/history', { params: { limit } })
export const triggerAudit = () => auditorApi.post('/audit/run')

// Validation
export const getValidationStatus = () => api.get('/validation/status')

// Notifications
export const getVapidPublicKey = () => api.get('/notifications/vapid-key')
export const subscribeNotifications = (sub) => api.post('/notifications/subscribe', sub)
export const unsubscribeNotifications = (endpoint) =>
  api.post('/notifications/unsubscribe', { endpoint })
