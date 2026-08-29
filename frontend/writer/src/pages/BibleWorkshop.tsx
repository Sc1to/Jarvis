import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { readSSE } from '@/lib/sse'
import { API } from '@/lib/api'
import { ChevronRight, Play, CheckCircle, Lock, Loader2, BookOpen, MapPin, Users, Plus, ListOrdered, Layers } from 'lucide-react'

type Stage = 'book' | 'acts' | 'consolidate' | 'chapters' | 'scenes'
type TierStatus = 'locked' | 'active' | 'running' | 'review' | 'approved'
type P2Step = 'idle' | 'consolidating' | 'researching' | 'done'

const STAGES: { id: Stage; label: string }[] = [
  { id: 'book',        label: 'Book'        },
  { id: 'acts',        label: 'Acts'        },
  { id: 'consolidate', label: 'Consolidate' },
  { id: 'chapters',    label: 'Chapters'    },
  { id: 'scenes',      label: 'Scenes'      },
]

const STAGE_QUESTIONS: Record<Stage, string> = {
  book:        'What happens in this book?',
  acts:        'What happens in each act?',
  consolidate: 'Extract the story bible skeleton.',
  chapters:    'What happens in each chapter?',
  scenes:      'What happens in each scene?',
}

interface TierEntry { content: string | null; approved: boolean; draft?: string | null }
interface BibleEntity {
  type: string; name: string; aliases?: string[]
  coreFacts?: Record<string, string>
  eventLog?: { act: number; chapter: number; event: string }[]
  lifecycle?: number[]
}
interface Bible { ledger: Record<string, BibleEntity>; metadata?: Record<string, unknown> }
interface SkeletonEntity { id: string; name: string; type: string; aliases?: string[]; coreFacts?: Record<string, string>; appearsInActs?: number[] }
interface Skeleton { acts: { number: number; title: string }[]; entities: SkeletonEntity[] }
interface ActStatus { act: number; title: string; approved: boolean; chapters: { number: number; title: string }[]; has_content?: boolean }
interface SceneEntry { number: number; title: string; approved: boolean; has_content?: boolean }
interface ChapterStatus { number: number; title: string; approved: boolean; has_content?: boolean; scenes?: SceneEntry[] }

const TYPE_ICON: Record<string, typeof BookOpen> = {
  character: Users, location: MapPin, faction: Users, object: BookOpen,
}

const ENTITY_TYPES = ['character', 'location', 'faction', 'object'] as const
type EntityType = typeof ENTITY_TYPES[number]

const BLANK_DRAFT = { name: '', type: 'character' as EntityType, description: '', appearsInActs: '' }

