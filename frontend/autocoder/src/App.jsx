import { useState } from 'react'
import AgentBoard from './components/AgentBoard'
import SessionLog from './components/SessionLog'
import MorningReview from './components/MorningReview'
import ProjectHistory from './components/ProjectHistory'
import StartSession from './components/StartSession'

const NAV = [
  { id: 'board',   label: 'Agent Board' },
  { id: 'log',     label: 'Session Log' },
  { id: 'review',  label: 'Morning Review' },
  { id: 'history', label: 'Project History' },
  { id: 'start',   label: '+ New Session' },
]

export default function App() {
  const [view, setView] = useState('board')
  const [activeSession, setActiveSession] = useState(null)
  const [open, setOpen] = useState(false)

  const nav = (id) => { setView(id); setOpen(false) }

  const handleSessionStarted = (id) => {
    setActiveSession(id)
    setView('board')
  }

  const NavItems = () => (
    <nav className="flex flex-col gap-1 p-3">
      {NAV.map((n) => (
        <button
          key={n.id}
          onClick={() => nav(n.id)}
          className={`text-left px-3 py-2 rounded-lg text-sm transition-colors ${
            view === n.id
              ? 'bg-gray-700 text-white font-medium'
              : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
          }`}
        >
          {n.label}
        </button>
      ))}
    </nav>
  )

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col w-44 flex-shrink-0 bg-gray-900 border-r border-gray-800">
        <div className="px-4 py-4 border-b border-gray-800">
          <span className="text-sm font-semibold text-gray-300">Autocoder</span>
          {activeSession && (
            <span className="block text-xs text-blue-400 mt-0.5 truncate">
              {activeSession.slice(0, 8)}…
            </span>
          )}
        </div>
        <NavItems />
      </aside>

      {/* Mobile sidebar */}
      {open && (
        <aside className="md:hidden fixed inset-y-0 left-0 z-30 w-44 flex flex-col bg-gray-900 border-r border-gray-800">
          <div className="px-4 py-4 border-b border-gray-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-300">Autocoder</span>
            <button onClick={() => setOpen(false)} className="text-gray-500 text-lg">✕</button>
          </div>
          <NavItems />
        </aside>
      )}

      {/* Main */}
      <main className="flex-1 overflow-y-auto p-4 md:p-6">
        {/* Mobile header */}
        <div className="md:hidden flex items-center gap-3 mb-4">
          <button onClick={() => setOpen(true)} className="text-gray-400 text-xl p-1">☰</button>
          <span className="text-sm font-semibold text-gray-300">
            {NAV.find((n) => n.id === view)?.label}
          </span>
        </div>

        {view === 'board'   && <AgentBoard activeSessionId={activeSession} />}
        {view === 'log'     && <SessionLog />}
        {view === 'review'  && <MorningReview />}
        {view === 'history' && <ProjectHistory onViewReview={(id) => { setActiveSession(id); setView('review') }} />}
        {view === 'start'   && <StartSession onStarted={handleSessionStarted} />}
      </main>
    </div>
  )
}
