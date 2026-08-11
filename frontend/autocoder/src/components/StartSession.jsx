import { useEffect, useRef, useState } from 'react'
import {
  getProjects, getOllamaModels, createProject, startSession,
  startReSession, sendReMessage,
} from '../api'

const AGENTS = [
  { key: 'conductor', label: 'Conductor' },
  { key: 'backend',   label: 'Backend' },
  { key: 'frontend',  label: 'Frontend' },
  { key: 'db',        label: 'DB' },
  { key: 'tester',    label: 'Tester' },
  { key: 'refactorer',label: 'Refactorer' },
]

const DEFAULTS = { conductor: 'qwen2.5:72b-instruct-q4_K_M', specialist: 'qwen2.5-coder:32b' }

function reqToMarkdown(r) {
  if (!r) return ''
  const lines = []
  if (r.objective)   lines.push(`## Objective\n${r.objective}`)
  if (r.scope) {
    const inc = (r.scope.included || []).map((x) => `- ${x}`).join('\n') || '—'
    const exc = (r.scope.excluded || []).map((x) => `- ${x}`).join('\n') || '—'
    lines.push(`## Scope\n### Included\n${inc}\n### Excluded\n${exc}`)
  }
  if (r.constraints?.length)
    lines.push(`## Constraints\n${r.constraints.map((x) => `- ${x}`).join('\n')}`)
  if (r.acceptance_criteria?.length)
    lines.push(`## Acceptance Criteria\n${r.acceptance_criteria.map((x) => `- ${x}`).join('\n')}`)
  if (r.tech_context) lines.push(`## Tech Context\n${r.tech_context}`)
  return lines.join('\n\n')
}

