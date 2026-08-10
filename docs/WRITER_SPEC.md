# Novel AI Pipeline
## Full System Specification · v6.0
*Built for Minisforum AI370 · Ollama · Windows*

---

## 1. System Overview

The Novel AI Pipeline is a locally-hosted application that guides a novel from initial concept through to a fully written, canon-consistent manuscript. It is designed to run on the author's own hardware (Minisforum AI370) but can run entirely on free cloud LLM providers during development and testing, before local hardware is available.

The system is split into three sequential phases:

- **Phase 1 — Bible Generation:** the author and an LLM co-create a North Star document, then an iterative agent loop expands it into a complete Story Bible across four tiers (book → acts → chapters → scenes), with the author approving each completed tier before the next begins.
- **Phase 2 — Research & Entity Completion:** a Research Assistant deepens the Living Bible with verified facts via live web search, and fully fleshes out any placeholder entities left from Phase 1. The author reviews and approves all Phase 2 output before Phase 3 begins.
- **Phase 3 — The Writing Loop:** an autonomous pipeline of Writer → QA → Bible Update that runs scene by scene until the novel is complete, with an optional automatic mode that advances without author intervention when QA passes.

---

## 2. Infrastructure

### 2.1 Hardware

The application runs in three modes, switchable at any time via the Settings page:

- **Cloud mode** — all agents use cloud LLM providers (Google Gemini, OpenRouter). No local hardware required. Intended for development, testing, and use before the AI370 is available.
- **Local mode** — agents use Ollama running on the Minisforum AI370. No data leaves the machine.
- **Hybrid mode** — agents are configured individually. Fast iteration tasks use cloud; prose writing uses local.

> Cloud mode sends your story content to external servers. This is a conscious trade-off: use it freely during development, then migrate sensitive phases to local when the hardware is available.

#### Local Hardware (when available)

| Component | Spec | Role |
|---|---|---|
| AI Server | Minisforum AI370 (Ryzen AI Max+ 395) | Runs all local models |
| Memory | 128 GB LPDDR5x unified | Holds 70B models in full |
| Network | Dual 10GbE + WiFi 7 | LAN access from all devices |
| Form factor | 2U rack-mountable | Clean rack installation |
| Expansion | PCIe x16 | Future discrete GPU option |

### 2.2 Software Stack

| Layer | Tool | Purpose |
|---|---|---|
| Model runtime (local) | Ollama (Windows) | Serves local LLMs via REST API — optional until hardware arrives |
| Interface | Web app (served locally) | Accessible from any browser on the same network |
| Remote access | Tailscale (future) | Secure global access — added when needed, not required at setup |
| Version control | Git | Living Bible versioning per scene and per tier |
| Agent framework | Direct API calls | Single-agent iterative loop — no orchestration framework needed |
| Web search | Integrated search tool | Research assistant live queries |

### 2.3 Model Providers

Two cloud providers are supported, both with live model lists fetched from their APIs. All model selection happens in the Settings page.

**Google Gemini**
- Model list fetched live from the Gemini API at settings load time.
- Free-tier models labelled clearly; availability and rate limits may change.
- API key required — obtained from Google AI Studio (aistudio.google.com).

**OpenRouter**
- Model list fetched live from the OpenRouter API, including real-time pricing.
- Free models badged clearly; the list reflects current availability, not what was free at release.
- API key required — obtained from openrouter.ai.

**Local (Ollama)**
- Model list fetched from the local Ollama instance (localhost:11434).
- No API key required. Available only when Ollama is running and reachable.

| Model | Provider | Recommended for |
|---|---|---|
| Gemini 2.0 Flash (free tier) | Google Gemini | Bible iteration — long context, fast |
| Gemini Pro (free tier, if available) | Google Gemini | Higher-quality bible generation passes |
| Meta Llama 3.3 70B (free) | OpenRouter | Writing, research, QA |
| Mistral 7B (free) | OpenRouter | Fast interactive queries |
| Llama 3.1 70B | Ollama (local) | All agents — primary local model |
| Qwen2.5-Coder 7B | Ollama (local) | Fast queries |

> The recommended column is guidance only. Any model from any provider can be assigned to any agent in Settings.

---

## 3. Settings Page

The Settings page is the control centre for model configuration. It is the first screen shown on first launch and accessible at any time thereafter.

