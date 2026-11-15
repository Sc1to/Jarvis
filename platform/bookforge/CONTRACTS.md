# Bookforge stage contracts

What each planning stage takes in, what it must produce, and what the validators check. Prompt edits (shipped, or overrides in
`<series>/workbench/prompts/`) must keep these contracts. `tests/test_contracts.py` fails when a shipped prompt loses a slot or a
phrase listed here; run `python -m bookforge suite` after any prompt, setting or validator change.

Hard findings are fed back to the model (at most `qc.max_revision_rounds` times; the second round is firmer: it says the last correction did not fix them, marks each problem that is STILL PRESENT, and quotes the parts of the model's own reply the problems point at, `prompts/correct_again.md`); one that survives stops the stage, and nothing flows
downstream. A hard finding you judge to be a false alarm can be accepted (dashboard: Stage checks, "Accept this finding"; `validation/accepted.json`): it stays in the report, marked accepted, and stops blocking that stage. Hard repeat findings are also put once to the critic (`qc.confirm_repeats`): only a clear "different events" downgrades them. Soft findings are recorded in `books/<book>/validation/<stage>.json` and shown in the dashboard (Workbench, Briefing tab,
"Stage checks"). Every validator detects a pattern (repeats, regressions, missing coverage, flat tension), never story content.

| Stage | Reads | Writes | Must hold (hard) |
|---|---|---|---|
| ledger (`prompts/ledger.md`, `ledger_revise.md`) | synopsis, north stars, carried state | `ledger.yaml`: events (id, text, verbatim excerpt, once_only, after, kind, weight, ending, pays_off, source), questions, capacity | every synopsis paragraph (the last = resolution) yields an event; excerpts are verbatim; ids unique, causes earlier; no reveal before its setup, a payoff names an earlier setup (reversed or unmarked pairs are repaired automatically); a setup nothing pays off becomes a question for the author, not a failure; an ending exists; derived events are minor children; a thin synopsis has questions (never padding) |
| acts (`acts_ledger.md`) | ledger | `acts.yaml`: events, turning_point_event, chapter_count, sizing_reason | every event in exactly one act, in order; the last act holds the resolution; the turning point is one of the act's events and not in the first half of its act; an act's summary does not retell another act's event; (soft) no act holds over 45% of the chapters, and the last act's summary describes the resolution events |
| (chapter capacity) | | | every chapter needs an event of its own: an act has at most one chapter per event, a second for each weight 3 event (`events_continued`, only in the chapter right after it begins, never a third), and a few derived complications; an act asking for more is refused at the acts stage |
| chapters (`chapters_ledger.md`) | ledger status (done / assigned / reserved), earlier end states, tracks, <=3 research notes | `chapters.yaml`: events_covered, end_state; `derived_events`; tracks | no once_only event twice; nothing reserved for later; a chapter's summary must not retell another chapter's event (soft: it shares no words with an event it lists); at most about a third of an act's events as derived complications; every assigned event covered, in order; each chapter has an event not told before; no chapter replans another; no flat stretch of tension across the book |
| scenes (`scenes_ledger.md`) | ledger status, story so far (end states), chapter, tracks, <=3 research notes | `scenes.yaml`: events, end_state, beats (>=1); timeline; tracks | each chapter event shown in a scene, a once_only one in exactly one; scene count fits the chapter's weight (about 3 weight per scene: crammed or padded fails); beats must not retell an event of another chapter; scenes have end_state; no repeated event or action pattern across chapters; research terms do not become beats; no state flips back without a `cause`; nobody in two places; story days never run backwards |
| prose (`prose.md`, `prose_system.md`, briefing) | briefing: previous-scene tail (~250 words), story so far (accepted prose / end states), reserved events | scene text | no copied sentences between scenes, no chapter opening with the previous ending; soft: wrap-up endings, tic words |

Inherited state: what the series ledger says is true when the book begins reaches the acts, chapters and scenes prompts (`{carried}`) and every scene briefing of a ledger book. The critic's plan review also gets the ledger status. Times of day are compared as parts of the day (`dusk` = `evening`), and the semantic repeat check also runs on the written scene summaries.

Whole-book checks (after every act or chapter is planned) run before anything is saved. A hard finding drops the saved pieces it names (acts for the chapters stage, chapters for the scenes stage), puts the findings in the layer's note (under the author's own words, which still reach the ledger-mode prompts) and stops; the next Run plans just those pieces again with the findings in their prompt, instead of reusing them and failing the same way. A chapter continuing a weight 3 event sees it as CONTINUING, not DONE; scenes of one chapter that tell the same thing are caught; a chapter heavier than four scenes can carry is refused.

