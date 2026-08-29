import { useState } from 'react'
import { API } from '@/lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BookOpen, Plus, Trash2, ArrowRight, Loader2, Library, ChevronDown, ChevronRight, ScrollText } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Book { id: string; title: string; created_at: number; series_id?: string | null; series_order?: number | null }
interface Series { id: string; title: string; created_at: number }

async function fetchBooks(): Promise<Book[]> {
  const r = await fetch(`${API}/books`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function fetchSeries(): Promise<Series[]> {
  const r = await fetch(`${API}/series`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function createBook(payload: { title: string; series_id?: string; series_order?: number }): Promise<Book> {
  const r = await fetch(`${API}/books`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error('Failed to create book')
  return r.json()
}

async function deleteBook(id: string) {
  await fetch(`${API}/books/${id}`, { method: 'DELETE' })
}

async function createSeries(title: string): Promise<Series> {
  const r = await fetch(`${API}/series`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!r.ok) throw new Error('Failed to create series')
  return r.json()
}

async function deleteSeries(id: string) {
  await fetch(`${API}/series/${id}`, { method: 'DELETE' })
}

function BookCard({ book, onDelete, onNavigate }: {
  book: Book
  onDelete: (id: string) => void
  onNavigate: (id: string) => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  return (
    <Card
      className="group cursor-pointer hover:bg-accent/30 transition-colors"
      onClick={() => !confirmDelete && onNavigate(book.id)}
    >
      <CardHeader className="py-3 px-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <CardTitle className="text-sm truncate">{book.title}</CardTitle>
            <CardDescription className="text-xs mt-0.5">
              {new Date(book.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
              <span className="mx-1.5 opacity-40">·</span>
              <span className="font-mono opacity-60">{book.id}</span>
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {confirmDelete ? (
              <>
                <span className="text-xs text-muted-foreground">Delete?</span>
                <Button size="sm" variant="destructive" onClick={e => { e.stopPropagation(); onDelete(book.id) }}>Yes</Button>
                <Button size="sm" variant="ghost" onClick={e => { e.stopPropagation(); setConfirmDelete(false) }}>No</Button>
              </>
            ) : (
              <>
                <Button
                  size="icon" variant="ghost"
                  className="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7"
                  onClick={e => { e.stopPropagation(); setConfirmDelete(true) }}
                >
                  <Trash2 size={13} />
                </Button>
                <ArrowRight size={15} className="text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
              </>
            )}
          </div>
        </div>
      </CardHeader>
    </Card>
  )
}

function SeriesSection({ series, books, onDeleteSeries, onDeleteBook, onNavigate, onAddBook }: {
  series: Series
  books: Book[]
  onDeleteSeries: (id: string) => void
  onDeleteBook: (id: string) => void
  onNavigate: (id: string) => void
  onAddBook: (seriesId: string) => void
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(true)
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div
        className="flex items-center gap-2 px-4 py-3 bg-accent/20 cursor-pointer hover:bg-accent/30 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded
          ? <ChevronDown size={14} className="text-muted-foreground shrink-0" />
          : <ChevronRight size={14} className="text-muted-foreground shrink-0" />}
        <Library size={14} className="text-muted-foreground shrink-0" />
        <span className="text-sm font-medium flex-1 truncate">{series.title}</span>
        <span className="text-xs text-muted-foreground">{books.length} book{books.length !== 1 ? 's' : ''}</span>
        <Button
          size="sm" variant="ghost"
          className="h-7 text-xs gap-1.5 ml-2"
          onClick={e => { e.stopPropagation(); navigate(`/series/${series.id}/bible`) }}
        >
          <ScrollText size={12} />Bible
        </Button>
        {confirmDelete ? (
          <>
            <span className="text-xs text-muted-foreground ml-1">Remove series?</span>
            <Button size="sm" variant="destructive" onClick={e => { e.stopPropagation(); onDeleteSeries(series.id) }}>Yes</Button>
            <Button size="sm" variant="ghost" onClick={e => { e.stopPropagation(); setConfirmDelete(false) }}>No</Button>
          </>
        ) : (
          <Button
            size="icon" variant="ghost"
            className="h-7 w-7 opacity-60 hover:opacity-100"
            onClick={e => { e.stopPropagation(); setConfirmDelete(true) }}
          >
            <Trash2 size={12} />
          </Button>
        )}
      </div>
      {expanded && (
        <div className="px-3 py-2 space-y-1.5">
          {books.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2 text-center">No books in this series yet.</p>
          ) : (
            books.map(book => (
              <BookCard key={book.id} book={book} onDelete={onDeleteBook} onNavigate={onNavigate} />
            ))
          )}
          <Button
            variant="ghost" size="sm"
            className="w-full gap-1.5 text-xs text-muted-foreground mt-1"
            onClick={() => onAddBook(series.id)}
          >
            <Plus size={12} />Add book to series
          </Button>
        </div>
      )}
    </div>
  )
}

export default function BooksPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [newTitle, setNewTitle] = useState('')
  const [newSeriesTitle, setNewSeriesTitle] = useState('')
  const [showNewSeries, setShowNewSeries] = useState(false)
  const [selectedSeriesId, setSelectedSeriesId] = useState<string>('')

  const { data: books = [], isLoading: booksLoading } = useQuery({ queryKey: ['books'], queryFn: fetchBooks })
  const { data: seriesList = [], isLoading: seriesLoading } = useQuery({ queryKey: ['series'], queryFn: fetchSeries })

  const createMutation = useMutation({
    mutationFn: createBook,
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      setNewTitle('')
      setSelectedSeriesId('')
      navigate(`/books/${book.id}/north-star`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteBook,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  })

  const createSeriesMutation = useMutation({
    mutationFn: createSeries,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['series'] })
      setNewSeriesTitle('')
      setShowNewSeries(false)
    },
  })

  const deleteSeriesMutation = useMutation({
    mutationFn: deleteSeries,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['series'] })
      qc.invalidateQueries({ queryKey: ['books'] })
    },
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newTitle.trim()) return
    const payload: { title: string; series_id?: string; series_order?: number } = { title: newTitle.trim() }
    if (selectedSeriesId) {
      payload.series_id = selectedSeriesId
      payload.series_order = books.filter(b => b.series_id === selectedSeriesId).length + 1
    }
    createMutation.mutate(payload)
  }

  function handleAddBookToSeries(seriesId: string) {
    setSelectedSeriesId(seriesId)
    document.getElementById('new-book-form')?.scrollIntoView({ behavior: 'smooth' })
  }

  const isLoading = booksLoading || seriesLoading
  const standaloneBooks = books.filter(b => !b.series_id)
  const booksBySeries = (sid: string) =>
    books.filter(b => b.series_id === sid).sort((a, b) => (a.series_order ?? 999) - (b.series_order ?? 999))

  return (
    <div className="min-h-screen flex flex-col items-center justify-start pt-16 px-6 pb-16">
      <div className="w-full max-w-xl space-y-8">
        {/* Header */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Novellist</h1>
          <p className="text-sm text-muted-foreground">Your books & series</p>
        </div>

        {/* Series section */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Series</h2>
            <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => setShowNewSeries(v => !v)}>
              <Plus size={12} />New series
            </Button>
          </div>

          {showNewSeries && (
            <form
              onSubmit={e => { e.preventDefault(); if (newSeriesTitle.trim()) createSeriesMutation.mutate(newSeriesTitle.trim()) }}
              className="flex gap-2"
            >
              <Input
                value={newSeriesTitle}
                onChange={e => setNewSeriesTitle(e.target.value)}
                placeholder="Series title…"
                className="flex-1 h-8 text-sm"
                autoFocus
              />
              <Button type="submit" size="sm" disabled={!newSeriesTitle.trim() || createSeriesMutation.isPending} className="gap-1.5 h-8">
                {createSeriesMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                Create
              </Button>
              <Button type="button" size="sm" variant="ghost" className="h-8" onClick={() => setShowNewSeries(false)}>Cancel</Button>
            </form>
          )}

          {isLoading ? (
            <div className="flex justify-center py-6"><Loader2 size={18} className="animate-spin text-muted-foreground" /></div>
          ) : seriesList.length === 0 ? (
            <div className="text-center py-6 space-y-1 border border-dashed border-border rounded-lg">
              <Library size={24} className="mx-auto text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground">No series yet. Create one to share characters across books.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {seriesList.map(s => (
                <SeriesSection
                  key={s.id}
                  series={s}
                  books={booksBySeries(s.id)}
                  onDeleteSeries={deleteSeriesMutation.mutate}
                  onDeleteBook={deleteMutation.mutate}
                  onNavigate={id => navigate(`/books/${id}/north-star`)}
                  onAddBook={handleAddBookToSeries}
                />
              ))}
            </div>
          )}
        </div>

        {/* Standalone books */}
        {!isLoading && standaloneBooks.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Standalone Books</h2>
            <div className="space-y-2">
              {standaloneBooks.map(book => (
                <BookCard
                  key={book.id}
                  book={book}
                  onDelete={deleteMutation.mutate}
                  onNavigate={id => navigate(`/books/${id}/north-star`)}
                />
              ))}
            </div>
          </div>
        )}

        {/* New book form */}
        <div id="new-book-form" className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">New book</h2>
          <form onSubmit={handleCreate} className="space-y-2">
            <div className="flex gap-2">
              <Input
                value={newTitle}
                onChange={e => setNewTitle(e.target.value)}
                placeholder="Book title…"
                className="flex-1"
              />
              <Button type="submit" disabled={!newTitle.trim() || createMutation.isPending} className="gap-2 shrink-0">
                {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                Create
              </Button>
            </div>
            {seriesList.length > 0 && (
              <select
                value={selectedSeriesId}
                onChange={e => setSelectedSeriesId(e.target.value)}
                className={cn(
                  'w-full h-9 rounded-md border border-input bg-background px-3 text-sm',
                  !selectedSeriesId ? 'text-muted-foreground' : 'text-foreground',
                  'focus:outline-none focus:ring-1 focus:ring-ring',
                )}
              >
                <option value="">No series (standalone)</option>
                {seriesList.map(s => (
                  <option key={s.id} value={s.id}>{s.title}</option>
                ))}
              </select>
            )}
            {selectedSeriesId && (
              <p className="text-xs text-muted-foreground">
                This book will inherit existing series characters and entities.
              </p>
            )}
          </form>
        </div>

        {/* Settings link */}
        <div className="text-center pt-4 border-t border-border">
          <button
            onClick={() => navigate('/settings')}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Settings — API keys, model configuration
          </button>
        </div>
      </div>
    </div>
  )
}
