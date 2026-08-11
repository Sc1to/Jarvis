import { useEffect, useState } from 'react'
import { getProjects, getOllamaModels, createProject, startSession } from '../api'

const AGENTS = [
  { key: 'conductor', label: 'Conductor' },
  { key: 'backend',   label: 'Backend' },
  { key: 'frontend',  label: 'Frontend' },
  { key: 'db',        label: 'DB' },
  { key: 'tester',    label: 'Tester' },
  { key: 'refactorer',label: 'Refactorer' },
]

const DEFAULTS = { conductor: 'qwen2.5:72b-instruct-q4_K_M', specialist: 'qwen2.5-coder:32b' }

export default function StartSession({ onStarted }) {
  const [projects, setProjects] = useState([])
  const [ollamaModels, setOllamaModels] = useState([])
  const [projectId, setProjectId] = useState('')
  const [requirements, setRequirements] = useState('')
  const [models, setModels] = useState({})
  const [workPath, setWorkPath] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Create-project inline form state
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  useEffect(() => {
    getProjects().then((r) => setProjects(r.data.data)).catch(() => {})
    getOllamaModels().then((r) => setOllamaModels(r.data.data || [])).catch(() => {})
  }, [])

  const handleModelChange = (agentKey, value) => {
    setModels((prev) => ({ ...prev, [agentKey]: value }))
  }

  const handleCreateProject = async () => {
    if (!newName.trim()) { setCreateError('Name is required'); return }
    setCreating(true)
    setCreateError('')
    try {
      const r = await createProject(newName.trim(), newDesc.trim())
      const p = r.data.data
      setProjects((prev) => [...prev, p])
      setProjectId(String(p.id))
      setShowCreate(false)
      setNewName('')
      setNewDesc('')
    } catch (e) {
      setCreateError(e.response?.data?.detail || 'Failed to create project')
    } finally {
      setCreating(false)
    }
  }

  const submit = async () => {
    setError('')
    if (!requirements.trim()) { setError('Requirements document is required.'); return }
    setLoading(true)
    try {
      // Only send non-empty model overrides
      const modelOverrides = Object.fromEntries(
        Object.entries(models).filter(([, v]) => v && v.trim())
      )
      const r = await startSession(
        projectId ? Number(projectId) : null,
        requirements,
        Object.keys(modelOverrides).length ? modelOverrides : null,
        workPath.trim() || null,
      )
      onStarted?.(r.data.data.session_id)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to start session')
    } finally {
      setLoading(false)
    }
  }

  const modelSelect = (agentKey, placeholder) => (
    <select
      className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200"
      value={models[agentKey] || ''}
      onChange={(e) => handleModelChange(agentKey, e.target.value)}
    >
      <option value="">{placeholder}</option>
      {ollamaModels.map((m) => <option key={m} value={m}>{m}</option>)}
    </select>
  )

  return (
    <div className="max-w-2xl space-y-5">
      <h2 className="text-lg font-semibold text-gray-200">Start New Session</h2>

      {/* Project picker + create */}
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

      {/* Requirements */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Requirements document</label>
        <p className="text-xs text-gray-600 mb-2">
          Must include: Objective, Scope, Constraints, Acceptance Criteria, Tech Context
        </p>
        <textarea
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 font-mono h-56 resize-y"
          placeholder="## Objective&#10;...&#10;&#10;## Scope&#10;...&#10;&#10;## Constraints&#10;...&#10;&#10;## Acceptance Criteria&#10;...&#10;&#10;## Tech Context&#10;..."
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
        />
      </div>

      {/* Model selection */}
      <div>
        <label className="block text-xs text-gray-500 mb-2">Model overrides (leave blank for defaults)</label>
        <div className="space-y-1.5">
          {AGENTS.map(({ key, label }) => {
            const placeholder = key === 'conductor'
              ? `default: ${DEFAULTS.conductor}`
              : `default: ${DEFAULTS.specialist}`
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="text-xs text-gray-400 w-20 flex-shrink-0">{label}</span>
                {modelSelect(key, placeholder)}
              </div>
            )
          })}
        </div>
      </div>

      {/* Working path */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Working path <span className="text-gray-600">(optional — where code is written during the run)</span>
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
        disabled={loading}
      >
        {loading ? 'Starting…' : 'Start Session'}
      </button>
    </div>
  )
}