The ledger's events cannot be edited in the Documents tab once the acts (or anything after) are built on them: Redo with the cascade box writes the ledger and what follows again. An event's text must stay close to the excerpt it quotes (soft). The critic's second look at repeat findings also runs inside each act's chapter check and at the prose stage (answers are remembered per pair of passages), and a written scene that hardly mentions the events its plan lists is a soft finding.

The planner of one act's chapters sees the other acts by title only and its own act without its summary (a summary retells events and leaks the others: a real run turned act 2's "buried ship" into chapter 3 of act 1); the scene planner sees the chapter's act by purpose only. A derived complication written loosely (its text under `description`, no id, no `after`) is understood; a retelling of a reserved event says what to do instead.

A failed layer saves nothing: the chapters and scenes layers write the cast, tracks, timeline, chapters, scenes and ledger inside one all-or-nothing block (`store.transaction`), so an attempt that fails leaves those files exactly as they were. (Research facts and saved pieces are kept on purpose, so a rerun does not repeat web searches or model calls.) A cast entity that is listed again is ignored, not an error.

Each book has its own bible (`books/<book>/bible/`); a track may carry `starts_as`, the state it begins the book in, copied from an earlier book (held until its first plan entry).

## Load-bearing prompt text
- Every ledger-mode planning prompt lists events as DONE / ASSIGNED / RESERVED FOR LATER and says reserved events must not be used.
- Research is always labelled reference only: never a beat, an event, an obstacle or a plot device; at most three notes per chapter or scene.
- `prose_system.md` forbids ending on a summary or thematic wrap-up, and restating the previous scene.
- Sizing comes from the material: chapter counts estimated at the acts stage from event weight (with a reason) and decided by the chapters stage from the events, scenes 1 to 4, scene length from the beats. `layers.*.count`, `per_chapter`, `layers.prose.words` and `book.target_words` are optional overrides.

## Files
`books/<b>/ledger.yaml`, `acts.yaml`, `chapters.yaml`, `scenes.yaml`; `books/<b>/validation/{ledger,acts,chapters,scenes,prose}.json`; per series: `workbench/prompts/` overrides.

## Cast editor (`cast.py`)
Input: entity id, kind (character/place/object/group/concept), name, facts (at least one). Invariants: a change that would add a validation problem is refused and nothing is written; delete is refused while any chapter, scene, ledger event, track or character rule refers to the entity; rename is all-or-nothing across those files and refused on a shared bible.

## Judging the input (2026-11-14)
- **ledger stage:** first the synopsis audit (`layers/audit.py`): findings with verbatim quotes become author questions (`type`, `quotes`); hard kinds (`contradiction`, `unestablished_object`, `cast_conflict`) stop at the ledger checkpoint with no events until answered or approved; answers travel as notes into the audit and extraction prompts (`{notes}`). Extraction then requires: one `ending`, at most one `decision`, varied weights, every plot sentence quoted, causes and conditions first.
- **acts:** `sizing_reason` agrees with the real weight and `chapter_count` (or starts `override:`); the counts add up to within `ledger.count_tolerance` of the ledger estimate; the last act turns on the decision or the resolution. `chapter_count` is an estimate: the chapters stage decides the real number from the events and writes it back.
- **chapters:** summary and end_state claim only their own and earlier events' changes (`end_state_overreach`); the POV character is in the text and its main person; names resolve to the cast.

## The Inbox (2026-11-14)
- Items: ledger questions (`ledger.yaml`) and hard findings (`validation/<stage>.json`, minus the accepted ones). Blocking = an audit-type question that is open, or any open hard finding. `Ledger.last_run` is written by the ledger stage when it audits, extracts or revises.
- Writes go through `ops.py` only; an answer is refused once `applied`; approving a checkpoint with open items for its stages needs `skip_open`.

## Proposals (stage 1)
- `resolve.propose_all` writes `validation/proposals.json` keyed by Inbox item id; a proposal never changes a ledger, cast or plan file in `shadow` mode. A model answer is used only if it names a change in the exact words of the sentence (or names none and is commentary).