### 3.1 Agent Model Assignment

Each agent has an independent model assignment. The author selects a provider, then a model from that provider's live list.

| Agent | Role | Default suggestion |
|---|---|---|
| Story Architect | North Star creation conversation | Gemini Flash (free) |
| Bible Agent | Tiered bible iteration passes | Gemini Flash (free) — long context |
| Research & Completion Agent | Phase 2 enrichment and entity completion | Llama 3.3 70B via OpenRouter (free) |
| Writer Agent | Scene prose generation | Llama 3.3 70B via OpenRouter (free) |
| QA Agent | Scene quality and consistency checking | Best available model — see note in section 6.4 |
| Bible Updater Agent | Structured bible updates post-scene | Gemini Flash (free) — reliable JSON |

### 3.2 Provider Configuration

- **Google Gemini:** enter API key → app fetches live model list → models labelled as Free or Paid with rate limit notes.
- **OpenRouter:** enter API key → app fetches live model list with real-time pricing → free models badged clearly.
- **Ollama:** enter host URL (default: localhost:11434) → app fetches available local models. Status indicator shows if Ollama is reachable.

### 3.3 Automatic Mode

Automatic mode can be toggled in Settings at any time, including mid-novel. See section 6.5 for full behaviour.

### 3.4 Remote Access (Tailscale)

Tailscale is not required at setup. When the author later wants to access the app from outside the home network, Tailscale can be installed and the device's Tailscale IP entered here. This section is clearly marked as optional and does not block any other functionality.

### 3.5 Tech Stack

The frontend framework, backend language, and database are decisions that must be made before implementation begins. They are not specified here. What the spec constrains: the app must serve a web UI locally, call LLM provider APIs directly, maintain a Git repository for the Living Bible, and run on Windows.

---

## 4. Phase 1 — Bible Generation

Phase 1 produces the complete Story Bible before any prose is written. It has two sub-phases: North Star Creation followed by the Tiered Bible Loop.

### 4.1 Sub-Phase A: North Star Creation

The author has a freeform conversation with the Story Architect agent. The goal is a short, dense document capturing the essential creative intent of the novel. This document is **append-only** once approved: all subsequent agents treat it as a hard constraint, never an input to modify. New directives are appended on top — nothing is deleted or overwritten.

| Property | Value |
|---|---|
| Agent | Story Architect |
| Mode | Interactive conversation |
| Output | `north_star.md` — locked after author approval |

**North Star Contents**
- Genre, tone, and narrative voice
- Core theme and emotional journey — what the reader should feel by the end
- Non-negotiable story beats — the 2–5 events the author knows must happen
- World constraints — hard rules the story must respect
- Protagonist's essential arc — who they are at the start, who they become

> The North Star is intentionally short (1–2 pages). It is the anchor that never changes. The bible grows around it.

### 4.2 Sub-Phase B: Tiered Bible Loop

Once the North Star is locked, the Bible Agent expands it through four tiers in strict sequence. The author approves the completed tier before the next begins — not individual passes. The agent runs autonomously within each tier until it judges the tier complete, then presents the full result for author review.

#### Tier Sequence

| Tier | Question answered | Key outputs |
|---|---|---|
| 1 — Book | What happens in this book? | Overall arc, emotional journey, major turning points |
| 2 — Acts | What happens in each act? | Act entry/exit states, dramatic purpose of each act |
| 3 — Chapters | What happens in each chapter? | Chapter entry/exit states, chapter briefs |
| 4 — Scenes | What happens in each scene? | Scene entry/exit states, scene briefs, foreshadowing placements |

> Lower tiers are never created until the tier above is fully approved. There is no chapter structure until the act structure is locked.

#### Author Interaction Within a Tier

When the agent presents the completed tier, the author can:

- **Approve** — tier is locked, agent descends to the next tier.
- **Inject a directive** — add a creative instruction appended to the North Star, and the agent runs another pass incorporating it.

Example directives at act level:
- *"Add a merchant character who joins the party in Acre and dies of fever in Constantinople — subplot about greed."* The agent creates a ledger entry, integrates the character into relevant act entry/exit states, and logs the change.
- *"The tone of act 2 feels too light — it should feel like things are quietly unravelling."* The agent revises act 2's brief and emotional descriptor.
- *"The protagonist must not know their father is alive until act 3."* The agent audits all character knowledge states up to act 3.

