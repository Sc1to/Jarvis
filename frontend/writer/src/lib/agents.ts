export type Provider = 'gemini' | 'openrouter' | 'anthropic' | 'openai' | 'ollama' | ''

export interface AgentAssignment { provider: Provider; model: string }

export interface AgentMeta { key: string; label: string; description: string; hint?: string }

/** Every LLM "role" the writer app assigns a model to. Shared between the global
 * Settings page and per-series model override panel — one source of truth. */
export const AGENTS: AgentMeta[] = [
  { key: 'story_architect',  label: 'Story Architect',            description: 'North Star creation conversation' },
  { key: 'bible_agent',      label: 'Bible Agent',                description: 'Tiered bible iteration passes',     hint: 'Long context recommended' },
  { key: 'research_agent',   label: 'Research & Completion',      description: 'Phase 2 enrichment and entity completion' },
  { key: 'writer_agent',     label: 'Writer Agent',               description: 'Scene prose generation' },
  { key: 'qa_agent',         label: 'QA Agent',                   description: 'Scene quality and consistency checking', hint: 'Largest context window available — see spec §6.1' },
  { key: 'bible_updater',    label: 'Bible Updater',              description: 'Structured bible updates post-scene', hint: 'Reliable JSON output recommended' },
  { key: 'beat_generator',   label: 'Beat Generator',             description: "Breaks a scene's brief into a numbered beat list before beat-based prose expansion (the \"Beats\" mode in the Writing Loop scene rewrite panel)", hint: 'Falls back to Writer Agent if unset' },
  { key: 'beat_expander',    label: 'Beat Expander',              description: 'Expands each beat from the Beat Generator into full prose, one beat at a time, during a Beats-mode rewrite', hint: 'Falls back to Writer Agent if unset' },
  { key: 'text_op_expand',   label: 'Text Op — Expand',           description: 'Powers the Expand button in the prose editor toolbar (lengthens the selected scene prose in place)', hint: 'Falls back to Writer Agent if unset' },
  { key: 'text_op_rephrase', label: 'Text Op — Rephrase / Tighten', description: 'Powers the Rephrase and Tighten buttons in the prose editor, and the automatic over-length trim applied after a scene is written', hint: 'Falls back to Writer Agent if unset' },
  { key: 'text_op_notes',    label: 'Text Op — Editorial Notes',  description: 'Powers the Notes button in the prose editor — editorial feedback on the current draft without changing it', hint: 'Falls back to QA Agent if unset' },
]
