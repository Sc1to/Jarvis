# Plan: no structural errors, and every content error comes with a one-tap fix (approved 2026-11-17)

Branch `ccr-62191c26-s69gvc`. Backend `platform/bookforge/bookforge/`, frontend `frontend/bookforge/src/`. One PR per phase, tests with each, merge on green (full local suite; the repo has no CI).

## Context
On the first real b2 run, every run showed a new kind of finding. We fixed them one at a time (repairs, narrow rewrites, warnings) and the next run showed another. The research for this plan shows why:

- **The model still writes structure the tool already knows.** Scene events, act events, track `from` positions, `chapter_count`, `turning_point_event`, derived-event ids, scene days, ending/decision flags. Each field has its own check and its own repair, spread over about 14 repair calls and about 10 silent normalisers, with no single entry point per layer. A slip in any of them is a finding.
- **Content findings reach you as open text boxes.** Of ~110 finding codes, the Inbox can suggest something for only 2 kinds (`sentence_not_covered`, world-fact questions). Everything else is "Your instruction for the next run", with no suggestion.
- Evidence from the b2 call log: the model's own first reply copied events already told, the tool's error cascade made it write the old format, and one correction round could not fix a retold chapter.

You asked for two rules, and this plan makes them the architecture:
- **(a) Structural errors do not exist.** The model never writes anything the tool can derive. If a structural problem still appears, it is a tool bug, not an item for you.
- **(b) Content errors always come with a recommended, executable fix.** No empty text boxes. One tap applies it.

