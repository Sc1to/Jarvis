import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { GitCommit } from 'lucide-react'

interface Commit { hash: string; message: string; date: string; author_name: string }

export default function HistoryPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const [selected, setSelected] = useState<string | null>(null)

  const { data: log = [] } = useQuery<Commit[]>({
    queryKey: ['git-log', bookId],
    queryFn: () => fetch(`/api/books/${bookId}/git/log`).then(r => r.json()),
    refetchInterval: 15_000,
  })

  const { data: diff } = useQuery({
    queryKey: ['git-diff', bookId, selected],
    queryFn: () => fetch(`/api/books/${bookId}/git/diff/${selected}`).then(r => r.json()),
    enabled: !!selected,
  })

  return (
    <div className="flex h-full">
      <div className="w-80 border-r border-border flex flex-col">
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

      <div className="flex-1 overflow-y-auto p-6">
        {!selected ? (
          <div className="text-center py-20"><p className="text-sm text-muted-foreground">Select a commit to view the scene and bible changes.</p></div>
        ) : (
          <div className="space-y-6">
            <div>
              <h3 className="font-semibold text-sm mb-1">{log.find(c => c.hash === selected)?.message.split('\n')[0]}</h3>
              <Badge variant="outline" className="text-xs font-mono">{selected.slice(0, 7)}</Badge>
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
