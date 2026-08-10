import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getHealth } from '../api.js'

const NAV = [
  { to: '/dashboard',  label: 'Dashboard' },
  { to: '/positions',  label: 'Positions' },
  { to: '/signals',    label: 'Signals' },
  { to: '/wsb',        label: 'WSB' },
  { to: '/catalysts',  label: 'Catalysts' },
  { to: '/audit',      label: 'Audit' },
  { to: '/settings',   label: 'Settings' },
]

// Validation is desktop-sidebar-only — mobile accesses it via Settings
const SIDEBAR_EXTRA = [
  { to: '/validation', label: 'Validation' },
]

function ModeBadge({ mode }) {
  if (!mode) return null
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded ${
      mode === 'live'
        ? 'bg-blue-900 text-blue-300'
        : 'bg-amber-900 text-amber-300'
    }`}>
      {mode.toUpperCase()}
    </span>
  )
}

export default function Layout() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    const fetch = () =>
      getHealth().then(r => setHealth(r.data)).catch(() => setHealth(null))
    fetch()
    const id = setInterval(fetch, 30000)
    return () => clearInterval(id)
  }, [])

  const ibkrOk = health?.dependencies?.ibkr_tws === 'ok'

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-48 bg-gray-900 border-r border-gray-800 flex-shrink-0">
        <div className="px-4 py-4 border-b border-gray-800">
          <div className="text-xs text-gray-400 mb-1">Trading Platform</div>
          <div className="flex items-center gap-2">
            <ModeBadge mode={health?.trading_mode} />
            <span className={`w-2 h-2 rounded-full ${ibkrOk ? 'bg-green-500' : 'bg-red-500'}`} title={ibkrOk ? 'TWS connected' : 'TWS disconnected'} />
          </div>
        </div>

        <nav className="flex-1 py-2">
          {[...NAV, ...SIDEBAR_EXTRA].map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-gray-800 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {health && (
          <div className="px-4 py-3 border-t border-gray-800 text-xs text-gray-500">
            up {Math.floor((health.uptime_seconds || 0) / 3600)}h
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 flex">
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex-1 py-3 text-center text-xs transition-colors ${
                isActive ? 'text-white bg-gray-800' : 'text-gray-400'
              }`
            }
          >
            {label.slice(0, 3)}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
