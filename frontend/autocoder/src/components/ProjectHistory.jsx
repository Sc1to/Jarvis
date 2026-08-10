import { useEffect, useState } from 'react'
import { getProjects, getProjectSessions } from '../api'

export default function ProjectHistory({ onViewReview }) {
  const [projects, setProjects] = useState([])
  const [selected, setSelected] = useState(null)
  const [sessions, setSessions] = useState([])

  useEffect(() => {
    getProjects().then((r) => {
      const list = r.data.data
      setProjects(list)
      if (list.length > 0) setSelected(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) return
    getProjectSessions(selected)
      .then((r) => setSessions(r.data.data))
      .catch(() => {})
  }, [selected])

  const OUTCOME_CLS = {
    success: 'text-green-400',
    parked:  'text-amber-400',
    failed:  'text-red-400',
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-lg font-semibold text-gray-200">Project History</h2>
        <select
          className="ml-auto bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
          value={selected || ''}
          onChange={(e) => setSelected(Number(e.target.value))}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {projects.length === 0 && (
        <p className="text-gray-600 text-sm">No projects yet.</p>
      )}

      <div className="space-y-2">
        {sessions.map((s) => {
          const duration = s.closed_at
            ? Math.round((new Date(s.closed_at) - new Date(s.started_at)) / 60000)
            : null
          return (
            <button
              key={s.id}
              className="w-full text-left bg-gray-900 rounded-xl p-4 hover:bg-gray-800 transition-colors"
              onClick={() => onViewReview && onViewReview(s.id)}
            >
              <div className="flex items-center gap-3">
                <span className={`text-sm font-medium ${OUTCOME_CLS[s.outcome] || 'text-gray-400'}`}>
                  {s.outcome || s.status}
                </span>
                <span className="text-gray-300 text-sm flex-1 truncate">{s.description}</span>
                {duration !== null && (
                  <span className="text-gray-600 text-xs flex-shrink-0">{duration} min</span>
                )}
              </div>
              <p className="text-gray-600 text-xs mt-1">
                {new Date(s.started_at).toLocaleString()}
              </p>
            </button>
          )
        })}
        {sessions.length === 0 && selected && (
          <p className="text-gray-600 text-sm">No sessions for this project yet.</p>
        )}
      </div>
    </div>
  )
}
