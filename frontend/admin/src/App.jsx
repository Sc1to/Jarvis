import { useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './views/Dashboard.jsx'
import Apps from './views/Apps.jsx'
import AppDetail from './views/AppDetail.jsx'
import Models from './views/Models.jsx'
import Agents from './views/Agents.jsx'
import Network from './views/Network.jsx'
import Updates from './views/Updates.jsx'
import Prompts from './views/Prompts.jsx'
import Settings from './views/Settings.jsx'

const VIEWS = { dashboard: Dashboard, apps: Apps, models: Models, agents: Agents, network: Network, updates: Updates, prompts: Prompts, settings: Settings }

export default function App() {
  const [view, setView] = useState('dashboard')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [selectedApp, setSelectedApp] = useState(null)

  function navigate(v) { setView(v); setSelectedApp(null) }

  const showDetail = view === 'apps' && selectedApp !== null
  const View = VIEWS[view]

  return (
    <div className="flex h-full bg-gray-900 text-gray-100">
      <Sidebar view={view} setView={navigate} open={sidebarOpen} setOpen={setSidebarOpen} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-gray-700 bg-gray-900">
          <button onClick={() => setSidebarOpen(true)} className="text-gray-400 hover:text-white" aria-label="Open menu">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <span className="text-sm font-medium capitalize">{showDetail ? selectedApp.name : view}</span>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          {showDetail
            ? <AppDetail app={selectedApp} onBack={() => setSelectedApp(null)} />
            : <View setSelectedApp={setSelectedApp} />
          }
        </main>
      </div>
    </div>
  )
}
