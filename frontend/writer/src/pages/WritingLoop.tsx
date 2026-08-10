import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Play, CheckCircle, XCircle, Edit3, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers, drawSelection, keymap } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'

type LoopStatus = 'idle' | 'writing' | 'qa' | 'qa-pass' | 'qa-fail' | 'editing'

function ProseEditor({ initialValue, onChange }: { initialValue: string; onChange: (v: string) => void }) {
  const editorRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)

  useEffect(() => {
    if (!editorRef.current) return
    const state = EditorState.create({
      doc: initialValue,
      extensions: [
        lineNumbers(),
        history(),
        drawSelection(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        EditorView.lineWrapping,
        EditorView.updateListener.of(update => {
          if (update.docChanged) onChange(update.state.doc.toString())
        }),
        EditorView.theme({
          '&': { height: '100%', fontSize: '1.05rem', fontFamily: '"Lora", Georgia, serif' },
          '.cm-scroller': { overflow: 'auto', lineHeight: '1.85' },
          '.cm-content': { padding: '1.5rem' },
          '&.cm-focused': { outline: 'none' },
        }),
      ],
    })
    viewRef.current = new EditorView({ state, parent: editorRef.current })
    return () => viewRef.current?.destroy()
  }, [])

  return <div ref={editorRef} className="h-full border border-border rounded-lg overflow-hidden" />
}

