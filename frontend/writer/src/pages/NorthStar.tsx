import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Lock, Send, Loader2, FileText, X, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'
import { API } from '@/lib/api'

interface Message { role: 'user' | 'assistant'; content: string }

type SidebarTab = 'northstar' | 'prefs'

export default function NorthStarPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const INITIAL_MESSAGE: Message = {
    role: 'assistant',
    content: "Let's build your North Star — the anchor document that all agents will treat as a hard constraint.\n\nTell me about your novel. What's the core of it? Start wherever feels right: a character, an image, a feeling, a line you can't get out of your head.",
  }
  const [messages, setMessages] = useState<Message[]>([INITIAL_MESSAGE])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [locking, setLocking] = useState(false)
  const [locked, setLocked] = useState(false)
  const [northStarDoc, setNorthStarDoc] = useState<string | null>(null)
  const [writingPrefs, setWritingPrefs] = useState<string | null>(null)
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('northstar')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Restore state on reload
  const { data: savedState } = useQuery({
    queryKey: ['north-star-state', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/north-star`).then(r => r.json()) as Promise<{ locked: boolean; document: string | null; writing_prefs: string | null; messages: Message[] | null }>,
  })
  useEffect(() => {
    if (!savedState) return
    if (savedState.locked) {
      setLocked(true)
      setNorthStarDoc(savedState.document)
      setWritingPrefs(savedState.writing_prefs)
    }
    if (savedState.messages?.length) setMessages(savedState.messages)
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
      const resp = await fetch(`${API}/books/${bookId}/phase1/north-star/reply`, {
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
      if (text) {
        const saved = [...history, { role: 'assistant' as const, content: text }]
        fetch(`${API}/books/${bookId}/phase1/north-star/messages`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: saved }),
        })
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
      const resp = await fetch(`${API}/books/${bookId}/phase1/north-star/lock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
      })
      if (!resp.ok) {
        const { error } = await resp.json()
        throw new Error(error ?? 'Lock failed')
      }
      const { document, writing_prefs } = await resp.json()
      setNorthStarDoc(document)
      setWritingPrefs(writing_prefs ?? null)
      setLocked(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Lock failed')
    } finally {
      setLocking(false)
    }
  }

  const userTurns = messages.filter(m => m.role === 'user').length
  const canLock = userTurns >= 2 && !streaming && !locking
  const [docOpen, setDocOpen] = useState(false)
  const [docCollapsed, setDocCollapsed] = useState(false)

  const sidebarContent = (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Tab bar — only show after locked (both docs exist) */}
      {locked && (
        <div className="flex border-b border-border shrink-0">
          {(['northstar', 'prefs'] as SidebarTab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setSidebarTab(tab)}
              className={cn(
                'flex-1 px-3 py-2 text-xs font-medium transition-colors',
                sidebarTab === tab
                  ? 'text-foreground border-b-2 border-primary -mb-px'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tab === 'northstar' ? 'North Star' : 'Writing Prefs'}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {sidebarTab === 'northstar' || !locked
          ? northStarDoc
            ? <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">{northStarDoc}</pre>
            : <p className="text-xs text-muted-foreground italic">Synthesized from the conversation on lock. Keep talking until the Story Architect has everything it needs.</p>
          : writingPrefs
            ? <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">{writingPrefs}</pre>
            : <p className="text-xs text-muted-foreground italic">Extracted from the conversation on lock.</p>
        }
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      {/* Chat panel */}
      <div className="flex-1 flex flex-col border-r border-border min-w-0">
        <div className="flex items-center justify-between px-4 md:px-6 py-4 border-b border-border gap-3">
          <div className="min-w-0">
            <h2 className="font-semibold">North Star</h2>
            <p className="text-xs text-muted-foreground">Phase 1A — create and lock the anchor document</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {/* Mobile doc preview toggle */}
            <button
              className="md:hidden flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setDocOpen(true)}
            >
              <FileText size={14} />
              <span className="text-xs">Doc</span>
            </button>
            {!locked ? (
              <Button variant="outline" size="sm" onClick={handleLock} className="gap-2" disabled={!canLock}>
                {locking ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}
                {locking ? 'Synthesizing…' : 'Lock North Star'}
              </Button>
            ) : (
              <Badge variant="success">Locked</Badge>
            )}
          </div>
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

      {/* Mobile doc preview overlay */}
      {docOpen && (
        <>
          <div
            className="md:hidden fixed inset-0 z-20 bg-black/50"
            onClick={() => setDocOpen(false)}
          />
          <aside className="md:hidden fixed inset-y-0 right-0 z-30 w-80 bg-background border-l border-border flex flex-col min-h-0">
            <div className="px-5 py-4 border-b border-border flex items-center justify-between shrink-0">
              <div>
                <h3 className="text-sm font-medium">{locked ? 'Documents' : 'Preview'}</h3>
                <p className="text-xs text-muted-foreground">{locked ? 'Read-only' : 'Synthesized on lock'}</p>
              </div>
              <button
                onClick={() => setDocOpen(false)}
                className="p-1 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X size={18} />
              </button>
            </div>
            {sidebarContent}
          </aside>
        </>
      )}

      {/* Desktop document preview sidebar */}
      <div className={cn(
        'hidden md:flex md:flex-col md:shrink-0 min-h-0 border-l border-border transition-all duration-200',
        docCollapsed ? 'md:w-8' : 'md:w-80',
      )}>
        {docCollapsed ? (
          <button
            onClick={() => setDocCollapsed(false)}
            className="flex-1 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Show document preview"
          >
            <ChevronLeft size={14} />
          </button>
        ) : (
          <>
            <div className="px-5 py-4 border-b border-border shrink-0 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <h3 className="text-sm font-medium">{locked ? 'Documents' : 'Preview'}</h3>
                <p className="text-xs text-muted-foreground">{locked ? 'Read-only' : 'Synthesized on lock'}</p>
              </div>
              <button
                onClick={() => setDocCollapsed(true)}
                className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded transition-colors"
                title="Hide preview"
              >
                <ChevronRight size={13} />
              </button>
            </div>
            {sidebarContent}
          </>
        )}
      </div>
    </div>
  )
}
