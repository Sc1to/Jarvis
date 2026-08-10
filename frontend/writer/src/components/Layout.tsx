import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { Settings, Star, BookOpen, Eye, PenLine, History, ChevronLeft } from 'lucide-react'

const bookNav = [
  { to: 'north-star', label: 'North Star', icon: Star },
  { to: 'bible-workshop', label: 'Bible Workshop', icon: BookOpen },
  { to: 'bible-viewer', label: 'Bible Viewer', icon: Eye },
  { to: 'writing-loop', label: 'Writing Loop', icon: PenLine },
  { to: 'history', label: 'History', icon: History },
]

// Used for the per-book layout
export function BookLayout() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()

  const { data: book } = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => fetch(`/api/books/${bookId}`).then(r => r.json()),
    enabled: !!bookId,
  })

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <aside className="w-56 shrink-0 border-r border-border flex flex-col py-4 px-3 gap-1">
        {/* Back to books */}
        <button
          onClick={() => navigate('/books')}
          className="flex items-center gap-2 px-3 py-2 mb-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
        >
          <ChevronLeft size={13} />
          All books
        </button>

        {/* Book title */}
        <div className="px-3 mb-3">
          <p className="text-xs font-semibold truncate text-foreground">{book?.title ?? '…'}</p>
          <p className="text-xs text-muted-foreground font-mono">{bookId}</p>
        </div>

        {/* Nav */}
        {bookNav.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={`/books/${bookId}/${to}`}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}

        {/* Settings at the bottom */}
        <div className="mt-auto">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              )
            }
          >
            <Settings size={16} />
            Settings
          </NavLink>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}

// Used for global pages (Settings) — minimal chrome
export function GlobalLayout() {
  const navigate = useNavigate()
  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <aside className="w-56 shrink-0 border-r border-border flex flex-col py-4 px-3 gap-1">
        <button
          onClick={() => navigate('/books')}
          className="flex items-center gap-2 px-3 py-2 mb-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
        >
          <ChevronLeft size={13} />
          All books
        </button>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
              isActive
                ? 'bg-accent text-accent-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            )
          }
        >
          <Settings size={16} />
          Settings
        </NavLink>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