> Directives are appended to `north_star.md` as timestamped blocks. The file is append-only — nothing is deleted. The agent always reads the complete document.

#### Tier Regression

The spec gates forward deliberately: lower tiers are not built until upper tiers are approved. If the author wants to restructure an upper tier after lower tiers have been built, this requires the late-addition cascade tool, which is deferred to a future version. Tier regression is a known need, not an oversight — it is explicitly out of scope for v1 implementation.

### 4.3 The Entity Ledger

The Living Bible maintains a persistent master ledger of every entity in the story — characters, locations, factions, objects, relationships. Entries are never deleted, only updated. An entity introduced in act 1 and referenced in act 5 is the same ledger entry throughout.

#### Entry Structure

- **Core facts** — timeless properties: geography and culture for a location; name, appearance, and fundamental personality for a character. Change rarely and only by explicit edit.
- **Event log** — a chronological, append-only record of everything that happens to this entity, tagged to act and chapter. Examples: city burns (act 2, ch 3); merchant dies of fever (act 3, ch 1); relationship turns hostile (act 1, ch 4).
- **Alias list** — all known references to this entity: proper name, role descriptions, pronouns, nicknames. Used during entity resolution.
- **Lifecycle** — the list of acts and chapters where this entity is active and visible to agents. Dormant entries remain in the ledger but are not surfaced unless requested.

#### Entity Resolution

Before any agent runs for a given unit, a resolution step matches references in the unit brief against the ledger — using the alias list, not raw noun matching.

> **Known hard problem:** alias resolution is non-trivial. "The merchant," "Ibrahim," and "the old man" may all refer to the same ledger entry. The alias list is the intended mechanism, but the reliability of LLM-based matching versus string matching versus other approaches is to be determined through trial and error during implementation. Duplication bugs at this seam are expected and should be monitored.

The author sees a confirmation before any agent run: which entities are existing (with ledger ID and current state) and which are new. This is the human safety net for resolution failures.

#### Event Log Visibility Rules

The event log is chronological. The Writer agent only ever sees backwards — entries up to and including the current chapter.

| Agent | Phase | Event log visibility |
|---|---|---|
| Story Architect / Bible Agent | Phase 1 | Full log including future events — needed to plan a coherent arc |
| Research & Completion Agent | Phase 2 | Full log — adds verified facts and completes placeholder entries |
| Writer Agent | Phase 3 | Present-state view only — events up to current chapter. Cannot foreshadow what it does not know. |
| QA Agent | Phase 3 | Full log including future events — catches contradictions with planned arc |
| Bible Updater Agent | Phase 3 | Full log — appends new events after each approved scene |

### 4.4 Foreshadowing Tracking

Foreshadowing seeds are defined during Phase 1 scene planning and stored in `foreshadowing_brief.json`. Each seed has:

- A unique ID (e.g. `SEED_007`)
- A description of what to plant, written without plot context — the Writer knows what to hint at, not why
- A target planting window (scene range by which the seed should be placed)
- A payoff scene reference (the scene where the seed resolves — not visible to the Writer)
- A status field: `unplanted` → `planted` (set by the Bible Updater, with scene reference)

The Writer receives the foreshadowing brief filtered to seeds that are `unplanted` and due by the current scene. QA checks that seeds due by this scene have been planted, and that no seed references its own payoff. The Bible Updater updates seed statuses after each approved scene.

### 4.5 Chapter and Scene State Structure

Every unit at every tier carries three elements that together form the QA contract for Phase 3:

- **Entry state** — the bible snapshot (active entity states) as the unit opens.
- **Brief** — what happens, the dramatic purpose, the emotional beat.
- **Exit state** — the bible snapshot as the unit closes. Set during Phase 1. Treated as fixed in Phase 3 — it is the destination the Writer must reach, not a document to be updated.

> Entry and exit states reference ledger entities by ID, they do not duplicate them. "Party is in Constantinople (LOC_004), post-fire" — not a copy of the full location entry.

### 4.6 Phase 1 Outputs

