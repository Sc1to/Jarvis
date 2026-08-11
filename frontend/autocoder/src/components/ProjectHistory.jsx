import { useEffect, useState } from 'react'
import { getProjects, getProjectSessions, exportProject, updateProject, deleteProject } from '../api'

export default function ProjectHistory({ onViewReview }) {
  const [projects, setProjects] = useState([])
  const [selected, setSelected] = useState(null)
  const [sessions, setSessions] = useState([])

  // Export
  const [exportPath, setExportPath] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportMsg, setExportMsg] = useState('')

  // Edit
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editError, setEditError] = useState('')
  const [saving, setSaving] = useState(false)

  // Delete
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

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
    setEditing(false)
    setConfirmDelete(false)
    const p = projects.find((x) => x.id === selected)
    if (p) { setEditName(p.name); setEditDesc(p.description || '') }
    getProjectSessions(selected)
      .then((r) => setSessions(r.data.data))
      .catch(() => {})
  }, [selected])

  const selectedProject = projects.find((p) => p.id === selected)

  const handleExport = async () => {
    if (!exportPath.trim()) return
    setExporting(true); setExportMsg('')
    try {
      await exportProject(selected, exportPath.trim())
      setExportMsg(`Copied to ${exportPath.trim()}`)
      setExportPath('')
    } catch (e) {
      setExportMsg(e.response?.data?.detail || 'Export failed')
    } finally { setExporting(false) }
  }

  const handleSave = async () => {
    if (!editName.trim()) { setEditError('Name is required'); return }
    setSaving(true); setEditError('')
    try {
      const r = await updateProject(selected, editName.trim(), editDesc.trim())
      const updated = r.data.data
      setProjects((prev) => prev.map((p) => p.id === selected ? updated : p))
      setEditing(false)
    } catch (e) {
      setEditError(e.response?.data?.detail || 'Save failed')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await deleteProject(selected)
      const remaining = projects.filter((p) => p.id !== selected)
      setProjects(remaining)
      setSelected(remaining.length > 0 ? remaining[0].id : null)
      setSessions([])
      setConfirmDelete(false)
    } catch (e) {
      setConfirmDelete(false)
    } finally { setDeleting(false) }
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
        {selected && !editing && (
          <>
            <button
              className="text-xs text-blue-400 hover:text-blue-300 px-1"
              onClick={() => { setEditing(true); setConfirmDelete(false) }}
            >
              Edit
            </button>
            <button
              className="text-xs text-red-500 hover:text-red-400 px-1"
              onClick={() => { setConfirmDelete(true); setEditing(false) }}
            >
              Delete
            </button>
          </>
        )}
      </div>

      {projects.length === 0 && (
        <p className="text-gray-600 text-sm">No projects yet.</p>
      )}

      {/* Edit form */}
      {editing && selectedProject && (
        <div className="mb-4 space-y-2 p-3 bg-gray-800/60 rounded-lg border border-gray-700">
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
            placeholder="Project name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
            placeholder="Description (optional)"
            value={editDesc}
            onChange={(e) => setEditDesc(e.target.value)}
          />
          {editError && <p className="text-red-400 text-xs">{editError}</p>}
          <div className="flex gap-2">
            <button
              className="bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-xs font-medium px-4 py-1.5 rounded"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              className="text-gray-400 hover:text-gray-200 text-xs px-2"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && selectedProject && (
        <div className="mb-4 p-3 bg-gray-800/60 rounded-lg border border-red-800 flex items-center gap-3">
          <span className="text-sm text-gray-300 flex-1">
            Delete <span className="font-medium text-white">{selectedProject.name}</span>? This cannot be undone.
          </span>
          <button
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
          <button
            className="text-gray-400 hover:text-gray-200 text-xs px-1"
            onClick={() => setConfirmDelete(false)}
          >
            Cancel
          </button>
        </div>
      )}

      {/* Export */}
      {selected && !editing && !confirmDelete && (
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
