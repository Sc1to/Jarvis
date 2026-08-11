import { useEffect, useState } from 'react'
import { getProjects, getProjectSessions, exportProject } from '../api'

export default function ProjectHistory({ onViewReview }) {
  const [projects, setProjects] = useState([])
  const [selected, setSelected] = useState(null)
  const [sessions, setSessions] = useState([])

  // Export state
  const [exportPath, setExportPath] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportMsg, setExportMsg] = useState('')

  useEffect(() => {
    getProjects().then((r) => {
      const list = r.data.data
      setProjects(list)
      if (list.length > 0) setSelected(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) return
    setExportMsg('')
    getProjectSessions(selected)
      .then((r) => setSessions(r.data.data))
      .catch(() => {})
  }, [selected])

  const handleExport = async () => {
    if (!exportPath.trim()) return
    setExporting(true)
    setExportMsg('')
    try {
      await exportProject(selected, exportPath.trim())
      setExportMsg(`Copied to ${exportPath.trim()}`)
      setExportPath('')
    } catch (e) {
      setExportMsg(e.response?.data?.detail || 'Export failed')
    } finally {
      setExporting(false)
    }
  }

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

      {/* Export */}
      {selected && (
        <div className="mb-4 flex gap-2 items-center">
          <input
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 font-mono"
            placeholder="Export code to path…"
            value={exportPath}
            onChange={(e) => { setExportPath(e.target.value); setExportMsg('') }}
            onKeyDown={(e) => e.key === 'Enter' && handleExport()}
          />
          <button
            className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-200 text-sm px-3 py-1.5 rounded whitespace-nowrap"
            onClick={handleExport}
            disabled={exporting || !exportPath.trim()}
          >
            {exporting ? 'Copying…' : 'Export'}
          </button>
        </div>
      )}
      {exportMsg && (
        <p className={`text-xs mb-3 ${exportMsg.startsWith('Copied') ? 'text-green-400' : 'text-red-400'}`}>
          {exportMsg}
        </p>
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