export default function WritingLoopPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const [autoMode, setAutoMode] = useState(false)
  const [status, setStatus] = useState<LoopStatus>('idle')
  const [qaAttempt, setQaAttempt] = useState(0)
  const [sceneText, setSceneText] = useState('')
  const [editedText, setEditedText] = useState('')
  const [qaNote, setQaNote] = useState('')
  const [rejectNote, setRejectNote] = useState('')

  // Mock scene data — will come from /api/phase3
  const scene = {
    number: '003',
    brief: 'The party arrives at Constantinople after a storm-delayed crossing. Hamid discovers the city has changed more than expected — the fire is now known, and he is recognised.',
    entryState: 'Party aboard ship, approaching Constantinople (LOC_004). Hamid (CHAR_012) unknown in the city. Fire of 1203 has occurred.',
    exitState: 'Party ashore in Constantinople. Hamid recognised by a harbour merchant. Fire aftermath visible throughout the waterfront.',
  }

  function runScene() {
    setStatus('writing')
    setQaAttempt(0)
    setSceneText('')
    // TODO: SSE stream from /api/phase3/run-scene
    setTimeout(() => {
      setSceneText('The galley slid into the Golden Horn on the third morning after the storm, its single sail carrying the smell of salt and smoke. Constantinople rose before them — or what remained of it.\n\nHamid stood at the bow and said nothing. He had been here before, years ago, when the sea walls still gleamed white. Now the waterfront was patched with timber where stone had fallen, and the smell of old ash had worked itself into the very wind off the water.\n\n"It burned," said Brother Tomás, appearing at his elbow with his customary precision for stating the obvious.\n\n"It burned," Hamid agreed.\n\nThey were barely at the dock when a merchant loading bales of wool turned, looked, and looked again.')
      setStatus('qa')
      setTimeout(() => {
        setQaAttempt(1)
        setQaNote('Exit state verified: party ashore ✓, Hamid recognised ✓, fire aftermath established ✓. Foreshadowing SEED_003 planted. Voice consistent with narrative_voice.md.')
        setStatus('qa-pass')
      }, 1200)
    }, 2000)
  }

  function approve() {
    setStatus('idle')
    setQaAttempt(0)
    // TODO: POST /api/books/:bookId/phase3/approve
  }

  function reject() {
    setStatus('idle')
    // TODO: POST /api/books/:bookId/phase3/reject { notes: rejectNote }
  }

  function startEdit() {
    setEditedText(sceneText)
    setStatus('editing')
  }

  function submitEdit() {
    setSceneText(editedText)
    setStatus('qa-pass')
    // TODO: POST /api/phase3/edit { scene: editedText }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-border">
        <div>
          <h2 className="font-semibold text-sm">Writing Loop</h2>
          <p className="text-xs text-muted-foreground">Phase 3 · Scene {scene.number}</p>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-2">
          <Switch id="auto" checked={autoMode} onCheckedChange={setAutoMode} />
          <Label htmlFor="auto" className="text-sm cursor-pointer">Automatic mode</Label>
        </div>
        {status === 'idle' && (
          <Button size="sm" onClick={runScene} className="gap-2">
            <Play size={13} />
            Write scene
          </Button>
        )}
      </div>

      {/* Scene state strip */}
      <div className="flex items-stretch border-b border-border text-xs">
        <div className="flex-1 px-4 py-2 border-r border-border">
          <span className="text-muted-foreground font-medium uppercase tracking-wider">Entry</span>
          <p className="mt-0.5 text-foreground/80">{scene.entryState}</p>
        </div>
        <div className="px-3 flex items-center text-muted-foreground">
          <ChevronRight size={14} />
        </div>
        <div className="flex-1 px-4 py-2">
          <span className="text-muted-foreground font-medium uppercase tracking-wider">Exit (contract)</span>
          <p className="mt-0.5 text-foreground/80">{scene.exitState}</p>
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 min-h-0">
        {/* Prose panel */}
        <div className="flex-1 overflow-y-auto p-6">
          {status === 'idle' && (
            <div className="text-center py-20">
              <p className="text-sm text-muted-foreground">Ready to write scene {scene.number}.</p>
              <p className="text-xs text-muted-foreground mt-1">{scene.brief}</p>
            </div>
          )}
          {status === 'writing' && (
            <p className="text-sm text-muted-foreground italic animate-pulse">Writer agent generating scene prose…</p>
          )}
          {(status === 'qa' || status === 'qa-pass' || status === 'qa-fail') && (
            <div className="prose-display text-foreground leading-relaxed whitespace-pre-wrap">
              {sceneText}
            </div>
          )}
          {status === 'editing' && (
            <div className="h-full min-h-[400px]">
              <ProseEditor initialValue={editedText} onChange={setEditedText} />
            </div>
          )}
        </div>

        {/* QA sidebar */}
        <div className="w-72 border-l border-border flex flex-col">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-medium">QA Status</h3>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {status === 'qa' && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                QA agent checking…
              </div>
            )}
            {status === 'qa-pass' && (
              <>
                <div className="flex items-center gap-2">
                  <CheckCircle size={14} className="text-emerald-500" />
                  <span className="text-sm font-medium text-emerald-500">Pass</span>
                  <Badge variant="outline" className="text-xs ml-auto">Attempt {qaAttempt}/3</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{qaNote}</p>
              </>
            )}
            {status === 'qa-fail' && (
              <>
                <div className="flex items-center gap-2">
                  <XCircle size={14} className="text-red-500" />
                  <span className="text-sm font-medium text-red-500">Fail</span>
                  <Badge variant="outline" className="text-xs ml-auto">Attempt {qaAttempt}/3</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{qaNote}</p>
              </>
            )}

            {status === 'qa-pass' && !autoMode && (
              <>
                <Separator />
                <div className="space-y-2">
                  <Button className="w-full" size="sm" onClick={approve}>
                    Approve scene
                  </Button>
                  <textarea
                    value={rejectNote}
                    onChange={e => setRejectNote(e.target.value)}
                    placeholder="Rejection notes…"
                    rows={2}
                    className="w-full resize-none rounded-md border border-input bg-transparent px-2 py-1.5 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" className="flex-1" onClick={reject} disabled={!rejectNote.trim()}>
                      Reject
                    </Button>
                    <Button variant="ghost" size="sm" className="flex-1 gap-1" onClick={startEdit}>
                      <Edit3 size={12} />
                      Edit
                    </Button>
                  </div>
                </div>
              </>
            )}

            {status === 'editing' && (
              <>
                <Separator />
                <p className="text-xs text-muted-foreground">Editing directly. The Bible Updater will still run on your approved version.</p>
                <Button className="w-full" size="sm" onClick={submitEdit}>
                  Approve edited scene
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
