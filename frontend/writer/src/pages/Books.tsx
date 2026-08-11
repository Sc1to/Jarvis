import { useState } from 'react'
import { API } from '@/lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BookOpen, Plus, Trash2, ArrowRight, Loader2 } from 'lucide-react'

interface Book { id: string; title: string; created_at: number }

async function fetchBooks(): Promise<Book[]> {
  const r = await fetch(`${API}/books`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function createBook(title: string): Promise<Book> {
  const r = await fetch(`${API}/books`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!r.ok) throw new Error('Failed to create book')
  return r.json()
}

async function deleteBook(id: string) {
  await fetch(`${API}/books/${id}`, { method: 'DELETE' })
}

export default function BooksPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [newTitle, setNewTitle] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const { data: books = [], isLoading } = useQuery({ queryKey: ['books'], queryFn: fetchBooks })

  const createMutation = useMutation({
    mutationFn: createBook,
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      setNewTitle('')
      navigate(`/books/${book.id}/north-star`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteBook,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['books'] })
      setConfirmDelete(null)
    },
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newTitle.trim()) return
    createMutation.mutate(newTitle.trim())
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-start pt-20 px-6">
      <div className="w-full max-w-xl space-y-8">
        {/* Header */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Novellist</h1>
          <p className="text-sm text-muted-foreground">Your books</p>
        </div>

        {/* Create form */}
        <form onSubmit={handleCreate} className="flex gap-2">
          <Input
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="New book title…"
            className="flex-1"
          />
          <Button type="submit" disabled={!newTitle.trim() || createMutation.isPending} className="gap-2 shrink-0">
            {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            New book
          </Button>
        </form>

        {/* Book list */}
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 size={20} className="animate-spin text-muted-foreground" />
          </div>
        ) : books.length === 0 ? (
          <div className="text-center py-12 space-y-2">
            <BookOpen size={32} className="mx-auto text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No books yet. Create your first one above.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {books.map(book => (
              <Card
                key={book.id}
                className="group cursor-pointer hover:bg-accent/30 transition-colors"
                onClick={() => confirmDelete !== book.id && navigate(`/books/${book.id}/north-star`)}
              >
                <CardHeader className="py-4 px-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-base truncate">{book.title}</CardTitle>
                      <CardDescription className="text-xs mt-0.5">
                        {new Date(book.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
                        <span className="mx-1.5 opacity-40">·</span>
                        <span className="font-mono opacity-60">{book.id}</span>
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {confirmDelete === book.id ? (
                        <>
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={e => { e.stopPropagation(); deleteMutation.mutate(book.id) }}
                            disabled={deleteMutation.isPending}
                          >
                            Yes
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={e => { e.stopPropagation(); setConfirmDelete(null) }}
                          >
                            No
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7"
                            onClick={e => { e.stopPropagation(); setConfirmDelete(book.id) }}
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
            ))}
          </div>
        )}

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
