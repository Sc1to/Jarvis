export type Status = 'pending' | 'drafted' | 'checked' | 'accepted' | 'stale' | 'flagged'

export interface Layer { name: string; status: Status; version: number; note: string | null; checkpoint: string | null }

export interface Job {
  id: string; series: string; book: string; kind: string
  status: 'running' | 'done' | 'failed' | 'interrupted'
  started: string; finished: string | null
  params: Record<string, unknown>; result: Record<string, any> | null; error: string | null
}

export interface BookStatus {
  series: string; book: string
  layers: Layer[]
  checkpoints: Record<string, 'pending' | 'waiting' | 'approved'>
  scenes: Record<string, number> & { total: number }
  pending_changes: number
  manuscript: boolean
  job: Job | null
}

export interface SeriesInfo { name: string; books: string[]; busy: Job | null }

export interface SceneRow { id: string; chapter: string; purpose: string; status: Status; version: number; note: string | null; words: number }

export interface TreeScene { id: string; purpose: string; status: Status; note: string | null }
export interface TreeChapter { id: string; title: string; tension: number; scenes: TreeScene[] }
export interface TreeAct { id: string; title: string; chapters: TreeChapter[] }

export interface ChangeRequest {
  id: string; status: 'pending' | 'applied' | 'rejected'; proposed_by: string; track: string; entity: string
  reason: string; planned: string; observed: string; evidence: string; affects: string[]
  scope: 'within_chapter' | 'later_chapters'; decided_by: string | null; fixed: boolean
}

export interface SceneDetail {
  plan: { id: string; chapter: string; purpose: string; pov: string; setting: string; characters: string[]; beats: string[] }
  status: Status; version: number; note: string | null
  text: string | null; summary: string | null
  review: Review | null
  drafts: Record<string, string>
  change_requests: ChangeRequest[]
}

export interface Review {
  chosen?: string; source?: string; blocking?: string[]
  judge?: { wins: Record<string, number>; pairs: { a: string; b: string; run1: string; run2: string; winner: string | null }[]; error?: string | null } | null
  critic?: { scores: Record<string, number>; weakest?: { criterion: string; quote: string; issue: string }[]; error?: string | null } | null
  continuity?: { questions: number; flags: { question: string; evidence: string }[]; unsure: { question: string; answer: string; confidence: number }[] } | null
  rounds?: { round: number; mechanical_blocking: string[]; continuity_flags: string[]; critic_lowest: number | null; revisions: { mode: string; before: string; after?: string }[] }[]
  mechanical?: Record<string, { score: number; issues: { severity: string; message: string }[] }>
  extraction?: { gaps: { track: string; planned: string; observed: string }[] }
  stale_fixes?: { at: string; action: string; why: string }[]
}

export interface StaleReport {
  scenes: { scene: string; level: string; reasons: string[] }[]
  plan: { id: string; kind: string; reason: string }[]
  problems: string[]
}

export interface TrackData {
  scenes: { id: string; chapter: string }[]
  chapters: string[]
  tracks: {
    id: string; entity: string; entity_name: string; kind: string; version: number
    plan: { from: string; value: string; must_show: boolean }[]
    observed: { at: string; value: string; matches_plan: boolean | null; evidence: string }[]
  }[]
}

export interface Fact { id: string; claim: string; url: string; title: string; fetched: string; quote: string; layer: string; question: string; sensitive: boolean; used_in: string[] }
