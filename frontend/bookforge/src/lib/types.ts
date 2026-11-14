export type Status = 'pending' | 'drafted' | 'checked' | 'accepted' | 'stale' | 'flagged'

export interface Layer { name: string; status: Status; version: number; note: string | null; checkpoint: string | null }

/** What a running job is doing now (filled in by the pipeline; see platform/bookforge/bookforge/activity.py). */
export interface JobActivity {
  layer?: string | null; scene?: string | null; step?: string | null
  calls?: number; scenes_done?: number
  prompt_tokens?: number; completion_tokens?: number  // reported by the model server; absent when it reports none
  call_started?: string; call_label?: string; call_role?: string; last_call_finished?: string
}

export interface Job {
  id: string; series: string; book: string; kind: string
  status: 'running' | 'done' | 'failed' | 'interrupted' | 'cancelled'
  cancel_requested: boolean
  activity?: JobActivity
  started: string; finished: string | null
  params: Record<string, unknown>; result: Record<string, any> | null; error: string | null
}

export interface BookStatus {
  series: string; book: string; title: string; server_time?: string
  layers: Layer[]
  checkpoints: Record<string, 'pending' | 'waiting' | 'approved'>
  scenes: Record<string, number> & { total: number }
  pending_changes: number
  pending_needs: number
  manuscript: boolean
  job: Job | null
  resume_text?: string
  planned_words?: { low: number; high: number; scenes: number; chapters: number } | null
}

export interface SeriesInfo { name: string; books: string[]; titles: Record<string, string>; busy: Job | null }

export interface SceneRow { id: string; chapter: string; purpose: string; status: Status; version: number; note: string | null; words: number }

export interface TreeScene { id: string; purpose: string; status: Status; note: string | null }
export interface TreeChapter { id: string; title: string; tension: number; scenes: TreeScene[] }
export interface TreeAct { id: string; title: string; chapters: TreeChapter[] }

export interface ChangeRequest {
  id: string; status: 'pending' | 'applied' | 'rejected' | 'dismissed'; proposed_by: string; track: string; entity: string
  reason: string; planned: string; observed: string; evidence: string; affects: string[]
  scope: 'within_chapter' | 'later_chapters'; decided_by: string | null; fixed: boolean
}

export type Stance = 'ground' | 'extrapolate' | 'bend' | 'invent'

/** Something the story needs to know or decide. A rule, assumption or deviation waits for the author while 'proposed'. */
export interface Need {
  id: string; scope: 'series' | 'book'; layer: string; question: string; stance: Stance
  reason: string; rule: string; query: string; context: string; sensitive: boolean
  status: 'proposed' | 'approved' | 'rejected'; fact_ids: string[]; decided_by: string
  applies_to: string[]  // chapter or scene ids; empty = the whole book
}

export interface SceneDetail {
  plan: { id: string; chapter: string; purpose: string; pov: string; setting: string; characters: string[]; beats: string[] }
  status: Status; version: number; note: string | null
  text: string | null; summary: string | null
  review: Review | null
  findings: SceneFindings
  critic_min_score?: number
  reasons?: FlagReason[]
  rubric?: Record<string, string>
  drafts: Record<string, string>
  change_requests: ChangeRequest[]
}

/** What the author said about this scene's findings: false alarms and instructions for the writer. */
export interface FlagReason { key: string; kind: 'mechanical' | 'continuity' | 'critic'; message: string; accepted: boolean; note: string }
export interface SceneFindings { dismissed: string[]; instructions: Record<string, string>; accepted?: Record<string, { label: string; note: string }> }

export interface CriticReview { scores: Record<string, number>; weakest?: { criterion: string; quote: string; issue: string }[]; beats?: { beat: number; verdict: 'shown' | 'thin' | 'missing' | 'out_of_order'; note: string }[]; error?: string | null }

