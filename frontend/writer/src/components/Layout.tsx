import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'
import { API } from '@/lib/api'
import { useQuery } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { Settings, Star, BookOpen, Eye, PenLine, History, ChevronLeft, Menu, X, ListOrdered } from 'lucide-react'

const bookNav = [
  { to: 'north-star', label: 'North Star', icon: Star },
  { to: 'bible-workshop', label: 'Bible Workshop', icon: BookOpen },
  { to: 'work', label: 'Work', icon: ListOrdered },
  { to: 'bible-viewer', label: 'Bible Viewer', icon: Eye },
  { to: 'writing-loop', label: 'Writing Loop', icon: PenLine },
  { to: 'history', label: 'History', icon: History },
]

function SidebarContent({ children, onClose }: { children: React.ReactNode; onClose?: () => void }) {
  return (
    <div className="flex flex-col h-full py-4 px-3 gap-1">
      {onClose && (
        <button onClick={onClose} className="self-end p-1 mb-1 text-muted-foreground hover:text-foreground md:hidden">
          <X size={16} />
        </button>
      )}
      {children}
    </div>
  )
}

function MobileOverlay({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null
  return (
    <>
      <div className="md:hidden fixed inset-0 z-20 bg-black/50" onClick={onClose} />
      <aside className="md:hidden fixed inset-y-0 left-0 z-30 w-56 bg-background border-r border-border overflow-y-auto">
        {children}
      </aside>
    </>
  )
}

// Used for the per-book layout
export function BookLayout() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const { data: book } = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}`).then(r => r.json()),
    enabled: !!bookId,
  })

  const navContent = (onClose?: () => void) => (
    <SidebarContent onClose={onClose}>
      <button
        onClick={() => { navigate('/books'); onClose?.() }}
        className="flex items-center gap-2 px-3 py-2 mb-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
      >
        <ChevronLeft size={13} />
        All books
      </button>
      <div className="px-3 mb-3">
        <p className="text-xs font-semibold truncate text-foreground">{book?.title ?? '…'}</p>
        <p className="text-xs text-muted-foreground font-mono">{bookId}</p>
      </div>
      {bookNav.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={`/books/${bookId}/${to}`}
          onClick={onClose}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
              isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            )
          }
        >
          <Icon size={16} />
          {label}
        </NavLink>
      ))}
      <div className="mt-auto">
        <NavLink
          to="/settings"
          onClick={onClose}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
              isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            )
          }
        >
          <Settings size={16} />
          Settings
        </NavLink>
      </div>
    </SidebarContent>
  )

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col w-56 shrink-0 border-r border-border overflow-y-auto">
        {navContent()}
      </aside>

      {/* Mobile overlay */}
      <MobileOverlay open={open} onClose={() => setOpen(false)}>
        {navContent(() => setOpen(false))}
      </MobileOverlay>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-border shrink-0">
          <button onClick={() => setOpen(true)} className="text-muted-foreground hover:text-foreground" aria-label="Open menu">
            <Menu size={20} />
          </button>
          <span className="text-sm font-medium truncate">{book?.title ?? '…'}</span>
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

// Used for global pages (Settings) — minimal chrome
export function GlobalLayout() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const navContent = (onClose?: () => void) => (
    <SidebarContent onClose={onClose}>
      <button
        onClick={() => { navigate('/books'); onClose?.() }}
        className="flex items-center gap-2 px-3 py-2 mb-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
      >
        <ChevronLeft size={13} />
        All books
      </button>
      <NavLink
        to="/settings"
        onClick={onClose}
        className={({ isActive }) =>
          cn(
            'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
            isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
          )
        }
      >
        <Settings size={16} />
        Settings
      </NavLink>
    </SidebarContent>
  )

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <aside className="hidden md:flex md:flex-col w-56 shrink-0 border-r border-border overflow-y-auto">
        {navContent()}
      </aside>

      <MobileOverlay open={open} onClose={() => setOpen(false)}>
        {navContent(() => setOpen(false))}
      </MobileOverlay>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-border shrink-0">
          <button onClick={() => setOpen(true)} className="text-muted-foreground hover:text-foreground" aria-label="Open menu">
            <Menu size={20} />
          </button>
          <span className="text-sm font-medium">Settings</span>
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