export default function StartSession({ onStarted }) {
  const [projects, setProjects]       = useState([])
  const [ollamaModels, setOllamaModels] = useState([])
  const [projectId, setProjectId]     = useState('')
  const [models, setModels]           = useState({})
  const [workPath, setWorkPath]       = useState('')
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState('')

  // Project create
  const [showCreate, setShowCreate]   = useState(false)
  const [newName, setNewName]         = useState('')
  const [newDesc, setNewDesc]         = useState('')
  const [creating, setCreating]       = useState(false)
  const [createError, setCreateError] = useState('')

  // Mode: 'chat' (RE-agent) or 'manual'
  const [mode, setMode]               = useState('chat')

  // RE-agent chat state
  const [reSessionId, setReSessionId] = useState(null)
  const [messages, setMessages]       = useState([])
  const [chatInput, setChatInput]     = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [reComplete, setReComplete]   = useState(false)

  // Requirements doc (populated from RE-agent or typed manually)
  const [requirements, setRequirements] = useState('')

  const bottomRef = useRef(null)

  useEffect(() => {
    getProjects().then((r) => setProjects(r.data.data)).catch(() => {})
    getOllamaModels().then((r) => setOllamaModels(r.data.data || [])).catch(() => {})
  }, [])

  // Start RE-agent session on mount (chat mode only)
  useEffect(() => {
    if (mode === 'chat') _startReSession()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const _startReSession = async () => {
    setMessages([])
    setReSessionId(null)
    setReComplete(false)
    setRequirements('')
    setChatLoading(true)
    try {
      const r = await startReSession(projectId ? Number(projectId) : null)
      const d = r.data.data
      setReSessionId(d.session_id)
      setMessages([{ role: 'assistant', content: d.message }])
    } catch {
      setMessages([{ role: 'assistant', content: "Couldn't reach the RE-agent. Switch to Manual to write requirements directly." }])
    } finally {
      setChatLoading(false)
    }
  }

  const handleSend = async () => {
    const text = chatInput.trim()
    if (!text || chatLoading || !reSessionId) return
    setChatInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setChatLoading(true)
    try {
      const r = await sendReMessage(reSessionId, text)
      const d = r.data.data
      setMessages((prev) => [...prev, { role: 'assistant', content: d.response }])
      if (d.is_complete && d.requirements_document) {
        setReComplete(true)
        setRequirements(reqToMarkdown(d.requirements_document))
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error — please try again.' }])
    } finally {
      setChatLoading(false)
    }
  }

  const handleCreateProject = async () => {
    if (!newName.trim()) { setCreateError('Name is required'); return }
    setCreating(true); setCreateError('')
    try {
      const r = await createProject(newName.trim(), newDesc.trim())
      const p = r.data.data
      setProjects((prev) => [...prev, p])
      setProjectId(String(p.id))
      setShowCreate(false); setNewName(''); setNewDesc('')
    } catch (e) {
      setCreateError(e.response?.data?.detail || 'Failed to create project')
    } finally { setCreating(false) }
  }

  const submit = async () => {
    setError('')
    if (!requirements.trim()) { setError('Requirements document is required.'); return }
    setLoading(true)
    try {
      const overrides = Object.fromEntries(Object.entries(models).filter(([, v]) => v?.trim()))
      const r = await startSession(
        projectId ? Number(projectId) : null,
        requirements,
        Object.keys(overrides).length ? overrides : null,
        workPath.trim() || null,
      )
      onStarted?.(r.data.data.session_id)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to start session')
    } finally { setLoading(false) }
  }

  const modelSelect = (agentKey, placeholder) => (
    <select
      className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200"
      value={models[agentKey] || ''}
      onChange={(e) => setModels((prev) => ({ ...prev, [agentKey]: e.target.value }))}
    >
      <option value="">{placeholder}</option>
      {ollamaModels.map((m) => <option key={m} value={m}>{m}</option>)}
    </select>
  )

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-gray-200">Start New Session</h2>

      {/* Project picker */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Project (optional)</label>
        <div className="flex gap-2 items-center">
          <select
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="">— No project —</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button
            className="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap px-1"
            onClick={() => setShowCreate((v) => !v)}
          >
            {showCreate ? 'Cancel' : '+ New'}
          </button>
        </div>
        {showCreate && (
          <div className="mt-2 space-y-2 p-3 bg-gray-800/60 rounded-lg border border-gray-700">
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
              placeholder="Project name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
              placeholder="Description (optional)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
            />
            {createError && <p className="text-red-400 text-xs">{createError}</p>}
            <button
              className="bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-xs font-medium px-4 py-1.5 rounded"
              onClick={handleCreateProject}
              disabled={creating}
            >
              {creating ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        )}
      </div>

      {/* Requirements — mode toggle */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs text-gray-500">Requirements</label>
          <div className="flex gap-2 text-xs">
            <button
              onClick={() => setMode('chat')}
              className={mode === 'chat' ? 'text-blue-400 font-medium' : 'text-gray-500 hover:text-gray-300'}
            >
              Chat with RE-agent
            </button>
            <span className="text-gray-700">|</span>
            <button
              onClick={() => setMode('manual')}
              className={mode === 'manual' ? 'text-blue-400 font-medium' : 'text-gray-500 hover:text-gray-300'}
            >
              Manual
            </button>
          </div>
        </div>

        {mode === 'chat' && (
          <div className="space-y-2">
            {/* Chat messages */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg h-72 overflow-y-auto p-3 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === 'user'
                      ? 'bg-blue-700 text-white'
                      : 'bg-gray-800 text-gray-200'
                  }`}>
                    {m.content}
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-800 text-gray-500 text-sm rounded-lg px-3 py-2">…</div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Chat input */}
            {!reComplete && (
              <div className="flex gap-2">
                <input
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
                  placeholder="Type your answer…"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                  disabled={chatLoading || !reSessionId}
                />
                <button
                  className="bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-sm px-4 rounded"
                  onClick={handleSend}
                  disabled={chatLoading || !chatInput.trim() || !reSessionId}
                >
                  Send
                </button>
              </div>
            )}

            {reComplete && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-green-400 font-medium">Requirements ready ✓</span>
                <button
                  className="text-xs text-gray-500 hover:text-gray-300 ml-auto"
                  onClick={_startReSession}
                >
                  Restart chat
                </button>
              </div>
            )}

            {/* Editable requirements doc once complete */}
            {reComplete && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">Generated requirements (edit if needed)</label>
                <textarea
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 font-mono h-48 resize-y"
                  value={requirements}
                  onChange={(e) => setRequirements(e.target.value)}
                />
              </div>
            )}
          </div>
        )}

        {mode === 'manual' && (
          <textarea
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 font-mono h-56 resize-y"
            placeholder="## Objective&#10;...&#10;&#10;## Scope&#10;...&#10;&#10;## Constraints&#10;...&#10;&#10;## Acceptance Criteria&#10;...&#10;&#10;## Tech Context&#10;..."
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
          />
        )}
      </div>

      {/* Model overrides */}
      <div>
        <label className="block text-xs text-gray-500 mb-2">Model overrides (leave blank for defaults)</label>
        <div className="space-y-1.5">
          {AGENTS.map(({ key, label }) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-xs text-gray-400 w-20 flex-shrink-0">{label}</span>
              {modelSelect(key, key === 'conductor' ? `default: ${DEFAULTS.conductor}` : `default: ${DEFAULTS.specialist}`)}
            </div>
          ))}
        </div>
      </div>

      {/* Working path */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Working path <span className="text-gray-600">(optional)</span>
        </label>
        <input
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 font-mono"
          placeholder="/opt/platform/data/projects/<project-name>"
          value={workPath}
          onChange={(e) => setWorkPath(e.target.value)}
        />
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <button
        className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg"
        onClick={submit}
        disabled={loading || (mode === 'chat' && !reComplete)}
        title={mode === 'chat' && !reComplete ? 'Complete the RE-agent chat first' : ''}
      >
        {loading ? 'Starting…' : 'Start Session'}
      </button>
    </div>
  )
}
