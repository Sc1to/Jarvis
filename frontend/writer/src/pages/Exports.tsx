import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { API } from '@/lib/api'
import { Download, Plus, Trash2, Save, Loader2, FileText } from 'lucide-react'

interface ExportSummary {
  export_id: string
  label: string
  created_at: string
  updated_at: string
  chapter_count: number
  word_count: number
}

interface ExportChapter {
  chapter: number
  title: string
  content: string
  word_count: number
}

interface ExportData {
  export_id: string
  label: string
  created_at: string
  updated_at: string
  chapter_count: number
  word_count: number
  chapters: ExportChapter[]
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function ExportsPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const qc = useQueryClient()

  const { data: listData, refetch: refetchList } = useQuery<{ exports: ExportSummary[] }>({
    queryKey: ['exports', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/exports`).then(r => r.json()),
  })

  const [activeId, setActiveId] = useState<string | null>(null)
  const [exportData, setExportData] = useState<ExportData | null>(null)
  const [selectedChapter, setSelectedChapter] = useState(0)

  // Editable state
  const [editedLabel, setEditedLabel] = useState('')
  const [editedChapters, setEditedChapters] = useState<ExportChapter[]>([])
  const [dirty, setDirty] = useState(false)

  // Loading states
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [loadingExport, setLoadingExport] = useState(false)

  const exports = listData?.exports ?? []

  // Load full export when selection changes
  useEffect(() => {
    if (!activeId || !bookId) return
    setLoadingExport(true)
    setDirty(false)
    fetch(`${API}/books/${bookId}/exports/${activeId}`)
      .then(r => r.json())
      .then(data => {
        if (data.export) {
          setExportData(data.export)
          setEditedLabel(data.export.label)
          setEditedChapters(data.export.chapters)
          setSelectedChapter(0)
        }
      })
      .finally(() => setLoadingExport(false))
  }, [activeId, bookId])

  // Auto-select first export on load
  useEffect(() => {
    if (exports.length > 0 && !activeId) {
      setActiveId(exports[0].export_id)
    }
  }, [exports])

  async function createExport() {
    setCreating(true)
    try {
      const data = await fetch(`${API}/books/${bookId}/exports`, { method: 'POST' }).then(r => r.json())
      if (data.status === 'ok') {
        await refetchList()
        setActiveId(data.export_id)
      } else {
        alert(data.error ?? 'Failed to create export')
      }
    } finally {
      setCreating(false)
    }
  }

  async function saveExport() {
    if (!activeId) return
    setSaving(true)
    try {
      await fetch(`${API}/books/${bookId}/exports/${activeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: editedLabel, chapters: editedChapters }),
      })
      setDirty(false)
      await refetchList()
    } finally {
      setSaving(false)
    }
  }

  async function deleteExport() {
    if (!activeId || !confirm('Delete this export? This cannot be undone.')) return
    setDeleting(true)
    try {
      await fetch(`${API}/books/${bookId}/exports/${activeId}`, { method: 'DELETE' })
      await refetchList()
      setActiveId(null)
      setExportData(null)
      setEditedChapters([])
      setDirty(false)
    } finally {
      setDeleting(false)
    }
  }

  function downloadExport(format: 'md' | 'docx') {
    if (!activeId) return
    const url = `${API}/books/${bookId}/exports/${activeId}/download?format=${format}`
    // Trigger download by creating a temporary link
    const a = document.createElement('a')
    a.href = url
    a.click()
  }

  function updateChapterContent(idx: number, content: string) {
    setEditedChapters(prev => {
      const next = [...prev]
      next[idx] = { ...next[idx], content, word_count: content.split(/\s+/).filter(Boolean).length }
      return next
    })
    setDirty(true)
  }

  function updateChapterTitle(idx: number, title: string) {
    setEditedChapters(prev => {
      const next = [...prev]
      next[idx] = { ...next[idx], title }
      return next
    })
    setDirty(true)
  }

  const currentChapter = editedChapters[selectedChapter] ?? null
  const totalWords = editedChapters.reduce((s, ch) => s + ch.word_count, 0)

  return (
    <div className="flex h-full">
      {/* Left sidebar: export list */}
      <div className="hidden md:flex md:flex-col md:w-52 md:shrink-0 border-r border-border">
        <div className="px-3 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Exports</h3>
          <button
            onClick={createExport}
            disabled={creating}
            title="Create new export"
            className="text-muted-foreground hover:text-foreground disabled:opacity-40 transition-colors"
          >
            {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {exports.length === 0 && (
            <div className="px-3 py-6 text-center space-y-3">
              <FileText size={24} className="mx-auto text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground">No exports yet.</p>
              <Button size="sm" onClick={createExport} disabled={creating} className="gap-1.5 w-full">
                {creating ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
                Create export
              </Button>
            </div>
          )}
          {exports.map(ex => (
            <button
              key={ex.export_id}
              onClick={() => setActiveId(ex.export_id)}
              className={cn(
                'w-full text-left px-3 py-2.5 transition-colors border-b border-border/40 last:border-0',
                activeId === ex.export_id ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/50',
              )}
            >
              <p className="text-xs font-medium truncate">{ex.label}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {ex.chapter_count} ch · {ex.word_count.toLocaleString()} words
              </p>
              <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">
                {formatDate(ex.updated_at)}
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {!activeId ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-3">
              <FileText size={32} className="mx-auto text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">
                {exports.length === 0 ? 'No exports yet — create one to snapshot your approved chapters.' : 'Select an export.'}
              </p>
              {exports.length === 0 && (
                <Button size="sm" onClick={createExport} disabled={creating} className="gap-2">
                  {creating ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Create export
                </Button>
              )}
            </div>
          </div>
        ) : loadingExport ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={20} className="animate-spin text-muted-foreground" />
          </div>
        ) : exportData && (
          <>
            {/* Top bar */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border shrink-0 flex-wrap">
              <input
                value={editedLabel}
                onChange={e => { setEditedLabel(e.target.value); setDirty(true) }}
                className="flex-1 min-w-0 bg-transparent text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-ring rounded px-1"
              />
              <span className="text-xs text-muted-foreground shrink-0">
                {totalWords.toLocaleString()} words
              </span>
              {dirty && (
                <Button size="sm" onClick={saveExport} disabled={saving} className="gap-1.5 shrink-0">
                  {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                  Save
                </Button>
              )}
              <button
                onClick={() => downloadExport('md')}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-border text-muted-foreground hover:text-foreground hover:border-foreground transition-colors shrink-0"
              >
                <Download size={11} /> MD
              </button>
              <button
                onClick={() => downloadExport('docx')}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-border text-muted-foreground hover:text-foreground hover:border-foreground transition-colors shrink-0"
              >
                <Download size={11} /> DOCX
              </button>
              <button
                onClick={deleteExport}
                disabled={deleting}
                className="p-1.5 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                title="Delete export"
              >
                {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
              </button>
            </div>

            {/* Body: chapter nav + editor */}
            <div className="flex flex-1 min-h-0">
              {/* Chapter list */}
              <div className="w-44 shrink-0 border-r border-border flex flex-col overflow-y-auto">
                <div className="px-3 py-3 border-b border-border">
                  <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Chapters</p>
                </div>
                {editedChapters.map((ch, idx) => (
                  <button
                    key={ch.chapter}
                    onClick={() => setSelectedChapter(idx)}
                    className={cn(
                      'w-full text-left px-3 py-2.5 text-xs transition-colors border-b border-border/40 last:border-0',
                      selectedChapter === idx
                        ? 'bg-accent text-accent-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
                    )}
                  >
                    <p className="truncate">{ch.title}</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">{ch.word_count.toLocaleString()} words</p>
                  </button>
                ))}
              </div>

              {/* Chapter editor */}
              {currentChapter && (
                <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                  <div className="px-6 py-3 border-b border-border shrink-0 flex items-center gap-3">
                    <input
                      value={currentChapter.title}
                      onChange={e => updateChapterTitle(selectedChapter, e.target.value)}
                      className="flex-1 bg-transparent text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-ring rounded px-1"
                      placeholder="Chapter title"
                    />
                    <span className="text-xs text-muted-foreground shrink-0">
                      {currentChapter.word_count.toLocaleString()} words
                    </span>
                  </div>
                  <div className="flex-1 overflow-y-auto px-8 py-6">
                    <textarea
                      value={currentChapter.content}
                      onChange={e => updateChapterContent(selectedChapter, e.target.value)}
                      className="w-full h-full min-h-[60vh] resize-none bg-transparent font-serif text-base leading-relaxed text-foreground focus:outline-none placeholder:text-muted-foreground"
                      placeholder="Chapter content…"
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