- `north_star.md` — append-only creative brief with all author directives in order
- `bible.json` — the complete Living Bible including the entity ledger
- `scene_queue.json` — ordered list of scene briefs with entry/exit states
- `foreshadowing_brief.json` — seeds with IDs, planting windows, payoff references, and statuses
- `narrative_voice.md` — tone, POV, and style guide enforced by QA

---

## 5. Phase 2 — Research & Entity Completion

Phase 2 has two responsibilities: enriching the Living Bible with verified real-world facts, and fully fleshing out any placeholder entities left incomplete during Phase 1. **Phase 3 does not begin until the author has reviewed and approved Phase 2 output.**

| Property | Value |
|---|---|
| Agent | Research & Completion Agent |
| Web search | Enabled — live queries during research |
| Input | `north_star.md` + `bible.json` |
| Output | Enriched `bible.json` with all entities completed, pending author approval |

### 5.1 Research Scope

- Verify historical dates, locations, and terminology
- Add authentic period detail to world entries — food, clothing, currency, travel times
- Check character names for period and cultural authenticity
- Flag any invented facts that contradict known history — for author decision, not silent override

### 5.2 Entity Completion Scope

Any entity introduced as a placeholder — named by role rather than identity — is fully realised in Phase 2. The agent invents and records:

- Full name appropriate to period and culture
- Physical description — age, build, distinguishing features
- Mannerisms and speech patterns
- Backstory sufficient to inform their behaviour in the story
- Relationships to other characters already in the ledger

*Example:* "two priests in the party" becomes Father Aldric (gaunt, precise, haunted by a vow he broke in his youth) and Brother Tomás (round, compulsively generous, uses humour to deflect anything serious). Both receive full ledger entries.

> Entity completion is a creative act within constraints. The agent cannot introduce facts that contradict the North Star or established canon.

### 5.3 Phase 2 Author Approval Gate

When Phase 2 is complete, the author reviews:

- All newly completed entity profiles
- All research additions and flags
- Any contradictions the agent surfaced for author decision

The author approves, edits, or rejects individual entries. Nothing is locked for Phase 3 until the author explicitly signs off on the full Phase 2 output. This is the last point at which the entity list can be cleanly modified before prose writing begins.

---

## 6. Phase 3 — The Writing Loop

Phase 3 runs scene by scene through the scene queue until the novel is complete. It is designed to run autonomously. The author's involvement is optional and configurable.

### 6.1 Context Window Strategy

The two agents have fundamentally different context profiles, and this drives model selection.

**Writer — bounded context by design**

The Writer agent does not receive every previous scene in full. Context is predictable regardless of where the novel is in the queue:

- Scene brief and entry state (references ledger entities by ID — compact)
- Active ledger entities in present-state view (the relevant subset, not the full ledger)
- Foreshadowing brief (unplanted seeds due by this scene)
- Short summaries of immediately preceding scenes for prose continuity (produced by the Bible Updater — see section 6.7)

The ledger is the memory system. Completed scenes do not need to be held in context — their effects are already captured in entity states and the event log. This keeps the Writer's context window bounded as the novel grows.

**QA — unbounded context by necessity**

QA sees everything: all prior scenes, the full bible, the complete ledger including future events, the narrative voice guide. This is deliberate — QA needs the full picture to catch contradictions between what was just written and what is planned for scene 280.

For a long novel, QA context will grow scene by scene and will hit model context limits before the Writer does. This makes **QA model selection the most important configuration decision in Phase 3**. A model with a larger context window, or one that handles long contexts more reliably, should be prioritised for QA over other agents. As the novel grows, QA may need to be reassigned to a more capable model mid-project.

> Context window limits are a real implementation constraint for both agents, but they hit QA first and harder. The summarisation strategy for preceding scenes, the threshold for "active" ledger entities, and the QA context eviction strategy must all be validated against chosen model limits during implementation.

### 6.2 Loop Overview

| Stage | Agent | Input | Output |
|---|---|---|---|
| 1. Write | Writer Agent | Scene brief + entry state + active ledger (present-view) + foreshadowing brief + preceding scene summaries | Scene draft |
| 2. QA | QA Agent | Scene draft + full bible + exit state contract + narrative voice guide + all prior scenes | Pass or fail with notes |
| 3a. Auto-advance (if enabled) | — | QA pass result | Scene committed, next scene begins |
| 3b. Author Approval (if manual) | Author | Scene draft + QA report | Approved, or returned for editing |
| 4. Update | Bible Updater Agent | Approved scene + exit state + current bible | Updated `bible.json` + `bible_diff.json` + scene summary + updated seed statuses + Git commit |