export interface Review {
  chosen?: string; source?: string; blocking?: string[]
  judge?: { wins: Record<string, number>; pairs: { a: string; b: string; run1: string; run2: string; winner: string | null }[]; error?: string | null } | null
  critic?: CriticReview | null
  first_attempt_critic?: CriticReview | null
  rewrote_with_critic_notes?: boolean
  accepted_reasons?: Record<string, { label: string; note: string }>
  continuity?: { questions: number; flags: { question: string; evidence: string; confidence?: number; fact_says?: string; text_says?: string }[]; unsure: { question: string; answer: string; confidence: number; evidence?: string; confirmed?: boolean; fact_says?: string; text_says?: string }[] } | null
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

export interface Rule {
  id: string; type: 'banned_phrase' | 'style_rule' | 'hard_constraint' | 'character_voice'; text: string; example: string
  scope: 'series' | 'book' | 'character' | 'scene'; target: string; severity: 'block' | 'warn' | 'note'; phrase: string; enabled: boolean
}
export interface RuleStat { id: string; applicable: number; written: number; fired: number; hits: { scene: string; what: string }[]; measured: boolean }
export interface RuleHealth { rule: string; problem: string; detail: string }
export interface RuleTest { rule: string; total_hits: number; scenes: { scene: string; applies: boolean; hits: string[]; error: string | null }[] }

export interface BriefingPreview { scene: string; tokens: number; budget: number; trimmed: string[]; sections: { heading: string; tokens: number; text: string }[] }
export interface XrayResult {
  scene: string; findings: { severity: 'problem' | 'warn' | 'info'; kind: string; message: string }[]
  beats: { n: number; beat: string; happens: boolean; evidence: string }[] | null; beats_error: string | null
  diagnosis: { cause: 'missing_input' | 'weak_prompt' | 'model_limit' | 'none'; reasons: string[] }
}

export interface PromptInfo { name: string; slots: string[]; overridden: boolean; words: number }
export interface PromptDetail { name: string; slots: string[]; default: string; override: string | null; effective: string; diff: string }

export interface ExperimentSummary {
  name: string; template: string; created: string; promoted: boolean; benchmarks: number
  judge: { a: number; b: number; tie: number }; yours: { a: number; b: number; tie: number; of: number }
}
export interface ExperimentView extends Omit<ExperimentSummary, 'judge'> {
  judge: ExperimentSummary['judge'] | null
  diff: string; warnings: string[]
  pairs: { id: string; first: string; second: string; voted: boolean; vote: 'a' | 'b' | 'tie' | null; first_is?: 'a' | 'b'; second_is?: 'a' | 'b'; judge?: string }[]
}

export interface CalibrationReport {
  scenes: { scene: string; yours: Record<string, number>; critic: Record<string, number> | null }[]
  criteria: Record<string, { n: number; mean_abs_diff: number; bias: number; within_one: number } | null>
  compared: number; ranking_disagreements: number; needs_recalibration: boolean; advice: string
}

export interface ArcView {
  tension: { chapters: { id: string; title: string; act: string; tension: number; scenes: number; written: number }[]; notes: string[] }
  threads: { scenes: string[]; unpaid: number; threads: { id: string; note: string; setup: string; payoff: string; problem: string | null; setup_at: number | null; payoff_at: number | null }[] }
  milestones: { chapters: { id: string; title: string }[]; items: { label: string; chapter: string; title: string; at: number | null; basis: 'plan' | 'written' }[]; generated_at: string; current: boolean }
}
export interface TensionPreview { chapter: string; from: number; to: number; consequence: string; applied: boolean }

export interface DocumentInfo { key: string; title: string; group: string; kind: 'markdown' | 'yaml' | 'text'; exists: boolean; words: number; editable: boolean }
export interface DocumentFull { key: string; title: string; group: string; kind: 'markdown' | 'yaml' | 'text'; exists: boolean; text: string; truncated: boolean; editable: boolean }

export interface TrashItem { name: string; series: string; deleted: string | null; books: string[] }

export interface Finding { stage: string; code: string; severity: 'hard' | 'soft'; message: string; items: string[]; evidence: string[]; accepted?: boolean }
export interface StageChecks { stage: string; summary: { hard: number; soft: number; codes: string[] }; findings: Finding[]; capacity?: Record<string, any> }
export interface AcceptedFinding { fingerprint: string; stage: string; code: string; items: string[]; message: string; at: string }
export interface ValidationResult { stages: Record<'ledger' | 'acts' | 'chapters' | 'scenes' | 'prose', StageChecks>; accepted?: AcceptedFinding[] }
export interface LedgerEvent { id: string; text: string; once_only: boolean; kind: string; weight: number; ending: boolean; source: string; parent: string; pays_off: string }
export interface LedgerQuestion { id: string; question: string; why: string; options: string[]; answer: string; status: 'open' | 'answered' | 'dismissed'; applied: boolean }
export interface LedgerView { events: LedgerEvent[]; questions: LedgerQuestion[]; thin: boolean; capacity: Record<string, any>; revision: number }

export interface StyleSuggestion {
  at: string; file: string; genre: string; subgenres: string[]; intended_style: string; web: boolean
  verified_titles: { title: string; author: string; why: string; sources: string[] }[]; unchecked_titles: string[]
  sources: { url: string; title: string }[]; problems: string[]; words: number
}
export interface StyleState { has_guide: boolean; suggestion: StyleSuggestion | null }