You decided: **per book, Ask me (default) or Apply recommended** (Apply recommended applies the tool's fix on its own, lists it in the morning report, with Undo).

## Principles
1. **Derive, don't ask.** A field with exactly one right answer is computed by the tool (by construction), never written by the model and then checked.
2. **A finding is a remedy waiting to run.** Each finding code is registered with a class and its remedies; a code with no registered remedy fails a test.
3. **Content never stops a run.** Wording, rating and repeat findings are collected, fixed or offered, and only block the checkpoint approval. Only a story DECISION at the ledger stage still stops (as now), because later layers would be built on it.
4. **Everything applied is undoable** (reuse `versions.keep`) and re-checked.

## Part A: structural errors cannot occur

### A0. One normalisation entry point per layer, and a tool-bug path
- New `bookforge/bible/normalize.py` with `normalize_acts / chapters / scenes / ledger / cast(raw, context) -> (plain data, notes)`. It composes what exists today (`partition.assign`, `repair.*`, `normalize_derived`, `adopt_places`, id assignment, track remapping) so each layer has ONE pipeline; `parse_*` in `bible/validate.py` call only it. Adopted and cached files go through the same entry (today adopted files bypass repair).
- **Invariant:** after `normalize_*`, no structural check can fire. If one does, it is a tool bug: it is not an Inbox item and never sent back to the model as a wall of errors. The run writes a diagnostics bundle (`books/<b>/diagnostics/<stamp>.json`: the raw reply, the normalised data, the failing check) and retries once from the by-construction path; the page shows "Internal problem, diagnostics saved" with the file path. This also ends the "send me files" round trips.

### A1. Convert what the model still writes into things the tool derives
Ranked by value (from the structure map), each with the checks that become impossible:

| # | Field today | Replacement | Checks and repairs that go away |
|---|---|---|---|
| 1 | Scene `events` | Scenes name `starts_with` like chapters; reuse `partition.assign` on `chapter.events_covered`; a scene with no `starts_with` carries on the previous one | `scene_event_not_in_chapter`, `chapter_event_not_in_scenes`, `once_only_repeated` (scenes), `repair_scenes` (except renumbering) |
| 2 | Act `events` list | Acts name `starts_with` (same partition); ending event forced into the last act | `event_in_two_acts`, `event_in_no_act`, `acts_out_of_order`, `unknown_event` (acts), `resolution_not_in_last_act`, all of `repair_acts` |
| 3 | Act `chapter_count`, `sizing_reason`, `turning_point_event` | Tool computes count from `act_weight`, writes the `[computed: ...]` note, sets the turning point to the act's last event (last act: decision or ending) | `acts_differ_from_capacity`, `sizing_reason_mismatch`, `implausible_chapter_count`, `chapter_count_exceeds_capacity`, `turning_point_without_event`, `turning_point_not_in_act`, `final_turning_point_is_transition`, `repair_sizing`, the `override:` convention |
| 4 | Track `from` positions (chapters and scenes) | States nest under the chapter (`states: [{track, value, must_show}]`); scenes pin by track id (`shows: [...]`); tool pivots to tracks with `from` set | all `from` spelling / not-allowed / used-twice problems, `_remap_tracks`, `_apply_refinement` guards, must_show-not-pinned |
| 5 | Chapter `events_continued` | `continues: true`; tool takes the previous chapter's last event | `continued_event_not_begun`, other-act case |
| 6 | Derived-event ids, parent, `after`, weight, kind | Model gives only `text`, attached to a chapter; tool sets the rest | `derived_not_minor`, `derived_not_after_parent`, `derived_without_parent`, id collision |
| 7 | Scene `day` (absolute) | `days_later` deltas; absolute `day` only for a flashback | `story_day_backwards`, in-parse and `validate_bible` day problems |
| 8 | Ids: act, chapter, scene (non-ledger mode too), cast entity and rule, ledger event, question | Never asked for; assigned by position / slugified from `name` | all id-mismatch problems, `duplicate_event_id` |
| 9 | Ledger `ending: true`, `decision: true`, setup/payoff `kind` | Top-level `ending: eN`, `decision: eN`; `pays_off` alone sets both kinds | `several_endings`, `several_decisions`, `no_resolution`, `payoff_target_not_setup`, `payoff_without_setup` |
| 10 | pov / setting / characters / research ids | Tool resolves an id, a name or a near-miss to a cast id; attaches the research ids it injected | "not in the cast", wrong-kind, unknown research id |

Also: structural codes with no remedy today (`event_cycle`, `resolution_not_final_paragraph`, `synopsis_not_covered`, `weights_flat`, `continued...`) are each either made impossible by the rows above or turned into a DECISION item with options (Part B).

### A2. The guarantee, as a test
Add `hypothesis` (dev requirement). Property tests per layer: generate a valid plan, apply random model-style mutations (wrong ids, duplicates, missing starts, foreign events, reordering, extra fields, both old and new shape), and assert `normalize_*` output has zero structural findings, covers each event once, and is idempotent. A registry test (B1) asserts every structural code is either marked "impossible by construction" or has a normaliser.

### A3. Prompts and the weak model
Prompts get shorter (sizing paragraphs, id instructions, event lists go away). Wherever the model must pick an event, the prompt lists the valid ids (done for chapters; same for scenes and acts). The correction message for a bad pick returns only that problem (done for chapters), never follow-on errors.

## Part B: content errors always carry an executable recommendation

### B1. Finding registry (`bookforge/remedies/registry.py`)
`FindingSpec(code, stage, klass, remedies)`, where class is STRUCTURAL (Part A), WORDING, RATING or DECISION, and `Remedy(id, label, effect, kind, build(finding, project) -> Action, rank)`. Exactly one remedy is `recommended`. A test enumerates every code emitted by `hard()/soft()` plus parser problem kinds and audit types (the catalog is already built) and fails on any code without a registered class, or a content code without a recommended remedy.

### B2. Actions and executor (`bookforge/remedies/actions.py`)
Executable, undoable, re-checked steps built from existing code:

| Action | Reuses |
|---|---|
| `rewrite_text(chapter\|scene, fields, forbidden)` | `qc/overreach_fix.py` (`fix`, `fix_retells`, `_check_*`), `ask_json` |
| `rerate_tension(ids)` | `overreach_fix.fix_tension` |
| `rewrite_passage(scene, flags)` | `prose_repair.fix`, `qc/revise.revise_text` |
| `merge_chapters / drop_chapter / split_chapter` | `partition` (re-cut starts), `repair._remap_tracks`, `versions.keep` |
| `set_pov(unit, id)`, `rewrite_to_follow_pov` | `validate` entity checks |
| `add_cast_entity(name, kind, facts)`, `replace_name(old, id)` | `cast.add`, `cast` rename, `canon` |
| `waive / attach / widen / new_event` | `resolve.py`, `answers.py` |
| `accept(finding)` | `accepted.accept` |

The executor applies one option, snapshots first (`versions.keep`), re-runs only the affected check, records the outcome in `decisions.jsonl` (existing per-outcome stats and demotion keep working) and a "Fixed" line in healing.

### B3. Recommended options per content finding
Each item shows the options with the recommended one preselected. Initial table for the codes that reach you most (the registry covers all of them):

| Finding | Recommended | Alternatives |
|---|---|---|
| `chapter_retells_event`, `event_repeated`, `chapter_replans_chapter` | Rewrite the later chapter's purpose and summary (`rewrite_text`) | Merge the two chapters; drop the later chapter (if its events are told elsewhere); accept as a deliberate echo |
| `end_state_overreach` | Rewrite the end_state and summary | Move the event into this chapter; accept |
| `flat_tension` | Rate the stretch again | Accept |
| `pov_not_in_text` / `pov_not_main` | Change the POV to the character the text follows | Rewrite the text to follow the POV; accept |
| `unknown_name` | Add as a new cast entry (if named 2+ times), else replace with the closest cast name | Ignore |
| `scene_retells_event`, `scene_repeats_scene` | Rewrite the later scene's beats | Merge the scenes; accept |
| `implausible_scene_count`, `chapter_overloaded` | Split / merge scenes to the count the weights imply | Move an event to a neighbouring chapter; accept |
| `action_pattern_repeated`, `research_in_beats` | Rewrite the named beats | Accept |
| `state_regression`, `two_places_at_once` | Add the missing `cause` / correct the location in the earlier scene (shown as a diff) | Accept |
| `sentences_repeated`, `chapter_opens_with_previous_ending` | Rewrite the passage (`prose_repair`) | Accept |
| `sentence_not_covered` (existing) | Existing proposal (widen / attach / waive / new_event) | unchanged |
| Audit questions: `contradiction`, `cast_conflict`, `condition_order`, `unknown_name`, `unestablished_object`, `motive_gap` | The tool's best option from the question's `options` (marked recommended; today they exist but none is preferred) | the other options |

### B4. Inbox, API and UI (390px, light and dark)
- Every item: radio list of options, recommended preselected, a one-line effect preview, one **Apply** button. The existing proposal/accepted/undo machinery (`resolve.py`, `inbox.py`, `api_inbox.py`) carries the rest.
- **No empty text boxes.** "Something else..." opens a box prefilled with the recommended instruction; there is no "Your instruction for the next run" any more.
- **Apply recommended to all (N)** for the items on screen.
- `POST .../inbox/apply {item, option}`; the CLI gets the same through `ops.py`.
- **Per-book switch** (extends `answers.yaml: mode`): *Ask me* (default) or *Apply recommended*. In Apply recommended an overnight run applies every recommended content fix itself, lists each in the morning report ("The tool's decisions") and in a "Fixed automatically" group with Undo. Content findings never stop a layer; they block only the checkpoint approval.

### B5. Severity policy
Retire the hard/soft split for wording, rating and repeat codes: they are `content` items with options (resolved, offered, or accepted). Only structural bugs (A0) and ledger-stage DECISIONS stop a stage. The earlier `warn_unfixable` demotion is superseded: an item the tool cannot fix still has options (accept is always one).

## Phases (each a PR with tests, merged on green)
1. **Foundation:** `normalize.py` entry points (behaviour-preserving), diagnostics bundle + tool-bug path, finding registry with the completeness test (no behaviour change).
2. **Scenes by construction** (A1 #1, #7 and scene ids). Biggest structural win for the least new machinery.
3. **Acts by construction** (A1 #2, #3).
4. **Tracks nested** (A1 #4), chapters `continues` and derived events (A1 #5, #6).
5. **Ids, ledger flags, pov/setting resolver** (A1 #8 to #10) and the Hypothesis property tests for every layer.
6. **Remedy executor + chapter-level remedies** (B2, the top rows of B3), Inbox options UI (B4).
7. **Remaining remedies** (scene, name, POV, state, audit-question recommendations) so the registry test passes with no gaps.
8. **Apply recommended mode,** morning-report section, Undo, retire the instruction box.
9. **b2 calibration:** re-plan b2 under the new formats (earlier versions are kept, nothing is deleted), compare what the tool recommended with what you chose, tune the recommendations from the recorded outcomes.

## Critical files
`bible/validate.py` (parsers become thin), `bible/repair.py` and `bible/partition.py` (folded into `bible/normalize.py`), `bible/models.py`, `prompts/{acts_ledger,chapters_ledger,scenes_ledger,ledger,cast}.md`, `layers/structure.py` (`get_piece`, `_book_*_checks`, `_resized`), `layers/ledger.py`, `validators/*.py` (findings gain a `klass` and remedy link), `qc/overreach_fix.py` and `prose_repair.py` (become actions), `resolve.py`, `inbox.py`, `api_inbox.py`, `ops.py`, `answers.py`, `healing.py`, `versions.py`, `frontend/bookforge/src/pages/InboxItems.tsx`.

## Reuse (do not rewrite)
`partition.assign/act_order` (generalised to acts and scenes), `repair._remap_tracks`, `normalize_derived`, `adopt_places`, `act_capacity/act_weight` (`validators/ledger.py`), `qc/overreach_fix.py` fixers, `prose_repair.fix`, `qc/revise.revise_text`, `resolve.propose_*`, `answers.py` modes and demotion, `versions.keep`, `healing.py`, `cast.py`, `accepted.py`, the existing 390px screenshot scripts in the scratchpad.

## Verification
- `cd platform/bookforge && venv/bin/pytest -q` after each phase (now 1319 passed, 2 skipped), plus the new property tests and the registry test.
- `python -m bookforge suite` (known-bad fixtures) must still catch every known-bad case, now as options with a recommendation instead of a bare error.
- Fuzz check per layer: 1000 mutated replies, zero structural findings, idempotent.
- Frontend `npm run build`, 390px screenshots (light and dark) of an item with options, Apply recommended to all, the Fixed automatically group, and the per-book switch.
- After each merge, on the mini PC: plan b2 again and look at (1) any structural finding (must be none), (2) any Inbox item without a recommended option (must be none), (3) the diagnostics folder (must stay empty).

## Risks, said plainly
- **Nothing here has run on a real model yet.** The prompts for `starts_with` (acts, scenes) rely on a 35B model picking ids correctly; the mitigation is the closed list of valid ids in the prompt and a one-problem correction message, but only b2 will tell.
- **Format changes re-plan existing b2 acts/scenes once** (earlier versions are kept and restorable; written prose is never touched).
- **Recommendations will sometimes be wrong.** That is why the default is Ask me, every action has Undo, and overrides are recorded per outcome so a recommendation you keep overriding is switched off (existing demotion).
- **Scope:** about eight PRs. Phases 1 to 5 can ship without touching the Inbox; Phases 6 to 8 are the part you will see.

---

## Phase 5c detail (inserted): knowledge needs without redundancy

**What the b2 "Decisions about the world" card shows:** 27 decisions waiting and about 40 already approved, all stance "Extrapolate", for roughly ten topics:
- rapid-hardening polymer concrete / sealant: about 14 (ch01, ch03, ch04, ch08, ch12, ch16 ... "how does it cure", "how long", "visual indicators", "failure modes", "how to verify the seal")
- plasma cutter (vacuum, microgravity, arc stability, sparks): about 9 (ch06, ch10, ch11, ch13, ch20, ch21 ...)
- automated security / lockdown / containment priority: about 12
- debt liens and non-disclosure agreements: about 6
- excavation arms, radiation fatigue, magnetic anchoring: about 6
- launch from a low-gravity asteroid, propulsion, flight logs: about 4

**Four causes (read in `research/step.py`, `research/notes.py`, `prompts/research_questions.md`, `layers/structure.py`):**
1. **Duplicates are matched on the exact wording.** `normalize_question` is `casefold` plus whitespace; "How do plasma cutters behave in microgravity..." and "How do plasma cutters behave in a vacuum..." are two questions, each with its own search, its own facts and its own approval.
2. **Every chapter asks again, and is not told what was already decided.** `layers/structure.py` runs research before each chapter's scenes (`scene_questions: 2`, `applies_to=[chapter.id]`), and `research_questions.md` shows only the research NOTES (facts), never the existing needs. So the model re-asks the same topic with new words in every chapter, and each need is scoped to one chapter ("Raised for b2.ch01, so only those scenes get it").
3. **The approved rules contradict each other, and become canon that the continuity check enforces.** Cure time alone: "within 15 minutes", "within minutes rather than days", "within hours ... fully over 24 hours", "80% of strength within minutes", "within seconds" (vibration-activated). Plasma cutter in a vacuum: "self-contained gas reservoir and radiators", "requires modified gas flow", "sparks float as droplets", "wider, less focused arc". A scene that follows one rule contradicts another.
4. **The book's own policy is not used.** The Inbox shows "How a fact about the world is answered: Invent it (soft sci-fi, fantasy)" and mode "Also answer minor facts about the world", yet the research step takes its stance from the realism statement (everything came out "Extrapolate" with web lookups) and every need waits for you. Two systems decide the same thing (`answers.policy_for` for Inbox questions, the realism statement for research needs), and the policy never reaches the needs. Most of these are minor mechanics, which you said the tool should decide.

**Changes**
1. **Topics, not wordings.** Each need gets a `topic` (a short key from its distinctive stems, `validators/text.py::content_stems`, plus a one-line label asked once from the model). Similarity is by topic (stem dice, then one narrow model call to confirm when unsure), not by the exact sentence. A new question whose topic already has a need (waiting, approved, or rejected) is NOT asked or looked up again: the existing need gets the chapter added to `applies_to` ("also applies to b2.ch05"), and the author sees nothing new.
2. **Tell the generator what exists.** `research_questions.md` gets a compact "Already decided or waiting (ask only about something NEW)" list (topic label plus one line of the rule, at most about 1500 characters), `scene_questions` default 2 becomes 1, and the prompt rule becomes "at most one question per topic in the whole book".
3. **Scope follows use.** A need that applies to two or more chapters becomes whole-book (`applies_to = []`) automatically; one card, "applies to the whole book".
4. **Contradictions are one item.** When two needs on one topic state different numbers or units (a small deterministic extractor: numbers plus time, length, mass units, plus the wording "within seconds / minutes / hours / days"), they become ONE decision: "These two rules disagree: A says ..., B says ...", with the options "Use A", "Use B", "Merge into one rule (recommended: the tool writes it from both)". Until decided, neither is held as canon by the continuity check.
5. **Consolidate what exists (one tap, undoable).** `needs --consolidate` and a button on the card: cluster all current needs by topic; for each cluster of two or more, one narrow call writes ONE consistent rule from its members (resolving numbers, keeping the story's constraints); show the preview ("67 decisions become 10 topics"); on one tap the merged needs replace the members (members keep `merged_into`, nothing is deleted; `versions.keep` snapshot of `needs.jsonl` for Undo). Approved members' wording is kept in the merged rule's history.
6. **The policy decides minor ones.** For a book whose policy is `invent` or `extrapolate`, in assist/auto mode, a need the size check calls minor (`resolve` markers: no new character, event, date, death or turning point) is approved by the tool as "decided by the tool" with Undo, listed in a collapsed group, not asked. Major ones stay yours. One source of truth: the research step reads `answers.policy_for` for the stance of a need; web lookups are skipped for `invent`.
7. **The card groups by topic.** "Decisions about the world" shows one card per topic ("Polymer sealant: 14 questions merged, applies to the whole book"), one Approve per topic with the recommended wording preselected (the Part B rule), and "Approve all minor" for the waiting ones.

**Files:** `research/notes.py` (`Need.topic`, `merged_into`, `add_need` dedupe, `consolidate`), `research/step.py` (`run_research`, `generate_questions`), `research/topics.py` (new: topic key, similarity, number extractor, contradiction), `prompts/research_questions.md`, `prompts/need_merge.md` (new), `layers/structure.py` (`scene_questions`), `config.py`, `ops.py` (`decide_need`, consolidate), `api.py` / `ops` routes for `needs`, `answers.py` (policy to stance), `resolve.py` (size check reuse), `inbox` or the needs card in `frontend/bookforge/src/pages/Inbox.tsx`, `lib/types.ts`, `tests/`, docs and BUILD_STATUS.

**Tests:** near-duplicate questions on one topic add no second need and extend `applies_to`; the generator prompt carries the existing topics; two chapters on one topic become one whole-book need; the b2 shapes (cure time 15 minutes vs 24 hours; plasma cutter) are detected as ONE contradiction with the three options, and neither is canon until decided; consolidation turns a fixture of 67 needs into the expected topic count, keeps `merged_into`, is idempotent and undoable; the policy `invent` plus assist mode approves a minor need and leaves a major one waiting; a replay of the b2 card (27 waiting) ends with at most the number of topics waiting.

**Verification:** full suite; on the mini PC press Consolidate on b2 and compare the card (67 becomes about 10 topics, the contradictions listed once), then re-plan one chapter and confirm no new need appears for a topic that exists.

