const NAV = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'apps',      label: 'Apps' },
  { id: 'models',    label: 'Models' },
  { id: 'agents',    label: 'Agents' },
  { id: 'prompts',   label: 'Prompts' },
  { id: 'network',   label: 'Network' },
  { id: 'updates',   label: 'Updates' },
  { id: 'settings',  label: 'Settings' },
]

function NavItems({ view, onNav }) {
  return (
    <nav className="flex-1 overflow-y-auto py-2">
      {NAV.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onNav(id)}
          className={[
            'w-full text-left px-4 py-2.5 text-sm transition-colors',
            view === id
              ? 'bg-gray-700 text-white font-medium'
              : 'text-gray-400 hover:text-white hover:bg-gray-800',
          ].join(' ')}
        >
          {label}
        </button>
      ))}
    </nav>
  )
}

export default function Sidebar({ view, setView, open, setOpen }) {
  function nav(id) {
    setView(id)
    setOpen(false)
  }

  return (
    <>
      {/* Desktop sidebar — always in flow */}
      <aside className="hidden md:flex md:flex-col w-48 flex-shrink-0 bg-gray-900 border-r border-gray-700">
        <div className="px-4 py-5 border-b border-gray-700">
          <span className="text-white font-semibold tracking-wide text-sm">PLATFORM</span>
        </div>
        <NavItems view={view} onNav={nav} />
      </aside>

      {/* Mobile overlay sidebar */}
      {open && (
        <>
          <div
            className="md:hidden fixed inset-0 z-20 bg-black/60"
            onClick={() => setOpen(false)}
          />
          <aside className="md:hidden fixed inset-y-0 left-0 z-30 w-48 flex flex-col bg-gray-900 border-r border-gray-700">
            <div className="px-4 py-5 border-b border-gray-700">
              <span className="text-white font-semibold tracking-wide text-sm">PLATFORM</span>
            </div>
            <NavItems view={view} onNav={nav} />
          </aside>
        </>
      )}
    </>
  )
}
