import { useState } from 'react'
import { API } from '@/lib/api'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { ChevronLeft, GitCommit, RotateCcw } from 'lucide-react'

interface Commit { hash: string; message: string; date: string; author_name: string }

export default function HistoryPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [restoreSuccess, setRestoreSuccess] = useState(false)

  const restore = useMutation({
    mutationFn: (sha: string) =>
      fetch(`${API}/books/${bookId}/git/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sha }),
      }).then(r => r.json()),
    onSuccess: () => {
      setRestoreSuccess(true)
      qc.invalidateQueries()
    },
  })

  const { data: log = [] } = useQuery<Commit[]>({
    queryKey: ['git-log', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/git/log`).then(r => r.json()),
    refetchInterval: 15_000,
  })

  const { data: diff } = useQuery({
    queryKey: ['git-diff', bookId, selected],
    queryFn: () => fetch(`${API}/books/${bookId}/git/diff/${selected}`).then(r => r.json()),
    enabled: !!selected,
  })

  return (
    <div className="flex h-full">
      {/* Commit list: full-width on mobile (master), fixed sidebar on desktop */}
      <div className={cn('flex flex-col border-r border-border shrink-0 md:w-80', selected ? 'hidden md:flex' : 'w-full')}>
        <div className="px-4 py-4 border-b border-border">
          <h2 className="font-semibold text-sm">History</h2>
          <p className="text-xs text-muted-foreground">{log.length} commits</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {log.length === 0
            ? <p className="text-xs text-muted-foreground px-4 py-6 italic">No commits yet — complete a scene to see history.</p>
            : log.map(commit => (
              <button key={commit.hash} onClick={() => setSelected(commit.hash)} className={cn('w-full text-left px-4 py-3 border-b border-border transition-colors hover:bg-accent/30', selected === commit.hash && 'bg-accent/50')}>
                <div className="flex items-start gap-2">
                  <GitCommit size={13} className="text-muted-foreground mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{commit.message.split('\n')[0]}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{new Date(commit.date).toLocaleDateString()} · {commit.hash.slice(0, 7)}</p>
                  </div>
                </div>
              </button>
            ))
          }
        </div>
      </div>

      {/* Detail: hidden on mobile until a commit is selected */}
      <div className={cn('overflow-y-auto p-6', selected ? 'flex-1' : 'hidden md:block md:flex-1')}>
        {selected && (
          <button
            onClick={() => setSelected(null)}
            className="md:hidden flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-4"
          >
            <ChevronLeft size={13} />Back to commits
          </button>
        )}
        {!selected ? (
          <div className="text-center py-20"><p className="text-sm text-muted-foreground">Select a commit to view the scene and bible changes.</p></div>
        ) : (
          <div className="space-y-6">
            <div className="space-y-3">
              <div>
                <h3 className="font-semibold text-sm mb-1">{log.find(c => c.hash === selected)?.message.split('\n')[0]}</h3>
                <Badge variant="outline" className="text-xs font-mono">{selected.slice(0, 7)}</Badge>
              </div>
              <div className="space-y-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 border-amber-400/60 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/20"
                  onClick={() => { setRestoreSuccess(false); restore.mutate(selected) }}
                  disabled={restore.isPending}
                >
                  <RotateCcw size={13} />
                  {restore.isPending ? 'Restoring…' : 'Restore book to here'}
                </Button>
                <p className="text-[10px] text-muted-foreground">Resets all approvals after this commit. Files are overwritten when re-run.</p>
                {restoreSuccess && (
                  <p className="text-xs text-emerald-500">✓ Restored. Go to Bible Workshop or Writing Loop to continue from here.</p>
                )}
                {restore.isError && (
                  <p className="text-xs text-destructive">⚠ Restore failed — try again.</p>
                )}
              </div>
            </div>
            {diff
              ? <Card><CardContent className="p-4"><p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Bible changes</p><pre className="text-xs font-mono whitespace-pre-wrap text-muted-foreground">{JSON.stringify(diff, null, 2)}</pre></CardContent></Card>
              : <p className="text-xs text-muted-foreground italic">No diff data for this commit.</p>
            }
          </div>
        )}
      </div>
    </div>
  )
}
