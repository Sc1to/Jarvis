import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { API } from '@/lib/api'
import { Pencil, Loader2, CheckCircle, AlertTriangle, ShieldCheck } from 'lucide-react'

export interface EditTarget {
  kind: 'tier' | 'act' | 'chapter' | 'scene'
  tier?: number
  act?: number
  chapter?: number
  scene?: number
}

interface Report {
  ok: boolean
  counts: Record<string, number>
  items: string[]
  errors: string[]
  warnings: string[]
}

interface QaResult { pass?: boolean; notes?: string; issues?: { type?: string; description: string; severity?: string }[] }

const COUNT_LABEL: Record<string, string> = {
  acts: 'acts', chapters: 'chapters', scenes: 'scenes', words: 'words', sections: 'sections', beats: 'beats',
}

function countSummary(r: Report): string {
  return Object.entries(r.counts)
    .filter(([k]) => k !== 'of_sections')
    .map(([k, v]) => (k === 'sections' && r.counts.of_sections ? `${v}/${r.counts.of_sections} sections` : `${v} ${COUNT_LABEL[k] ?? k}`))
    .join(' · ')
}

async function errorText(res: Response): Promise<{ message: string; report?: Report }> {
  const body = await res.json().catch(() => ({}))
  const d = body?.detail
  if (typeof d === 'string') return { message: d }
  if (d?.message) return { message: d.message, report: d.report }
  return { message: `Error ${res.status}` }
}

/**
 * Read-only document view with a manual edit mode.
 * Edit → "Check & save" runs a dry-run validation and shows what was detected
 * (acts / chapters / scenes …). Nothing is written until the author confirms.
 * While editing, `onEditingChange(true)` lets the parent hold approval buttons.
 */
export default function EditableDoc({
  bookId, target, value, onSaved, onEditingChange, running, canEdit = true, streamingCursor, pending = false, className = 'text-sm',
}: {
  bookId: string
  target: EditTarget
  value: string
  onSaved: (normalised: string) => void
  onEditingChange?: (editing: boolean) => void
  running?: boolean
  canEdit?: boolean
  streamingCursor?: boolean
  pending?: boolean
  className?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [report, setReport] = useState<Report | null>(null)   // awaiting confirmation
  const [error, setError] = useState<string | null>(null)
  const [qa, setQa] = useState<QaResult | null>(null)
  const [qaRunning, setQaRunning] = useState(false)

  const url = (p: string) => `${API}/books/${bookId}/phase1/edit/${p}`
  const post = (p: string, extra: Record<string, unknown>) => fetch(url(p), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...target, content: draft, ...extra }),
  })

  function setMode(on: boolean) {
    setEditing(on)
    onEditingChange?.(on)
    if (!on) { setReport(null); setError(null) }
  }

  function startEdit() {
    setDraft(value)
    setQa(null)
    setMode(true)
  }

  async function check() {
    setChecking(true); setError(null)
    try {
      const res = await post('validate', {})
      if (!res.ok) { setError((await errorText(res)).message); return }
      setReport(await res.json())
    } catch {
      setError('Connection error — is the server running?')
    } finally {
      setChecking(false)
    }
  }

  async function confirmSave() {
    setSaving(true); setError(null)
    try {
      const res = await post('save', { confirmed: true })
      if (!res.ok) {
        const e = await errorText(res)
        setError(e.message)
        if (e.report) setReport(e.report)
        return
      }
      const data = await res.json()
      onSaved(data.content)
      setMode(false)
    } catch {
      setError('Connection error — is the server running?')
    } finally {
      setSaving(false)
    }
  }

  async function runQa() {
    setQaRunning(true)
    try {
      const res = await fetch(url('scene-qa'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: target.chapter, scene: target.scene, content: value }),
      })
      setQa(res.ok ? await res.json() : { pass: false, notes: (await errorText(res)).message })
    } catch {
      setQa({ pass: false, notes: 'Connection error' })
    } finally {
      setQaRunning(false)
    }
  }

  if (!editing) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-end gap-2">
          {canEdit && !running && !pending && (
            <Button size="sm" variant="outline" onClick={startEdit} className="gap-1.5 h-7 text-xs">
              <Pencil size={11} />Edit text
            </Button>
          )}
          {target.kind === 'scene' && canEdit && !running && !pending && (
            <Button size="sm" variant="outline" onClick={runQa} disabled={qaRunning} className="gap-1.5 h-7 text-xs">
              {qaRunning ? <Loader2 size={11} className="animate-spin" /> : <ShieldCheck size={11} />}Run brief QA
            </Button>
          )}
        </div>
        <Card><CardContent className="p-4">
          <pre className={`${className} whitespace-pre-wrap font-mono leading-relaxed text-foreground`}>
            {value}{streamingCursor && <span className="animate-pulse">▋</span>}
          </pre>
        </CardContent></Card>
        {qa && (
          <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs space-y-1">
            <p className="font-medium">{qa.pass ? '✓ Brief QA passed' : 'Brief QA flagged issues'}{qa.notes ? ` — ${qa.notes}` : ''}</p>
            {(qa.issues ?? []).map((i, n) => (
              <p key={n} className="text-muted-foreground">• {i.severity ? `[${i.severity}] ` : ''}{i.description}</p>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <textarea
        value={draft}
        onChange={e => { setDraft(e.target.value); setReport(null); setError(null) }}
        disabled={!!report || saving}
        spellCheck={false}
        rows={Math.min(40, Math.max(12, draft.split('\n').length + 2))}
        className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-70"
      />

      {error && <p className="text-xs text-destructive">⚠ {error}</p>}

      {report && (
        <div className={`rounded-md border px-3 py-3 space-y-2 text-sm ${report.ok ? 'border-border bg-muted/30' : 'border-destructive/40 bg-destructive/5'}`}>
          <p className="font-medium flex items-center gap-2">
            {report.ok ? <CheckCircle size={14} className="text-emerald-500" /> : <AlertTriangle size={14} className="text-destructive" />}
            Detected: {countSummary(report)}
          </p>
          {report.items.length > 0 && (
            <ul className="text-xs text-muted-foreground max-h-40 overflow-y-auto space-y-0.5">
              {report.items.map((it, i) => <li key={i}>{it}</li>)}
            </ul>
          )}
          {report.errors.map((e, i) => <p key={i} className="text-xs text-destructive">✕ {e}</p>)}
          {report.warnings.map((w, i) => <p key={i} className="text-xs text-amber-600">! {w}</p>)}
          <p className="text-xs">{report.ok ? 'Is this what you intended? Nothing is saved until you confirm.' : 'Fix the errors above — this can’t be saved as is.'}</p>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => setMode(false)} disabled={saving}>Discard changes</Button>
        {report ? (
          <>
            <Button size="sm" variant="outline" onClick={() => setReport(null)} disabled={saving}>Keep editing</Button>
            {report.ok && (
              <Button size="sm" onClick={confirmSave} disabled={saving} className="gap-2">
                {saving ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}Confirm &amp; save
              </Button>
            )}
          </>
        ) : (
          <Button size="sm" onClick={check} disabled={checking || draft === value || !draft.trim()} className="gap-2">
            {checking && <Loader2 size={13} className="animate-spin" />}Check &amp; save
          </Button>
        )}
      </div>
    </div>
  )
}