export default function BibleWorkshopPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  // ── Queries ──────────────────────────────────────────────────────────────────
  const { data: savedTiers } = useQuery<TierEntry[]>({
    queryKey: ['bible-tiers', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/bible/tiers`).then(r => r.json()),
  })

  const { data: phase2Status, refetch: refetchP2Status } = useQuery({
    queryKey: ['phase2-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase2/status`).then(r => r.json()),
    refetchInterval: false,
  })

  const { data: bible, refetch: refetchBible } = useQuery<Bible>({
    queryKey: ['bible', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/bible`).then(r => r.json()),
    enabled: !!phase2Status?.bible_exists,
  })

  const { data: skeleton, refetch: refetchSkeleton } = useQuery<Skeleton | null>({
    queryKey: ['bible-skeleton', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/bible-skeleton`).then(r => r.json()),
  })

  const { data: tier3Status, refetch: refetchTier3 } = useQuery<{ acts: ActStatus[] } | null>({
    queryKey: ['tier3-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/tier3/status`).then(r => r.json()),
  })

  const { data: tier4Status, refetch: refetchTier4 } = useQuery<{ chapters: ChapterStatus[] } | null>({
    queryKey: ['tier4-status', bookId],
    queryFn: () => fetch(`${API}/books/${bookId}/phase1/tier4/status`).then(r => r.json()),
  })

  // ── Tier 1 & 2 local state ───────────────────────────────────────────────────
  const [contents, setContents] = useState<(string | null)[]>([null, null])
  const [statuses, setStatuses] = useState<TierStatus[]>(['active', 'locked'])
  const [streaming, setStreaming] = useState(false)
  const [directive, setDirective] = useState('')

  // ── Stage state ──────────────────────────────────────────────────────────────
  const [activeStage, setActiveStage] = useState<Stage>('book')
  const hasSetInitial = useRef(false)

  // ── Mini-consolidation state ─────────────────────────────────────────────────
  const [miniConsolRunning, setMiniConsolRunning] = useState(false)
  const [miniConsolError, setMiniConsolError] = useState<string | null>(null)

  // ── Act management state (Tier 3) ────────────────────────────────────────────
  const [activeActNum, setActiveActNum] = useState<number | null>(null)
  const [actContents, setActContents] = useState<Record<number, string>>({})
  const [actRunning, setActRunning] = useState<number | null>(null)
  const [actDirective, setActDirective] = useState('')

  // ── Chapter management state (Tier 4 — scene planning) ─────────────────────
  const [activeChapterNum, setActiveChapterNum] = useState<number | null>(null)
  const [chapterContents, setChapterContents] = useState<Record<number, string>>({})
  const [chapterRunning, setChapterRunning] = useState<number | null>(null)
  const [chapterApproving, setChapterApproving] = useState<number | null>(null)
  const [chapterLockError, setChapterLockError] = useState<Record<number, string>>({})
  const [chapterDirective, setChapterDirective] = useState('')

  // ── Scene management state (individual scene generation) ─────────────────────
  const [sceneContents, setSceneContents] = useState<Record<string, string>>({})
  const [sceneRunning, setSceneRunning] = useState<string | null>(null)
  const [sceneSyncing, setSceneSyncing] = useState<string | null>(null)
  const [sceneDirective, setSceneDirective] = useState('')
  const [expandedScenes, setExpandedScenes] = useState<Set<string>>(new Set())

  // ── Auto-run state (Tier 3) ──────────────────────────────────────────────────
  const autoCancelT3 = useRef(false)
  const [autoRunningT3, setAutoRunningT3] = useState(false)
  const [autoLogT3, setAutoLogT3] = useState<string[]>([])
  const [autoErrorT3, setAutoErrorT3] = useState<string | null>(null)

  // ── Auto-run state (Tier 4) ──────────────────────────────────────────────────
  const autoCancelT4 = useRef(false)
  const [autoRunningT4, setAutoRunningT4] = useState(false)
  const [autoLogT4, setAutoLogT4] = useState<string[]>([])
  const [autoErrorT4, setAutoErrorT4] = useState<string | null>(null)

  // ── Entity sidebar state ─────────────────────────────────────────────────────
  const [addingEntity, setAddingEntity] = useState(false)
  const [editingEntityId, setEditingEntityId] = useState<string | null>(null)
  const [entityDraft, setEntityDraft] = useState(BLANK_DRAFT)

  // ── Phase 2 state ────────────────────────────────────────────────────────────
  const [p2Step, setP2Step] = useState<P2Step>('idle')
  const [p2Log, setP2Log] = useState('')
  const [p2LastSaved, setP2LastSaved] = useState<{ step: string; count: number } | null>(null)
  const p2LogRef = useRef<HTMLPreElement>(null)

  // ── Derived stage completeness ───────────────────────────────────────────────
  const tier1Approved = statuses[0] === 'approved'
  const tier2Approved = statuses[1] === 'approved'
  const skeletonExists = !!(skeleton?.entities?.length)
  const allActsApproved = !!(tier3Status?.acts?.length && tier3Status.acts.every(a => a.approved))
  const allChaptersApproved = !!(tier4Status?.chapters?.length && tier4Status.chapters.every(c => c.approved))

  function stageComplete(s: Stage): boolean {
    if (s === 'book') return tier1Approved
    if (s === 'acts') return tier2Approved
    if (s === 'consolidate') return skeletonExists
    if (s === 'chapters') return allActsApproved
    if (s === 'scenes') return allChaptersApproved
    return false
  }

  function stageLocked(s: Stage): boolean {
    if (s === 'book') return false
    if (s === 'acts') return !tier1Approved
    if (s === 'consolidate') return !tier2Approved
    if (s === 'chapters') return !skeletonExists
    if (s === 'scenes') return !allActsApproved
    return true
  }

  // ── Restore tiers 1 & 2 from server ─────────────────────────────────────────
  useEffect(() => {
    if (!savedTiers) return
    const next: TierStatus[] = ['active', 'locked']
    for (let i = 0; i < 2; i++) {
      if (savedTiers[i]?.approved) {
        next[i] = 'approved'
      } else {
        const unlocked = i === 0 || next[i - 1] === 'approved'
        if (unlocked) next[i] = savedTiers[i]?.draft ? 'review' : 'active'
      }
    }
    setStatuses(next)
    setContents([
      savedTiers[0]?.content ?? savedTiers[0]?.draft ?? null,
      savedTiers[1]?.content ?? savedTiers[1]?.draft ?? null,
    ])
  }, [savedTiers])

  // Set initial active stage once all data has loaded
  useEffect(() => {
    if (hasSetInitial.current || !savedTiers) return
    const t1 = savedTiers[0]?.approved
    const t2 = savedTiers[1]?.approved
    if (!t1) { setActiveStage('book'); hasSetInitial.current = true; return }
    if (!t2) { setActiveStage('acts'); hasSetInitial.current = true; return }
    if (skeleton === undefined) return
    if (!skeleton?.entities?.length) { setActiveStage('consolidate'); hasSetInitial.current = true; return }
    if (tier3Status === undefined) return
    if (!tier3Status?.acts?.length || !tier3Status.acts.every(a => a.approved)) {
      setActiveStage('chapters'); hasSetInitial.current = true; return
    }
    if (tier4Status === undefined) return
    setActiveStage('scenes')
    hasSetInitial.current = true
  }, [savedTiers, skeleton, tier3Status, tier4Status])

  // Auto-load chapter plan from disk when accordion opens and plan exists but isn't in session state
  useEffect(() => {
    if (activeChapterNum === null || !tier4Status) return
    const chInfo = tier4Status.chapters.find(c => c.number === activeChapterNum)
    if (!chInfo || chInfo.scenes?.length || chapterContents[activeChapterNum] !== undefined || !chInfo.has_content) return
    fetch(`${API}/books/${bookId}/phase1/tier4/chapter/${activeChapterNum}/plan`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.content) setChapterContents(prev => ({ ...prev, [activeChapterNum]: data.content })) })
      .catch(() => {})
  // chapterContents intentionally omitted — only run when accordion opens or status changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChapterNum, bookId, tier4Status])

  // Sync p2Step from server state
  useEffect(() => {
    if (!phase2Status) return
    const s = phase2Status.phase2_status
    if (s === 'approved' || s === 'researched' || s === 'consolidated') setP2Step('done')
  }, [phase2Status])

  // ── Tier 1 & 2 actions ───────────────────────────────────────────────────────
  const tierIdx = activeStage === 'book' ? 0 : activeStage === 'acts' ? 1 : -1

  async function runTier(idx: number) {
    setStatuses(prev => { const n = [...prev]; n[idx] = 'running'; return n })
    setContents(prev => { const n = [...prev]; n[idx] = ''; return n })
    setStreaming(true)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/bible/run-tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: idx + 1 }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setContents(prev => { const n = [...prev]; n[idx] = text; return n })
        } else if (event.type === 'error') {
          setContents(prev => { const n = [...prev]; n[idx] = `⚠ ${event.message}`; return n })
          break
        }
      }
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } catch {
      setContents(prev => { const n = [...prev]; n[idx] = '⚠ Connection error — is the server running?'; return n })
      setStatuses(prev => { const n = [...prev]; n[idx] = 'active'; return n })
    } finally {
      setStreaming(false)
    }
  }

  async function approveTier(idx: number) {
    const content = contents[idx] ?? ''
    await fetch(`${API}/books/${bookId}/phase1/bible/approve-tier`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: idx + 1, content }),
    })
    setStatuses(prev => {
      const n = [...prev]
      n[idx] = 'approved'
      if (idx === 0) n[1] = 'active'
      return n
    })
    setActiveStage(idx === 0 ? 'acts' : 'consolidate')
    qc.invalidateQueries({ queryKey: ['bible-tiers', bookId] })
    refetchP2Status()
  }

  async function editTier(idx: number) {
    if (!directive.trim()) return
    const d = directive
    setDirective('')
    setStatuses(prev => { const n = [...prev]; n[idx] = 'running'; return n })
    setContents(prev => { const n = [...prev]; n[idx] = ''; return n })
    setStreaming(true)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/bible/edit-tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: idx + 1, directive: d }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setContents(prev => { const n = [...prev]; n[idx] = text; return n })
        } else if (event.type === 'error') {
          setContents(prev => { const n = [...prev]; n[idx] = `⚠ ${event.message}`; return n })
          break
        }
      }
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } catch {
      setContents(prev => { const n = [...prev]; n[idx] = '⚠ Connection error — is the server running?'; return n })
      setStatuses(prev => { const n = [...prev]; n[idx] = 'review'; return n })
    } finally {
      setStreaming(false)
    }
  }

  async function injectAndRerun(idx: number) {
    if (!directive.trim()) return
    await fetch(`${API}/books/${bookId}/phase1/bible/directive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directive }),
    })
    setDirective('')
    runTier(idx)
  }

  // ── Mini-consolidation action ────────────────────────────────────────────────
  async function runMiniConsol() {
    setMiniConsolRunning(true)
    setMiniConsolError(null)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/mini-consolidate`, { method: 'POST' })
      for await (const event of readSSE(resp)) {
        if (event.type === 'saved') {
          await refetchSkeleton()
          await refetchTier3()
        } else if (event.type === 'error') {
          setMiniConsolError(event.message ?? 'Unknown error')
          break
        }
      }
    } catch {
      setMiniConsolError('Connection error — is the server running?')
    } finally {
      setMiniConsolRunning(false)
    }
  }

  // ── Act actions (Tier 3) ─────────────────────────────────────────────────────
  async function runAct(actNum: number) {
    setActRunning(actNum)
    setActContents(prev => ({ ...prev, [actNum]: '' }))
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/tier3/run-act`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ act: actNum }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setActContents(prev => ({ ...prev, [actNum]: text }))
        } else if (event.type === 'error') {
          setActContents(prev => ({ ...prev, [actNum]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setActContents(prev => ({ ...prev, [actNum]: '⚠ Connection error — is the server running?' }))
    } finally {
      setActRunning(null)
      refetchTier3()
    }
  }

  async function approveAct(actNum: number) {
    const content = actContents[actNum] ?? ''
    await fetch(`${API}/books/${bookId}/phase1/tier3/approve-act`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ act: actNum, content }),
    })
    await refetchTier3()
    await refetchTier4()
  }

  async function editAct(actNum: number) {
    if (!actDirective.trim()) return
    const d = actDirective
    setActDirective('')
    setActRunning(actNum)
    setActContents(prev => ({ ...prev, [actNum]: '' }))
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/tier3/edit-act`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ act: actNum, directive: d }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setActContents(prev => ({ ...prev, [actNum]: text }))
        } else if (event.type === 'error') {
          setActContents(prev => ({ ...prev, [actNum]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setActContents(prev => ({ ...prev, [actNum]: '⚠ Connection error' }))
    } finally {
      setActRunning(null)
    }
  }

  // ── Entity actions ───────────────────────────────────────────────────────────
  function parseActs(s: string): number[] {
    return s.split(',').map(x => parseInt(x.trim())).filter(n => !isNaN(n))
  }

  async function addEntity() {
    if (!entityDraft.name.trim()) return
    await fetch(`${API}/books/${bookId}/phase1/skeleton/entity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: entityDraft.name.trim(),
        type: entityDraft.type,
        purpose: entityDraft.description.trim(),
        appearsInActs: parseActs(entityDraft.appearsInActs),
      }),
    })
    await refetchSkeleton()
    setAddingEntity(false)
    setEntityDraft(BLANK_DRAFT)
  }

  function startEditEntity(e: SkeletonEntity) {
    setEditingEntityId(e.id)
    setAddingEntity(false)
    setEntityDraft({
      name: e.name,
      type: (e.type as EntityType) ?? 'character',
      description: e.coreFacts?.purpose ?? e.coreFacts?.description ?? '',
      appearsInActs: (e.appearsInActs ?? []).join(', '),
    })
  }

  async function saveEditEntity() {
    if (!editingEntityId) return
    await fetch(`${API}/books/${bookId}/phase1/skeleton/entity/${editingEntityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: entityDraft.name.trim() || undefined,
        coreFacts: entityDraft.description.trim() ? { purpose: entityDraft.description.trim() } : undefined,
        appearsInActs: parseActs(entityDraft.appearsInActs),
      }),
    })
    await refetchSkeleton()
    setEditingEntityId(null)
    setEntityDraft(BLANK_DRAFT)
  }

  // ── Chapter actions (Tier 4) ─────────────────────────────────────────────────
  async function runChapter(chapterNum: number) {
    setChapterRunning(chapterNum)
    setChapterContents(prev => ({ ...prev, [chapterNum]: '' }))
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/tier4/run-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: chapterNum }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setChapterContents(prev => ({ ...prev, [chapterNum]: text }))
        } else if (event.type === 'error') {
          setChapterContents(prev => ({ ...prev, [chapterNum]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setChapterContents(prev => ({ ...prev, [chapterNum]: '⚠ Connection error — is the server running?' }))
    } finally {
      setChapterRunning(null)
      refetchTier4()
    }
  }

  async function approveChapter(chapterNum: number) {
    const content = chapterContents[chapterNum] ?? ''
    setChapterApproving(chapterNum)
    setChapterLockError(prev => { const n = { ...prev }; delete n[chapterNum]; return n })
    try {
      const res = await fetch(`${API}/books/${bookId}/phase1/tier4/approve-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: chapterNum, content }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setChapterLockError(prev => ({ ...prev, [chapterNum]: err.detail ?? `Error ${res.status}` }))
        return
      }
      const data = await res.json()
      if (!data.scenes) {
        setChapterLockError(prev => ({ ...prev, [chapterNum]: 'No scenes parsed — ensure headers use "### Scene N — Title" format' }))
        return
      }
      // Auto-open the next unlocked chapter
      const chapters = tier4Status?.chapters ?? []
      const nextCh = chapters.find(c => c.number > chapterNum && !c.approved)
      if (nextCh) setActiveChapterNum(nextCh.number)
    } catch {
      setChapterLockError(prev => ({ ...prev, [chapterNum]: 'Connection error — is the server running?' }))
    } finally {
      setChapterApproving(null)
      await refetchTier4()
    }
  }

  async function editChapter(chapterNum: number) {
    if (!chapterDirective.trim()) return
    const d = chapterDirective
    setChapterDirective('')
    setChapterRunning(chapterNum)
    setChapterContents(prev => ({ ...prev, [chapterNum]: '' }))
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/tier4/edit-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: chapterNum, directive: d }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setChapterContents(prev => ({ ...prev, [chapterNum]: text }))
        } else if (event.type === 'error') {
          setChapterContents(prev => ({ ...prev, [chapterNum]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setChapterContents(prev => ({ ...prev, [chapterNum]: '⚠ Connection error' }))
    } finally {
      setChapterRunning(null)
    }
  }

  // ── Scene actions ────────────────────────────────────────────────────────────
  function sceneKey(chapterNum: number, sceneNum: number) { return `${chapterNum}_${sceneNum}` }

  async function runScene(chapterNum: number, sceneNum: number) {
    const key = sceneKey(chapterNum, sceneNum)
    setSceneRunning(key)
    setSceneContents(prev => ({ ...prev, [key]: '' }))
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase1/tier4/chapter/${chapterNum}/run-scene`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: sceneNum }),
      })
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setSceneContents(prev => ({ ...prev, [key]: text }))
        } else if (event.type === 'error') {
          setSceneContents(prev => ({ ...prev, [key]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setSceneContents(prev => ({ ...prev, [key]: '⚠ Connection error' }))
    } finally {
      setSceneRunning(null)
      refetchTier4()
    }
  }

  async function approveScene(chapterNum: number, sceneNum: number) {
    const key = sceneKey(chapterNum, sceneNum)
    const content = sceneContents[key] ?? ''
    setSceneSyncing(key)
    try {
      const resp = await fetch(
        `${API}/books/${bookId}/phase1/tier4/chapter/${chapterNum}/scene/${sceneNum}/approve`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }
      )
      for await (const event of readSSE(resp)) {
        if (event.type === 'saved' || event.type === 'syncing_bible' || event.type === 'bible_synced' || event.type === 'bible_sync_error') {
          // events consumed — UI shows syncing badge
        }
      }
    } catch { /* ignore */ } finally {
      setSceneSyncing(null)
      await refetchTier4()
      await refetchSkeleton()
    }
  }

  async function editScene(chapterNum: number, sceneNum: number) {
    if (!sceneDirective.trim()) return
    const key = sceneKey(chapterNum, sceneNum)
    const d = sceneDirective
    setSceneDirective('')
    setSceneRunning(key)
    setSceneContents(prev => ({ ...prev, [key]: '' }))
    try {
      const resp = await fetch(
        `${API}/books/${bookId}/phase1/tier4/chapter/${chapterNum}/scene/${sceneNum}/edit`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ directive: d }) }
      )
      let text = ''
      for await (const event of readSSE(resp)) {
        if (event.type === 'token' && event.content) {
          text += event.content
          setSceneContents(prev => ({ ...prev, [key]: text }))
        } else if (event.type === 'error') {
          setSceneContents(prev => ({ ...prev, [key]: `⚠ ${event.message}` }))
          break
        }
      }
    } catch {
      setSceneContents(prev => ({ ...prev, [key]: '⚠ Connection error' }))
    } finally {
      setSceneRunning(null)
    }
  }

  // ── Auto-run: all acts (Tier 3) ──────────────────────────────────────────────
  async function autoRunAllActs() {
    autoCancelT3.current = false
    setAutoRunningT3(true)
    setAutoLogT3([])
    setAutoErrorT3(null)
    const log = (msg: string) => setAutoLogT3(prev => [...prev, msg])
    try {
      const acts = (tier3Status?.acts ?? []).filter(a => !a.approved)
      if (!acts.length) { log('All acts already approved.'); return }
      for (const actInfo of acts) {
        if (autoCancelT3.current) { log('Stopped.'); break }
        log(`Generating Act ${actInfo.act}…`)
        setActRunning(actInfo.act)
        setActContents(prev => ({ ...prev, [actInfo.act]: '' }))
        let text = ''
        const resp = await fetch(`${API}/books/${bookId}/phase1/tier3/run-act`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ act: actInfo.act }),
        })
        for await (const event of readSSE(resp)) {
          if (event.type === 'token' && event.content) {
            text += event.content
            setActContents(prev => ({ ...prev, [actInfo.act]: text }))
          } else if (event.type === 'error') {
            setActRunning(null)
            throw new Error(`Act ${actInfo.act}: ${event.message ?? 'Generation failed'}`)
          }
        }
        setActRunning(null)
        if (!text) throw new Error(`Act ${actInfo.act}: no content generated`)
        if (autoCancelT3.current) { log('Stopped.'); break }
        log(`Approving Act ${actInfo.act}…`)
        await fetch(`${API}/books/${bookId}/phase1/tier3/approve-act`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ act: actInfo.act, content: text }),
        })
        await refetchTier3()
        await refetchTier4()
        log(`Act ${actInfo.act} done ✓`)
      }
      if (!autoCancelT3.current) log('All acts complete!')
    } catch (e) {
      setAutoErrorT3(e instanceof Error ? e.message : String(e))
    } finally {
      setActRunning(null)
      setAutoRunningT3(false)
    }
  }

  // ── Auto-run: all chapters + scene briefs (Tier 4) ───────────────────────────
  async function autoRunAllTier4() {
    autoCancelT4.current = false
    setAutoRunningT4(true)
    setAutoLogT4([])
    setAutoErrorT4(null)
    const log = (msg: string) => setAutoLogT4(prev => [...prev, msg])
    try {
      const initialT4 = await refetchTier4()
      const chapters = initialT4.data?.chapters ?? []
      for (const chInfo of chapters) {
        if (autoCancelT4.current) { log('Stopped.'); break }

        // Phase A: generate + lock scene plan if not yet approved
        if (!chInfo.approved) {
          log(`Planning scenes for Chapter ${chInfo.number}…`)
          setChapterRunning(chInfo.number)
          setChapterContents(prev => ({ ...prev, [chInfo.number]: '' }))
          let planText = ''
          const planResp = await fetch(`${API}/books/${bookId}/phase1/tier4/run-chapter`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter: chInfo.number }),
          })
          for await (const event of readSSE(planResp)) {
            if (event.type === 'token' && event.content) {
              planText += event.content
              setChapterContents(prev => ({ ...prev, [chInfo.number]: planText }))
            } else if (event.type === 'error') {
              setChapterRunning(null)
              throw new Error(`Chapter ${chInfo.number} plan: ${event.message ?? 'Failed'}`)
            }
          }
          setChapterRunning(null)
          if (!planText) throw new Error(`Chapter ${chInfo.number}: no scene plan generated`)
          if (autoCancelT4.current) { log('Stopped.'); break }
          log(`Locking plan for Chapter ${chInfo.number}…`)
          setChapterApproving(chInfo.number)
          const lockRes = await fetch(`${API}/books/${bookId}/phase1/tier4/approve-chapter`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter: chInfo.number, content: planText }),
          })
          setChapterApproving(null)
          if (!lockRes.ok) {
            const err = await lockRes.json().catch(() => ({}))
            throw new Error(`Chapter ${chInfo.number} lock: ${err.detail ?? `HTTP ${lockRes.status}`}`)
          }
          const lockData = await lockRes.json()
          if (!lockData.scenes) {
            throw new Error(`Chapter ${chInfo.number}: no scenes parsed — ensure "### Scene N — Title" headers`)
          }
        }

        // Phase B: run + approve each scene brief
        if (autoCancelT4.current) { log('Stopped.'); break }
        const freshT4 = await refetchTier4()
        const freshCh = (freshT4.data?.chapters ?? []).find(c => c.number === chInfo.number)
        for (const scInfo of freshCh?.scenes ?? []) {
          if (autoCancelT4.current) { log('Stopped.'); break }
          if (scInfo.approved) continue
          const key = `${chInfo.number}_${scInfo.number}`
          log(`Writing brief Ch${chInfo.number} Sc${scInfo.number}…`)
          setSceneRunning(key)
          setSceneContents(prev => ({ ...prev, [key]: '' }))
          let scText = ''
          const scResp = await fetch(`${API}/books/${bookId}/phase1/tier4/chapter/${chInfo.number}/run-scene`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scene: scInfo.number }),
          })
          for await (const event of readSSE(scResp)) {
            if (event.type === 'token' && event.content) {
              scText += event.content
              setSceneContents(prev => ({ ...prev, [key]: scText }))
            } else if (event.type === 'error') {
              setSceneRunning(null)
              throw new Error(`Ch${chInfo.number} Sc${scInfo.number}: ${event.message ?? 'Failed'}`)
            }
          }
          setSceneRunning(null)
          if (!scText) throw new Error(`Ch${chInfo.number} Sc${scInfo.number}: no content generated`)
          if (autoCancelT4.current) { log('Stopped.'); break }
          log(`Approving brief Ch${chInfo.number} Sc${scInfo.number} (bible sync)…`)
          setSceneSyncing(key)
          const approveResp = await fetch(
            `${API}/books/${bookId}/phase1/tier4/chapter/${chInfo.number}/scene/${scInfo.number}/approve`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: scText }) }
          )
          for await (const event of readSSE(approveResp)) {
            if (event.type === 'bible_sync_error') {
              // Scene is already saved — bible sync failure is non-fatal in auto-mode
              log(`⚠ Ch${chInfo.number} Sc${scInfo.number} bible sync failed (scene saved): ${event.message ?? 'JSON error'}`)
            }
          }
          setSceneSyncing(null)
          await refetchTier4()
          await refetchSkeleton()
        }
        if (!autoCancelT4.current) log(`Chapter ${chInfo.number} complete ✓`)
      }
      if (!autoCancelT4.current) log('All chapters and scenes complete!')
    } catch (e) {
      setAutoErrorT4(e instanceof Error ? e.message : String(e))
    } finally {
      setChapterRunning(null)
      setChapterApproving(null)
      setSceneRunning(null)
      setSceneSyncing(null)
      setAutoRunningT4(false)
    }
  }

  // ── Phase 2 actions ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (p2LogRef.current) p2LogRef.current.scrollTop = p2LogRef.current.scrollHeight
  }, [p2Log])

  async function runP2(endpoint: string, label: string, nextStep: P2Step) {
    setP2Step(nextStep)
    setP2Log('')
    setP2LastSaved(null)
    try {
      const resp = await fetch(`${API}/books/${bookId}/phase2/${endpoint}`, { method: 'POST' })
      for await (const event of readSSE(resp)) {
        if (event.type === 'token') setP2Log(prev => prev + event.content)
        else if (event.type === 'status') setP2Log(prev => prev + `\n[${event.message}]\n`)
        else if (event.type === 'saved') {
          setP2LastSaved({ step: label, count: event.entity_count as number })
          await refetchP2Status()
          await refetchBible()
        } else if (event.type === 'error') {
          setP2Log(prev => prev + `\n⚠ ${event.message}`)
          setP2Step('idle')
          return
        }
      }
    } catch {
      setP2Log(prev => prev + '\n⚠ Connection error')
      setP2Step('idle')
    }
  }

  async function approveP2() {
    await fetch(`${API}/books/${bookId}/phase2/approve`, { method: 'POST' })
    await refetchP2Status()
    qc.invalidateQueries({ queryKey: ['bible', bookId] })
  }

  // ── Entity ledger (sidebar — Phase 2) ───────────────────────────────────────
  const ledger = bible?.ledger ?? {}
  const byType: Record<string, [string, BibleEntity][]> = {}
  for (const [id, entity] of Object.entries(ledger)) {
    const t = entity.type ?? 'other'
    ;(byType[t] ??= []).push([id, entity])
  }
  const typeOrder = ['character', 'location', 'faction', 'object']
  const sortedTypes = [...new Set([...typeOrder, ...Object.keys(byType)])].filter(t => byType[t])

  const p2Approved = phase2Status?.phase2_approved
  const p2Status = phase2Status?.phase2_status ?? 'idle'
  const bibleExists = phase2Status?.bible_exists
  const entityCount = phase2Status?.entity_count ?? 0

  // ── Skeleton sidebar helpers ─────────────────────────────────────────────────
  const skeletonByType = ENTITY_TYPES.reduce<Record<string, SkeletonEntity[]>>((acc, t) => {
    acc[t] = (skeleton?.entities ?? []).filter(e => e.type === t)
    return acc
  }, {} as Record<string, SkeletonEntity[]>)

  // ── Entity form component (inline, reused for add + edit) ────────────────────
  function EntityForm({ onSave, onCancel }: { onSave: () => void; onCancel: () => void }) {
    return (
      <div className="border border-border rounded-md p-3 space-y-2 bg-muted/20">
        <input
          value={entityDraft.name}
          onChange={e => setEntityDraft(p => ({ ...p, name: e.target.value }))}
          placeholder="Name"
          className="w-full rounded border border-input bg-transparent px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <select
          value={entityDraft.type}
          onChange={e => setEntityDraft(p => ({ ...p, type: e.target.value as EntityType }))}
          className="w-full rounded border border-input bg-transparent px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <textarea
          value={entityDraft.description}
          onChange={e => setEntityDraft(p => ({ ...p, description: e.target.value }))}
          placeholder="Role / description"
          rows={2}
          className="w-full resize-none rounded border border-input bg-transparent px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <input
          value={entityDraft.appearsInActs}
          onChange={e => setEntityDraft(p => ({ ...p, appearsInActs: e.target.value }))}
          placeholder="Acts: 1, 2, 3"
          className="w-full rounded border border-input bg-transparent px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <div className="flex gap-1.5">
          <Button size="sm" className="h-6 text-xs px-2" onClick={onSave} disabled={!entityDraft.name.trim()}>Save</Button>
          <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* ── Stage stepper ── */}
        <div className="flex items-center gap-2 px-6 py-4 border-b border-border">
          {STAGES.map((stage, i) => {
            const complete = stageComplete(stage.id)
            const locked = stageLocked(stage.id)
            const isActive = activeStage === stage.id
            return (
              <div key={stage.id} className="flex items-center gap-2">
                <button
                  className={cn(
                    'flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md transition-colors',
                    complete
                      ? 'text-emerald-500'
                      : isActive
                        ? 'bg-accent text-accent-foreground font-medium'
                        : locked
                          ? 'text-muted-foreground/40 cursor-not-allowed'
                          : 'text-muted-foreground hover:text-foreground'
                  )}
                  onClick={() => !locked && !streaming && setActiveStage(stage.id)}
                  disabled={locked || streaming}
                >
                  {complete && <CheckCircle size={13} />}
                  {stage.label}
                </button>
                {i < STAGES.length - 1 && <ChevronRight size={14} className="text-muted-foreground/40" />}
              </div>
            )
          })}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
          {/* ── Tier 1 (Book) / Tier 2 (Acts) panel ── */}
          {tierIdx >= 0 && (
            <>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-semibold">Tier {tierIdx + 1} — {activeStage === 'book' ? 'Book' : 'Acts'}</h2>
                  <p className="text-sm text-muted-foreground">{STAGE_QUESTIONS[activeStage]}</p>
                </div>
                <div className="flex gap-2">
                  {statuses[tierIdx] === 'active' && (
                    <Button size="sm" onClick={() => runTier(tierIdx)} className="gap-2" disabled={streaming}>
                      <Play size={13} />Run agent
                    </Button>
                  )}
                  {statuses[tierIdx] === 'running' && (
                    <Badge variant="secondary" className="gap-1.5">
                      <Loader2 size={12} className="animate-spin" />Agent running…
                    </Badge>
                  )}
                  {statuses[tierIdx] === 'review' && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => runTier(tierIdx)} disabled={streaming}>Re-run</Button>
                      <Button size="sm" onClick={() => approveTier(tierIdx)} className="gap-2" disabled={streaming}>
                        <Lock size={13} />Approve tier
                      </Button>
                    </>
                  )}
                  {statuses[tierIdx] === 'approved' && <Badge variant="success">Approved</Badge>}
                </div>
              </div>

              <Card className="min-h-[300px]">
                <CardContent className="p-5">
                  {statuses[tierIdx] === 'locked' && (
                    <p className="text-sm text-muted-foreground italic">Complete the tier above to unlock this one.</p>
                  )}
                  {statuses[tierIdx] === 'active' && !contents[tierIdx] && (
                    <p className="text-sm text-muted-foreground italic">Run the agent to generate this tier.</p>
                  )}
                  {contents[tierIdx] && (
                    <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                      {contents[tierIdx]}
                      {statuses[tierIdx] === 'running' && <span className="animate-pulse">▋</span>}
                    </pre>
                  )}
                </CardContent>
              </Card>

              {statuses[tierIdx] === 'review' && (
                <div className="space-y-2">
                  <Separator />
                  <p className="text-xs text-muted-foreground pt-2">
                    Inject a directive — saved to directives.md, agent re-runs incorporating it.
                  </p>
                  <div className="flex gap-2">
                    <textarea
                      value={directive}
                      onChange={e => setDirective(e.target.value)}
                      placeholder='e.g. "Add a merchant who joins in Acre and dies in Constantinople…"'
                      rows={2}
                      disabled={streaming}
                      className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                    <Button variant="outline" size="sm" onClick={() => editTier(tierIdx)} disabled={!directive.trim() || streaming}>
                      Edit current
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => injectAndRerun(tierIdx)} disabled={!directive.trim() || streaming}>
                      Inject &amp; re-run
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── Consolidate panel ── */}
          {activeStage === 'consolidate' && (
            <div className="space-y-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-semibold">Mini-Consolidation — Story Bible Skeleton</h2>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Extract named entities from your North Star and Acts breakdown.
                    These seed the entity sidebar in the Chapters stage.
                  </p>
                </div>
                <Button size="sm" onClick={runMiniConsol} className="gap-2 shrink-0 ml-4" disabled={miniConsolRunning}>
                  {miniConsolRunning
                    ? <><Loader2 size={13} className="animate-spin" />Extracting…</>
                    : <><Play size={13} />{skeletonExists ? 'Re-run' : 'Extract skeleton'}</>
                  }
                </Button>
              </div>

              {miniConsolError && (
                <p className="text-sm text-destructive">⚠ {miniConsolError}</p>
              )}

              {miniConsolRunning && (
                <Card className="bg-muted/30">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 size={14} className="animate-spin" />
                      Agent reading North Star and Acts, extracting entities…
                    </div>
                  </CardContent>
                </Card>
              )}

              {skeletonExists && skeleton && !miniConsolRunning && (
                <>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-muted-foreground">
                      {skeleton.acts.length} acts · {skeleton.entities.length} entities extracted
                    </span>
                    <Badge variant="success" className="gap-1">
                      <CheckCircle size={11} />Ready
                    </Badge>
                  </div>

                  <div className="space-y-3">
                    {ENTITY_TYPES.filter(t => skeleton.entities.some(e => e.type === t)).map(type => {
                      const Icon = TYPE_ICON[type] ?? BookOpen
                      const entities = skeleton.entities.filter(e => e.type === type)
                      return (
                        <div key={type}>
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                            {type}s ({entities.length})
                          </p>
                          <div className="space-y-0.5">
                            {entities.map(e => (
                              <div key={e.id} className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-muted/50">
                                <Icon size={12} className="shrink-0 text-muted-foreground" />
                                <span className="text-sm font-medium">{e.name}</span>
                                <span className="text-[10px] text-muted-foreground/60">{e.id}</span>
                                {e.appearsInActs?.length ? (
                                  <span className="text-[10px] text-muted-foreground ml-auto">
                                    Acts {e.appearsInActs.join(', ')}
                                  </span>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  <div className="pt-4 border-t border-border space-y-3">
                    <p className="text-sm font-medium">Choose how you want to write this book</p>
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        onClick={() => navigate(`/books/${bookId}/work`)}
                        className="flex flex-col gap-2 p-4 rounded-lg border-2 border-border hover:border-primary hover:bg-accent/30 text-left transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <ListOrdered size={18} className="text-primary shrink-0" />
                          <span className="text-sm font-semibold">Sequential</span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          Work act by act, chapter by chapter, scene by scene — brief then prose before moving on.
                        </p>
                      </button>
                      <button
                        onClick={() => setActiveStage('chapters')}
                        className="flex flex-col gap-2 p-4 rounded-lg border-2 border-border hover:border-primary hover:bg-accent/30 text-left transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <Layers size={18} className="text-primary shrink-0" />
                          <span className="text-sm font-semibold">Batch</span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          Plan all chapters and scenes first, then write everything in the Writing Loop.
                        </p>
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Chapters panel (Tier 3 — per act) ── */}
          {activeStage === 'chapters' && (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-semibold">Chapters — per act</h2>
                  <p className="text-sm text-muted-foreground">Generate and approve chapter summaries act by act.</p>
                </div>
                <button
                  onClick={autoRunningT3 ? () => { autoCancelT3.current = true } : autoRunAllActs}
                  disabled={!tier3Status?.acts?.length || (allActsApproved && !autoRunningT3)}
                  className={`shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-colors ${
                    autoRunningT3
                      ? 'border-destructive text-destructive hover:bg-destructive/10'
                      : 'border-border text-muted-foreground hover:text-foreground hover:border-foreground disabled:opacity-40 disabled:cursor-not-allowed'
                  }`}
                >
                  {autoRunningT3
                    ? <><Loader2 size={11} className="animate-spin" />Stop</>
                    : <><Play size={11} />Auto-run all</>
                  }
                </button>
              </div>

              {(autoLogT3.length > 0 || autoErrorT3) && (
                <div className="space-y-1.5">
                  {autoErrorT3 && (
                    <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                      <span className="flex-1">⚠ {autoErrorT3}</span>
                      <button onClick={() => setAutoErrorT3(null)} className="shrink-0 hover:opacity-70 leading-none">✕</button>
                    </div>
                  )}
                  {autoLogT3.length > 0 && (
                    <pre className="text-xs font-mono text-muted-foreground bg-muted/30 rounded-md px-3 py-2 max-h-28 overflow-y-auto whitespace-pre-wrap">
                      {autoLogT3.join('\n')}{autoRunningT3 && <span className="animate-pulse"> ▋</span>}
                    </pre>
                  )}
                </div>
              )}

              {!tier3Status?.acts?.length ? (
                <Card className="bg-muted/30">
                  <CardContent className="p-4">
                    <p className="text-sm text-muted-foreground italic">No acts found — run mini-consolidation first.</p>
                  </CardContent>
                </Card>
              ) : (
                tier3Status.acts.map(actInfo => {
                  const isExpanded = activeActNum === actInfo.act
                  const content = actContents[actInfo.act]
                  const isRunning = actRunning === actInfo.act
                  const hasLocalContent = content !== undefined

                  return (
                    <div key={actInfo.act} className="border border-border rounded-lg overflow-hidden">
                      {/* Act header — click to expand */}
                      <button
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/30 transition-colors text-left"
                        onClick={() => setActiveActNum(isExpanded ? null : actInfo.act)}
                      >
                        <div className="flex items-center gap-2.5">
                          {actInfo.approved
                            ? <CheckCircle size={14} className="text-emerald-500 shrink-0" />
                            : isRunning
                              ? <Loader2 size={14} className="animate-spin text-muted-foreground shrink-0" />
                              : <div className="w-3.5 h-3.5 rounded-full border border-muted-foreground/40 shrink-0" />
                          }
                          <span className="text-sm font-medium">Act {actInfo.act} — {actInfo.title}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          {actInfo.approved && (
                            <span className="text-xs text-muted-foreground">{actInfo.chapters.length} ch</span>
                          )}
                          <ChevronRight size={14} className={cn('text-muted-foreground/60 transition-transform duration-150', isExpanded && 'rotate-90')} />
                        </div>
                      </button>

                      {/* Act detail */}
                      {isExpanded && (
                        <div className="border-t border-border px-4 py-4 space-y-3">
                          {actInfo.approved ? (
                            <>
                              <div className="space-y-1">
                                {actInfo.chapters.map(ch => (
                                  <p key={ch.number} className="text-sm text-muted-foreground">
                                    <span className="text-foreground font-medium">Ch {ch.number}</span> — {ch.title}
                                  </p>
                                ))}
                              </div>
                              <Button size="sm" variant="outline" onClick={() => runAct(actInfo.act)} disabled={isRunning} className="gap-2">
                                <Play size={12} />Re-run act
                              </Button>
                            </>
                          ) : (
                            <>
                              <div className="flex items-center justify-end gap-2">
                                {isRunning ? (
                                  <Badge variant="secondary" className="gap-1.5">
                                    <Loader2 size={12} className="animate-spin" />Agent running…
                                  </Badge>
                                ) : (
                                  <Button size="sm" onClick={() => runAct(actInfo.act)} className="gap-2">
                                    <Play size={13} />{actInfo.has_content || hasLocalContent ? 'Re-run' : 'Run act'}
                                  </Button>
                                )}
                                {hasLocalContent && !isRunning && (
                                  <Button size="sm" onClick={() => approveAct(actInfo.act)} className="gap-2">
                                    <Lock size={13} />Approve act
                                  </Button>
                                )}
                              </div>

                              <Card className="min-h-[180px]">
                                <CardContent className="p-4">
                                  {!hasLocalContent && !actInfo.has_content && (
                                    <p className="text-sm text-muted-foreground italic">Run the agent to generate chapters for this act.</p>
                                  )}
                                  {!hasLocalContent && actInfo.has_content && (
                                    <p className="text-sm text-muted-foreground italic">Content exists from a previous session. Re-run to reload.</p>
                                  )}
                                  {hasLocalContent && (
                                    <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed text-foreground">
                                      {content}
                                      {isRunning && <span className="animate-pulse">▋</span>}
                                    </pre>
                                  )}
                                </CardContent>
                              </Card>

                              {hasLocalContent && !isRunning && (
                                <div className="space-y-2">
                                  <Separator />
                                  <div className="flex gap-2 pt-1">
                                    <textarea
                                      value={actDirective}
                                      onChange={e => setActDirective(e.target.value)}
                                      placeholder='e.g. "Add a confrontation in Act 2 chapter 3…"'
                                      rows={2}
                                      className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                    />
                                    <Button variant="outline" size="sm" onClick={() => editAct(actInfo.act)} disabled={!actDirective.trim()}>
                                      Edit current
                                    </Button>
                                  </div>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })
              )}

              {allActsApproved && (
                <div className="flex justify-end pt-2">
                  <Button onClick={() => setActiveStage('scenes')} className="gap-2">
                    Continue to Scenes <ChevronRight size={14} />
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* ── Scenes panel (Tier 4) ── */}
          {activeStage === 'scenes' && (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-semibold">Scenes — one scene at a time</h2>
                  <p className="text-sm text-muted-foreground">Plan scenes per chapter, then generate and approve each scene. Approving syncs the story bible.</p>
                </div>
                <button
                  onClick={autoRunningT4 ? () => { autoCancelT4.current = true } : autoRunAllTier4}
                  disabled={!tier4Status?.chapters?.length || (allChaptersApproved && !autoRunningT4)}
                  className={`shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-colors ${
                    autoRunningT4
                      ? 'border-destructive text-destructive hover:bg-destructive/10'
                      : 'border-border text-muted-foreground hover:text-foreground hover:border-foreground disabled:opacity-40 disabled:cursor-not-allowed'
                  }`}
                >
                  {autoRunningT4
                    ? <><Loader2 size={11} className="animate-spin" />Stop</>
                    : <><Play size={11} />Auto-run all</>
                  }
                </button>
              </div>

              {(autoLogT4.length > 0 || autoErrorT4) && (
                <div className="space-y-1.5">
                  {autoErrorT4 && (
                    <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                      <span className="flex-1">⚠ {autoErrorT4}</span>
                      <button onClick={() => setAutoErrorT4(null)} className="shrink-0 hover:opacity-70 leading-none">✕</button>
                    </div>
                  )}
                  {autoLogT4.length > 0 && (
                    <pre className="text-xs font-mono text-muted-foreground bg-muted/30 rounded-md px-3 py-2 max-h-28 overflow-y-auto whitespace-pre-wrap">
                      {autoLogT4.join('\n')}{autoRunningT4 && <span className="animate-pulse"> ▋</span>}
                    </pre>
                  )}
                </div>
              )}

              {!tier4Status?.chapters?.length ? (
                <Card className="bg-muted/30"><CardContent className="p-4">
                  <p className="text-sm text-muted-foreground italic">No chapters found — approve all acts first.</p>
                </CardContent></Card>
              ) : (
                tier4Status.chapters.map(chInfo => {
                  const isExpanded = activeChapterNum === chInfo.number
                  const planContent = chapterContents[chInfo.number]
                  const isPlanRunning = chapterRunning === chInfo.number
                  const isPlanApproving = chapterApproving === chInfo.number
                  const hasScenes = !!(chInfo.scenes?.length)

                  return (
                    <div key={chInfo.number} className="border border-border rounded-lg overflow-hidden">
                      {/* Chapter header */}
                      <button
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/30 transition-colors text-left"
                        onClick={() => setActiveChapterNum(isExpanded ? null : chInfo.number)}
                      >
                        <div className="flex items-center gap-2.5">
                          {chInfo.approved
                            ? <CheckCircle size={14} className="text-emerald-500 shrink-0" />
                            : isPlanRunning
                              ? <Loader2 size={14} className="animate-spin text-muted-foreground shrink-0" />
                              : <div className="w-3.5 h-3.5 rounded-full border border-muted-foreground/40 shrink-0" />
                          }
                          <span className="text-sm font-medium">Ch {chInfo.number} — {chInfo.title}</span>
                          {hasScenes && (
                            <span className="text-xs text-muted-foreground">
                              ({chInfo.scenes!.filter(s => s.approved).length}/{chInfo.scenes!.length} scenes)
                            </span>
                          )}
                        </div>
                        <ChevronRight size={14} className={cn('text-muted-foreground/60 transition-transform duration-150', isExpanded && 'rotate-90')} />
                      </button>

                      {isExpanded && (
                        <div className="border-t border-border px-4 py-4 space-y-3">
                          {/* ── Phase A: plan scenes ── */}
                          {!hasScenes && (
                            <>
                              <div className="flex items-center justify-between">
                                <p className="text-xs text-muted-foreground">Step 1 — generate the scene list for this chapter.</p>
                                <div className="flex gap-2">
                                  {isPlanRunning ? (
                                    <Badge variant="secondary" className="gap-1.5"><Loader2 size={12} className="animate-spin" />Planning…</Badge>
                                  ) : (
                                    <Button size="sm" onClick={() => runChapter(chInfo.number)} className="gap-2">
                                      <Play size={13} />{chInfo.has_content || planContent !== undefined ? 'Re-plan' : 'Plan scenes'}
                                    </Button>
                                  )}
                                  {planContent !== undefined && !isPlanRunning && (
                                    <Button size="sm" onClick={() => approveChapter(chInfo.number)} disabled={isPlanApproving} className="gap-2">
                                      {isPlanApproving ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}
                                      {isPlanApproving ? 'Locking…' : 'Lock plan'}
                                    </Button>
                                  )}
                                </div>
                              </div>
                              {chapterLockError[chInfo.number] && (
                                <p className="text-xs text-red-500">⚠ {chapterLockError[chInfo.number]}</p>
                              )}
                              {planContent !== undefined && (
                                <>
                                  <Card className="min-h-[140px]"><CardContent className="p-4">
                                    <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed text-foreground">
                                      {planContent}{isPlanRunning && <span className="animate-pulse">▋</span>}
                                    </pre>
                                  </CardContent></Card>
                                  {!isPlanRunning && (
                                    <div className="flex gap-2 pt-1">
                                      <textarea
                                        value={chapterDirective}
                                        onChange={e => setChapterDirective(e.target.value)}
                                        placeholder='e.g. "Add a mystery subplot to scene 2…"'
                                        rows={2}
                                        className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                      />
                                      <Button variant="outline" size="sm" onClick={() => editChapter(chInfo.number)} disabled={!chapterDirective.trim()}>
                                        Edit plan
                                      </Button>
                                    </div>
                                  )}
                                </>
                              )}
                              {planContent === undefined && chInfo.has_content && (
                                <p className="text-xs text-muted-foreground italic">Loading plan…</p>
                              )}
                            </>
                          )}

                          {/* ── Phase B: individual scenes ── */}
                          {hasScenes && (
                            <div className="space-y-2">
                              {chInfo.scenes!.map(scInfo => {
                                const key = sceneKey(chInfo.number, scInfo.number)
                                const isScExpanded = expandedScenes.has(key)
                                const scContent = sceneContents[key]
                                const isScRunning = sceneRunning === key
                                const isScSyncing = sceneSyncing === key
                                const hasLocalSc = scContent !== undefined

                                return (
                                  <div key={scInfo.number} className="border border-border/60 rounded-md overflow-hidden">
                                    <button
                                      className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-muted/20 transition-colors text-left"
                                      onClick={async () => {
                                        const next = new Set(expandedScenes)
                                        next.has(key) ? next.delete(key) : next.add(key)
                                        setExpandedScenes(next)
                                        if (!next.has(key)) return
                                        if (scContent !== undefined) return
                                        if (!scInfo.has_content) return
                                        try {
                                          const r = await fetch(`${API}/books/${bookId}/phase1/tier4/chapter/${chInfo.number}/scene/${scInfo.number}`)
                                          if (r.ok) {
                                            const d = await r.json()
                                            setSceneContents(prev => ({ ...prev, [key]: d.content }))
                                          }
                                        } catch { /* leave empty, user can re-run */ }
                                      }}
                                    >
                                      <div className="flex items-center gap-2">
                                        {scInfo.approved
                                          ? <CheckCircle size={12} className="text-emerald-500 shrink-0" />
                                          : isScRunning || isScSyncing
                                            ? <Loader2 size={12} className="animate-spin text-muted-foreground shrink-0" />
                                            : <div className="w-3 h-3 rounded-full border border-muted-foreground/40 shrink-0" />
                                        }
                                        <span className="text-xs font-medium">Scene {scInfo.number} — {scInfo.title}</span>
                                      </div>
                                      <ChevronRight size={12} className={cn('text-muted-foreground/60 transition-transform duration-150', isScExpanded && 'rotate-90')} />
                                    </button>

                                    {isScExpanded && (
                                      <div className="border-t border-border/60 px-3 py-3 space-y-2.5">
                                        <div className="flex items-center justify-end gap-2 flex-wrap">
                                          {isScSyncing && (
                                            <Badge variant="secondary" className="gap-1.5"><Loader2 size={11} className="animate-spin" />Syncing bible…</Badge>
                                          )}
                                          {isScRunning && !isScSyncing && (
                                            <Badge variant="secondary" className="gap-1.5"><Loader2 size={11} className="animate-spin" />Writing…</Badge>
                                          )}
                                          {!isScRunning && !isScSyncing && (
                                            <>
                                              <Button size="sm" variant="outline" onClick={() => runScene(chInfo.number, scInfo.number)} className="gap-1.5 h-7 text-xs">
                                                <Play size={11} />{hasLocalSc || scInfo.has_content ? 'Re-run' : 'Write scene'}
                                              </Button>
                                              {hasLocalSc && !scInfo.approved && (
                                                <Button size="sm" onClick={() => approveScene(chInfo.number, scInfo.number)} className="gap-1.5 h-7 text-xs">
                                                  <Lock size={11} />Approve + sync
                                                </Button>
                                              )}
                                              {scInfo.approved && (
                                                <Badge variant="success" className="gap-1"><CheckCircle size={11} />Approved</Badge>
                                              )}
                                            </>
                                          )}
                                        </div>

                                        {!hasLocalSc && !scInfo.has_content && (
                                          <p className="text-xs text-muted-foreground italic">Run the agent to write this scene.</p>
                                        )}
                                        {!hasLocalSc && scInfo.has_content && (
                                          <p className="text-xs text-muted-foreground italic">Content exists. Re-run to reload.</p>
                                        )}
                                        {hasLocalSc && (
                                          <Card><CardContent className="p-3">
                                            <pre className="text-sm whitespace-pre-wrap leading-relaxed text-foreground">
                                              {scContent}{isScRunning && <span className="animate-pulse">▋</span>}
                                            </pre>
                                          </CardContent></Card>
                                        )}

                                        {hasLocalSc && !isScRunning && !isScSyncing && (
                                          <>
                                            <Separator />
                                            <div className="flex gap-2">
                                              <textarea
                                                value={sceneDirective}
                                                onChange={e => setSceneDirective(e.target.value)}
                                                placeholder='e.g. "Lengthen the confrontation — more tension before the reveal"'
                                                rows={2}
                                                className="flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                              />
                                              <Button variant="outline" size="sm" className="h-auto text-xs" onClick={() => editScene(chInfo.number, scInfo.number)} disabled={!sceneDirective.trim()}>
                                                Edit
                                              </Button>
                                            </div>
                                          </>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          )}

          {/* ── Phase 2 panel (appears when all chapters approved) ── */}
          {allChaptersApproved && (
            <>
              <Separator className="my-4" />
              <div className="space-y-4">
                <div>
                  <h2 className="font-semibold">Phase 2 — Research &amp; Entity Completion</h2>
                  <p className="text-sm text-muted-foreground">
                    Consolidate the bible into a structured entity ledger, then enrich every entity.
                  </p>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn('flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                        bibleExists ? 'bg-emerald-500/20 text-emerald-500' : 'bg-muted text-muted-foreground')}>1</span>
                      <span className="text-sm font-medium">Consolidate entity ledger</span>
                      {bibleExists && <CheckCircle size={13} className="text-emerald-500 shrink-0" />}
                    </div>
                    {!p2Approved && (
                      <Button size="sm" variant={bibleExists ? 'outline' : 'default'}
                        disabled={p2Step === 'consolidating' || p2Step === 'researching'}
                        onClick={() => runP2('consolidate', 'Consolidate', 'consolidating')}>
                        {p2Step === 'consolidating'
                          ? <><Loader2 size={12} className="animate-spin mr-1" />Running…</>
                          : bibleExists ? 'Re-run' : 'Run'}
                      </Button>
                    )}
                  </div>
                  {bibleExists && <p className="text-xs text-muted-foreground pl-7">{entityCount} entities in ledger</p>}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn('flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                        (p2Status === 'researched' || p2Status === 'approved') ? 'bg-emerald-500/20 text-emerald-500'
                          : bibleExists ? 'bg-muted text-foreground' : 'bg-muted text-muted-foreground/40')}>2</span>
                      <span className={cn('text-sm font-medium', !bibleExists && 'text-muted-foreground/40')}>
                        Research &amp; complete entities
                      </span>
                      {(p2Status === 'researched' || p2Status === 'approved') && <CheckCircle size={13} className="text-emerald-500 shrink-0" />}
                    </div>
                    {!p2Approved && bibleExists && (
                      <Button size="sm" variant={(p2Status === 'researched') ? 'outline' : 'default'}
                        disabled={p2Step === 'consolidating' || p2Step === 'researching'}
                        onClick={() => runP2('run', 'Research', 'researching')}>
                        {p2Step === 'researching'
                          ? <><Loader2 size={12} className="animate-spin mr-1" />Running…</>
                          : (p2Status === 'researched' || p2Status === 'approved') ? 'Re-run' : 'Run'}
                      </Button>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={cn('flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold',
                      p2Approved ? 'bg-emerald-500/20 text-emerald-500'
                        : (p2Status === 'researched') ? 'bg-muted text-foreground' : 'bg-muted text-muted-foreground/40')}>3</span>
                    <span className={cn('text-sm font-medium', !bibleExists && 'text-muted-foreground/40')}>
                      Approve &amp; unlock Writing Loop
                    </span>
                    {p2Approved && <CheckCircle size={13} className="text-emerald-500 shrink-0" />}
                  </div>
                  {!p2Approved && p2Status === 'researched' && (
                    <Button size="sm" onClick={approveP2} className="gap-2">
                      <Lock size={13} />Approve Phase 2
                    </Button>
                  )}
                  {p2Approved && <Badge variant="success">Writing Loop unlocked</Badge>}
                </div>

                {p2LastSaved && (
                  <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400">
                    <CheckCircle size={16} className="shrink-0" />
                    <span className="text-sm font-medium">{p2LastSaved.step} saved — {p2LastSaved.count} entities</span>
                  </div>
                )}
                {p2Log && (
                  <Card className="bg-muted/30">
                    <CardContent className="p-4">
                      <pre ref={p2LogRef} className="text-xs font-mono whitespace-pre-wrap leading-relaxed text-muted-foreground max-h-48 overflow-y-auto">
                        {p2Log}
                        {(p2Step === 'consolidating' || p2Step === 'researching') && <span className="animate-pulse">▋</span>}
                      </pre>
                    </CardContent>
                  </Card>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Sidebar ── */}
      {activeStage === 'scenes' ? (
        /* Skeleton entity sidebar (read-only reference) */
        <div className="w-72 border-l border-border flex flex-col">
          <div className="px-4 py-4 border-b border-border">
            <h3 className="text-sm font-medium">Story Bible</h3>
            <p className="text-xs text-muted-foreground">{skeleton?.entities?.length ?? 0} entities</p>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {ENTITY_TYPES.filter(t => skeletonByType[t]?.length).map(type => {
              const Icon = TYPE_ICON[type] ?? BookOpen
              const entities = skeletonByType[type]
              return (
                <div key={type}>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">
                    {type}s ({entities.length})
                  </p>
                  <div className="space-y-1">
                    {entities.map(e => (
                      <div key={e.id} className="flex items-start gap-2 px-2 py-1.5 rounded-md">
                        <Icon size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium truncate">{e.name}</p>
                          {e.coreFacts?.purpose && (
                            <p className="text-[10px] text-muted-foreground truncate">{e.coreFacts.purpose}</p>
                          )}
                        </div>
                        <span className="text-[9px] text-muted-foreground/40 shrink-0">{e.id}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {!skeleton?.entities?.length && (
              <p className="text-xs text-muted-foreground italic">No entities in skeleton.</p>
            )}
          </div>
        </div>
      ) : activeStage === 'chapters' ? (
        /* Skeleton entity sidebar (editable) */
        <div className="w-72 border-l border-border flex flex-col">
          <div className="px-4 py-4 border-b border-border flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Story Bible</h3>
              <p className="text-xs text-muted-foreground">
                {skeleton?.entities?.length ?? 0} entities
              </p>
            </div>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={() => { setAddingEntity(true); setEditingEntityId(null); setEntityDraft(BLANK_DRAFT) }}
            >
              <Plus size={14} />
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {addingEntity && (
              <EntityForm onSave={addEntity} onCancel={() => { setAddingEntity(false); setEntityDraft(BLANK_DRAFT) }} />
            )}

            {ENTITY_TYPES.filter(t => skeletonByType[t]?.length).map(type => {
              const Icon = TYPE_ICON[type] ?? BookOpen
              const entities = skeletonByType[type]
              return (
                <div key={type}>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">
                    {type}s ({entities.length})
                  </p>
                  <div className="space-y-1">
                    {entities.map(e => (
                      <div key={e.id}>
                        {editingEntityId === e.id ? (
                          <EntityForm
                            onSave={saveEditEntity}
                            onCancel={() => { setEditingEntityId(null); setEntityDraft(BLANK_DRAFT) }}
                          />
                        ) : (
                          <div
                            className="flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
                            onClick={() => startEditEntity(e)}
                          >
                            <Icon size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-medium truncate">{e.name}</p>
                              {e.coreFacts?.purpose && (
                                <p className="text-[10px] text-muted-foreground truncate">{e.coreFacts.purpose}</p>
                              )}
                            </div>
                            <span className="text-[9px] text-muted-foreground/40 shrink-0 group-hover:text-muted-foreground/80">
                              {e.id}
                            </span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}

            {!skeleton?.entities?.length && !addingEntity && (
              <p className="text-xs text-muted-foreground italic">No entities yet. Run mini-consolidation or add manually.</p>
            )}
          </div>
        </div>
      ) : (
        /* Phase 2 entity ledger sidebar (read-only) */
        <div className="w-72 border-l border-border flex flex-col">
          <div className="px-4 py-4 border-b border-border">
            <h3 className="text-sm font-medium">Entity Ledger</h3>
            <p className="text-xs text-muted-foreground">
              {entityCount > 0 ? `${entityCount} entities` : 'Populated in Phase 2'}
            </p>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {sortedTypes.length === 0 ? (
              ['Characters', 'Locations', 'Factions'].map(type => (
                <div key={type}>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">{type}</p>
                  <Card className="bg-muted/30">
                    <CardContent className="px-3 py-2">
                      <p className="text-xs text-muted-foreground italic">Populated in Phase 2</p>
                    </CardContent>
                  </Card>
                </div>
              ))
            ) : (
              sortedTypes.map(type => {
                const Icon = TYPE_ICON[type] ?? BookOpen
                const entities = byType[type]
                return (
                  <div key={type}>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider py-1">
                      {type}s ({entities.length})
                    </p>
                    <div className="space-y-1">
                      {entities.map(([id, entity]) => (
                        <div key={id} className="flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 transition-colors">
                          <Icon size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                          <div className="min-w-0">
                            <p className="text-xs font-medium truncate">{entity.name}</p>
                            {entity.aliases && entity.aliases.length > 0 && (
                              <p className="text-[10px] text-muted-foreground truncate">
                                {entity.aliases.slice(0, 2).join(', ')}
                              </p>
                            )}
                          </div>
                          <span className="text-[9px] text-muted-foreground/60 ml-auto shrink-0">{id}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
