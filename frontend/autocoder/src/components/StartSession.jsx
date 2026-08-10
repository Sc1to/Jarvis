import { useEffect, useState } from 'react'
import { getProjects, startSession } from '../api'

export default function StartSession({ onStarted }) {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [requirements, setRequirements] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getProjects().then((r) => setProjects(r.data.data)).catch(() => {})
  }, [])

  const submit = async () => {
    setError('')
    if (!requirements.trim()) { setError('Requirements document is required.'); return }
    setLoading(true)
    try {
      const r = await startSession(projectId ? Number(projectId) : null, requirements)
      onStarted?.(r.data.data.session_id)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to start session')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-4">
      <h2 className="text-lg font-semibold text-gray-200">Start New Session</h2>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Project (optional)</label>
        <select
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        >
          <option value="">— No project —</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Requirements document</label>
        <p className="text-xs text-gray-600 mb-2">
          Must include: Objective, Scope, Constraints, Acceptance Criteria, Tech Context
        </p>
        <textarea
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 font-mono h-64 resize-y"
          placeholder="## Objective&#10;...&#10;&#10;## Scope&#10;...&#10;&#10;## Constraints&#10;...&#10;&#10;## Acceptance Criteria&#10;...&#10;&#10;## Tech Context&#10;..."
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
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