### 6.3 Writer Agent

| Property | Value |
|---|---|
| Sees | Scene brief, entry state, active ledger entities (present-state view — no future events), foreshadowing brief (unplanted seeds due by this scene), summaries of preceding scenes |
| Does NOT see | Full story arc, future scene briefs, future ledger events, seed payoff references |
| Output | Prose scene in established narrative voice |

### 6.4 QA Agent

| Property | Value |
|---|---|
| Sees | Everything — full arc, complete ledger with future events, narrative voice guide, all prior scenes in full |
| Primary check | Does the prose produce the planned exit state? Character knowledge, location, relationships, planted seeds — all verified against the exit state contract. |
| Secondary checks | Canon consistency, narrative voice and tone, pacing, foreshadowing placement (seeds due by this scene marked as planted?), contradictions with future planned events |
| Attempt 1 | Standard pass — QA checks scene, returns pass or fail with notes |
| Attempt 2 | Negative constraint injection — summary of what failed in attempt 1 is prepended to the Writer's prompt as a hard constraint list |
| Attempt 3 | Always escalates to author, regardless of automatic mode setting |

> The exit state is fixed — set in Phase 1, it is the destination the Writer must reach. QA does not renegotiate it; it verifies arrival.

> **Model selection note:** QA carries the largest and fastest-growing context of any agent in the system. Prioritise context window size and long-context reliability when choosing the QA model. As the novel grows, this may mean reassigning QA to a more capable model mid-project. See section 6.1.

### 6.5 Automatic Mode

Automatic mode can be enabled or disabled in Settings at any time, including mid-novel.

- **Enabled:** if QA passes on attempt 1 or 2, the scene is committed and the next scene begins without author involvement. The pipeline runs unattended — overnight if desired.
- **Disabled:** every QA-passed scene waits for explicit author approval before proceeding.

Automatic mode always pauses and alerts the author when:
- QA fails three times on the same scene (attempt 3 always escalates, regardless of mode)
- The Bible Updater flags a contradiction it cannot resolve automatically
- The pipeline reaches the end of the scene queue

> Automatic mode does not reduce quality — QA standards are identical regardless of whether a human is watching. It removes the approval step in the happy path only.

### 6.6 Author Approval (Manual Mode)

When manual mode is active, after QA passes the author sees:
- The scene draft
- The QA report — what was checked and what passed
- All revision attempts if the scene was escalated

The author can:
- **Approve** — scene proceeds to Bible Update unchanged.
- **Reject with notes** — Writer gets one final attempt with author guidance added to the prompt.
- **Edit directly** — if the Writer's final attempt still fails, or at any point the author prefers to take over, an inline text editor opens on the Writing Loop view. The author edits the scene draft in place and approves the result.

In all cases — Writer-generated, revised, or author-edited — the approved scene passes through the Bible Updater before being committed. The Bible Updater must run to keep the ledger consistent. The scene's provenance (writer-generated, revised, or author-edited) is recorded in `scenes/NNN_meta.json`.

### 6.7 Bible Updater Agent

The Bible Updater runs after every approved scene, regardless of how the scene was produced.

| Property | Value |
|---|---|
| Input | Approved scene + exit state (as reference) + current `bible.json` |
| Output | Updated `bible.json` + `bible_diff.json` + `scenes/NNN_summary.txt` + updated seed statuses in `foreshadowing_brief.json` + Git commit |

**Scene summary (`scenes/NNN_summary.txt`)** is a short prose summary of the approved scene, produced by the Bible Updater immediately after approval. This is the input the Writer uses for preceding scene context in subsequent scenes — not the full prose. This keeps the Writer's context bounded while preserving narrative continuity.

### 6.8 Git Commit Structure

```
bible.json                ← updated Living Bible
bible_diff.json           ← machine-readable record of what changed and why
foreshadowing_brief.json  ← updated seed statuses
scenes/NNN.txt            ← approved scene prose
scenes/NNN_summary.txt    ← short summary for Writer context in future scenes
scenes/NNN_meta.json      ← QA attempts, author notes, provenance, seeds used

Scene 003 approved [author-edited]
Characters updated: Mary (CHAR_001), Hamid (CHAR_012)
Locations: Constantinople (LOC_004) — burn event appended
Seeds planted: SEED_003, SEED_007 | Seeds due and unplanted: 0
Threads opened: 3 | Threads resolved: 1
Contradictions flagged: 0
```

