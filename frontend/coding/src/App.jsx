import { useEffect, useState } from 'react'
import { getProjects, createProject, deleteProject, getFileTree, getGitStatus, saveToken, getTokenStatus } from './api.js'
import FileTree from './components/FileTree.jsx'
import GitStatus from './components/GitStatus.jsx'
import Chat from './components/Chat.jsx'

// Mobile panel tabs
const PANELS = ['Files', 'Chat', 'Git']

export default function App() {
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [tree, setTree] = useState(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [gitStatus, setGitStatus] = useState(null)
  const [showAddProject, setShowAddProject] = useState(false)
  const [form, setForm] = useState({ name: '', local_path: '', github_repo: '' })
  const [tokenNeeded, setTokenNeeded] = useState(false)
  const [token, setToken] = useState('')
  const [mobilePanel, setMobilePanel] = useState('Chat')
  const [error, setError] = useState(null)

  async function loadProjects() {
    try {
      const r = await getProjects()
      setProjects(r.data)
    } catch (e) { setError(e.message) }
  }

  async function checkToken() {
    try {
      const r = await getTokenStatus()
      setTokenNeeded(!r.data.configured)
    } catch {}
  }

  useEffect(() => {
    loadProjects()
    checkToken()
  }, [])

  async function selectProject(p) {
    setActiveProject(p)
    setTree(null)
    setGitStatus(null)
    if (!p) return
    setTreeLoading(true)
    try {
      const [t, g] = await Promise.all([getFileTree(p.id), getGitStatus(p.id)])
      setTree(t.data)
      setGitStatus(g.data)
    } catch (e) { setError(e.message) }
    finally { setTreeLoading(false) }
  }

  async function refreshGit() {
    if (!activeProject) return
    try {
      const r = await getGitStatus(activeProject.id)
      setGitStatus(r.data)
    } catch {}
  }

  async function addProject(e) {
    e.preventDefault()
    setError(null)
    try {
      await createProject(form)
      setForm({ name: '', local_path: '', github_repo: '' })
      setShowAddProject(false)
      loadProjects()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
  }

  async function removeProject(id, ev) {
    ev.stopPropagation()
    if (!confirm('Remove project?')) return
    await deleteProject(id)
    if (activeProject?.id === id) setActiveProject(null)
    loadProjects()
  }

  async function submitToken(e) {
    e.preventDefault()
    await saveToken(token)
    setTokenNeeded(false)
    setToken('')
  }

  function onFileClick(path) {
    // Paste file path into chat context by switching to chat with a prompt
    setMobilePanel('Chat')
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-gray-100">
      {/* Top bar */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-700 bg-gray-900 flex-shrink-0">
        <span className="text-sm font-semibold text-gray-300 hidden sm:block">Coding</span>

        {/* Project selector */}
        <select
          className="flex-1 max-w-xs bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500"
          value={activeProject?.id ?? ''}
          onChange={e => {
            const p = projects.find(p => p.id === Number(e.target.value))
            selectProject(p ?? null)
          }}
        >
          <option value="">No project</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>

        <button
          onClick={() => setShowAddProject(o => !o)}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          + Add
        </button>

        {activeProject && (
          <button
            onClick={ev => removeProject(activeProject.id, ev)}
            className="text-xs text-red-400 hover:text-red-300"
          >
            Remove
          </button>
        )}

        {/* Mobile panel tabs */}
        <div className="ml-auto flex gap-1 md:hidden">
          {PANELS.map(p => (
            <button
              key={p}
              onClick={() => setMobilePanel(p)}
              className={`text-xs px-2 py-1 rounded ${mobilePanel === p ? 'bg-gray-700 text-white' : 'text-gray-400'}`}
            >
              {p}
            </button>
          ))}
        </div>
      </header>

      {/* Add project form */}
      {showAddProject && (
        <form onSubmit={addProject} className="flex flex-wrap gap-2 px-4 py-2 border-b border-gray-700 bg-gray-800">
          <input className={inp} placeholder="Name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} required />
          <input className={inp} placeholder="Local path (auto-created if blank)" value={form.local_path} onChange={e => setForm(f => ({...f, local_path: e.target.value}))} />
          <input className={inp} placeholder="GitHub repo (user/repo)" value={form.github_repo} onChange={e => setForm(f => ({...f, github_repo: e.target.value}))} />
          <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1.5 rounded">Add</button>
        </form>
      )}

      {/* GitHub token banner */}
      {tokenNeeded && (
        <form onSubmit={submitToken} className="flex gap-2 px-4 py-2 border-b border-gray-700 bg-yellow-900/30">
          <span className="text-xs text-yellow-400 self-center">GitHub token needed for push/PR:</span>
          <input
            type="password"
            className={`${inp} max-w-xs`}
            placeholder="ghp_…"
            value={token}
            onChange={e => setToken(e.target.value)}
          />
          <button type="submit" className="text-xs bg-yellow-700 hover:bg-yellow-600 text-white px-3 py-1.5 rounded">Save</button>
          <button type="button" onClick={() => setTokenNeeded(false)} className="text-xs text-gray-400 hover:text-white">Skip</button>
        </form>
      )}

      {error && <p className="px-4 py-1 text-xs text-red-400 border-b border-gray-700">{error}</p>}

      {/* Main 3-panel layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: File tree */}
        <aside className={`w-52 flex-shrink-0 flex flex-col border-r border-gray-700 bg-gray-900 ${mobilePanel === 'Files' ? 'flex' : 'hidden'} md:flex`}>
          <div className="px-3 py-2 text-xs text-gray-500 border-b border-gray-700 font-medium">
            {activeProject ? activeProject.name : 'Files'}
          </div>
          <FileTree tree={tree} onFileClick={onFileClick} loading={treeLoading} />
        </aside>

        {/* Center: Chat */}
        <main className={`flex-1 flex flex-col min-w-0 ${mobilePanel === 'Chat' ? 'flex' : 'hidden'} md:flex`}>
          <Chat projectId={activeProject?.id ?? null} />
        </main>

        {/* Right: Git status */}
        <aside className={`w-56 flex-shrink-0 flex flex-col border-l border-gray-700 bg-gray-900 ${mobilePanel === 'Git' ? 'flex' : 'hidden'} md:flex`}>
          <div className="px-3 py-2 text-xs text-gray-500 border-b border-gray-700 font-medium">Git</div>
          <div className="flex-1 overflow-y-auto p-3">
            <GitStatus
              projectId={activeProject?.id}
              status={gitStatus}
              onRefresh={refreshGit}
            />
          </div>
        </aside>
      </div>
    </div>
  )
}

const inp = 'bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500'
