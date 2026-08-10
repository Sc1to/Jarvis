import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Lock, Send, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'

interface Message { role: 'user' | 'assistant'; content: string }


export default function NorthStarPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: "Let's build your North Star — the anchor document that all agents will treat as a hard constraint.\n\nTell me about your novel. What's the core of it? Start wherever feels right: a character, an image, a feeling, a line you can't get out of your head.",
  }])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [locking, setLocking] = useState(false)
  const [locked, setLocked] = useState(false)
  const [northStarDoc, setNorthStarDoc] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Restore state on reload (if already locked)
  const { data: savedState } = useQuery({
    queryKey: ['north-star-state', bookId],
    queryFn: () => fetch(`/api/books/${bookId}/phase1/north-star`).then(r => r.json()) as Promise<{ locked: boolean; document: string | null }>,
  })
  useEffect(() => {
    if (savedState?.locked) {
      setLocked(true)
      setNorthStarDoc(savedState.document)
    }
  }, [savedState])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  async function sendMessage() {
    if (!input.trim() || locked || streaming) return
    const userMsg: Message = { role: 'user', content: input.trim() }
    const history = [...messages, userMsg]
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
    setStreaming(true)

    try {
      const resp = await fetch(`/api/books/${bookId}/phase1/north-star/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      })

      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: text }
            return next
          })
        } else if (event.type === 'error') {
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: `⚠ ${event.message}` }
            return next
          })
          break
        }
      }
    } catch {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: '⚠ Connection error — is the server running?' }
        return next
      })
    } finally {
      setStreaming(false)
    }
  }

  async function handleLock() {
    setLocking(true)
    try {
      const resp = await fetch(`/api/books/${bookId}/phase1/north-star/lock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
      })
      if (!resp.ok) {
        const { error } = await resp.json()
        throw new Error(error ?? 'Lock failed')
      }
      const { document } = await resp.json()
      setNorthStarDoc(document)
      setLocked(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Lock failed')
    } finally {
      setLocking(false)
    }
  }

  const userTurns = messages.filter(m => m.role === 'user').length
  const canLock = userTurns >= 2 && !streaming && !locking

  return (
    <div className="flex h-full">
      {/* Chat panel */}
      <div className="flex-1 flex flex-col border-r border-border">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="font-semibold">North Star</h2>
            <p className="text-xs text-muted-foreground">Phase 1A — create and lock the anchor document</p>
          </div>
          {!locked ? (
            <Button variant="outline" size="sm" onClick={handleLock} className="gap-2" disabled={!canLock}>
              {locking ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}
              {locking ? 'Synthesizing…' : 'Lock North Star'}
            </Button>
          ) : (
            <Badge variant="success">Locked</Badge>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.map((m, i) => (
            <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              <div className={cn(
                'max-w-[80%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap',
                m.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border border-border text-foreground',
              )}>
                {m.content || <span className="animate-pulse">▋</span>}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {!locked ? (
          <div className="px-6 py-4 border-t border-border">
            <div className="flex gap-2 items-end">
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Tell me about your novel…"
                rows={2}
                disabled={streaming}
                className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
              />
              <Button size="icon" onClick={sendMessage} disabled={!input.trim() || streaming}>
                {streaming ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Enter to send · Shift+Enter for new line</p>
          </div>
        ) : (
          <div className="px-6 py-4 border-t border-border bg-muted/30">
            <p className="text-xs text-muted-foreground">North Star is locked. New directives can be injected from the Bible Workshop.</p>
          </div>
        )}
      </div>

      {/* Document preview */}
      <div className="w-80 flex flex-col">
        <div className="px-5 py-4 border-b border-border">
          <h3 className="text-sm font-medium">north_star.md</h3>
          <p className="text-xs text-muted-foreground">{locked ? 'Append-only · read-only' : 'Preview'}</p>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {northStarDoc
            ? <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">{northStarDoc}</pre>
            : <p className="text-xs text-muted-foreground italic">Synthesized from the conversation on lock. Keep talking until the Story Architect has everything it needs.</p>
          }
        </div>
      </div>
    </div>
  )
}