---

## 7. User Interface

The application is a web app served locally, accessible from any browser on the same network. It has six main views:

| View | Purpose |
|---|---|
| Settings | Model provider configuration, API keys, agent assignment, automatic mode toggle, optional Tailscale setup |
| North Star | Phase 1A — conversation interface to create and lock the North Star document |
| Bible Workshop | Phase 1B — tiered bible loop; shows completed tier output for author review, author injection panel, entity ledger sidebar, diff from previous pass |
| Bible Viewer | Read-only view of current `bible.json` with search, filter, and ledger entity lookup including alias list |
| Writing Loop | Active scene display with entry/exit state, QA status, automatic mode indicator, inline editor for direct author edits, approval controls |
| History | Git log visualiser — browse all scenes and bible states by commit |

> Settings is the first screen shown on first launch. The app does not proceed to any other view until at least one agent has a model assigned.

---

## 8. Export

- Plain text — all approved scenes concatenated in order
- Markdown — formatted with scene headings and chapter breaks
- DOCX — formatted Word document ready for submission or editing
- Living Bible — full `bible.json` including entity ledger as a readable document

> The Living Bible export (JSON → formatted document) is non-trivial to implement well. It should be treated as a separate workstream, not a one-liner.

---

## 9. Future Extensions

| Extension | Description |
|---|---|
| Tailscale remote access | Secure access from outside the home network — phone, tablet, or laptop while travelling |
| Late-addition cascade tool | Introduce a new entity or plot element after lower tiers are already built, with controlled tier-by-tier propagation downward |
| Tier regression | Restructure an upper tier after lower tiers have been built. Depends on the cascade tool. |
| Multi-novel support | Separate projects, each with own North Star, bible, ledger, and Git repo |
| Shared entity ledgers | Reuse a world ledger across multiple novels set in the same universe |
| Co-author mode | Second user with their own approval rights and directive history |
| Editor pass | Final prose quality sweep before export |
| Audio export | TTS narration of completed chapters |
| Discrete GPU | Add NVIDIA card via PCIe x16 for faster 70B local inference |

---

## 10. Summary

The Novel AI Pipeline v6.0 guides a novel from first idea to completed manuscript. It runs on free cloud LLMs from day one and migrates to local hardware when available, with no changes to the application.

**Key design principles:**

- **Cloud-first, local-ready** — works entirely on free cloud models during development; local hardware is additive, not required.
- **Settings is the foundation** — every agent has an independently configurable model. Switch providers without touching code.
- **The North Star is append-only** — all agents treat it as a hard constraint. Directives stack on top; nothing is deleted or overwritten.
- **The bible grows tier by tier** — book, then acts, then chapters, then scenes. No tier begins until the one above is approved.
- **The author sees completed tiers, not individual passes** — launch the tier, come back, review the result.
- **The entity ledger is the single source of truth** — never duplicated, never deleted, append-only event log, alias list per entity.
- **Entity resolution is a known hard problem** — alias matching is non-trivial; the alias list is the mechanism, reliability is to be proven through implementation.
- **The Writer only sees backwards** — it cannot foreshadow what it does not know. QA sees the full future.
- **Writer context is bounded by design; QA context is unbounded by necessity** — the ledger is the Writer's memory system. QA needs everything and will hit model limits first. QA model selection matters most.
- **Every unit has a fixed exit state** — set in Phase 1, verified in Phase 3. Not renegotiated.
- **Foreshadowing is tracked mechanically** — seeds have IDs, planting windows, and statuses. QA checks against them; payoff references are hidden from the Writer.
- **QA escalates at attempt 3, always** — attempt 2 gets negative constraint injection; attempt 3 goes to the author regardless of automatic mode.
- **Author edits flow through the Bible Updater** — whether the scene was writer-generated or author-edited, the ledger always stays consistent.
- **Automatic mode lets the pipeline run unattended** — QA passes, the story advances. The author wakes to finished scenes.
- **The system is built to grow** — more novels, more users, better hardware, all additive.