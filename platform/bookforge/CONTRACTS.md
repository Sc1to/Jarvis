# Bookforge stage contracts

What each planning stage takes in, what it must produce, and what the validators check. Prompt edits (shipped, or overrides in
`<series>/workbench/prompts/`) must keep these contracts. `tests/test_contracts.py` fails when a shipped prompt loses a slot or a
phrase listed here; run `python -m bookforge suite` after any prompt, setting or validator change.

Hard findings are fed back to the model (at most `qc.max_revision_rounds` times); one that survives stops the stage, and nothing flows
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

## Load-bearing prompt text
- Every ledger-mode planning prompt lists events as DONE / ASSIGNED / RESERVED FOR LATER and says reserved events must not be used.
- Research is always labelled reference only: never a beat, an event, an obstacle or a plot device; at most three notes per chapter or scene.
- `prose_system.md` forbids ending on a summary or thematic wrap-up, and restating the previous scene.
- Sizing comes from the material: chapter counts from event weight (with a reason), scenes 1 to 4, scene length from the beats. `layers.*.count`, `per_chapter`, `layers.prose.words` and `book.target_words` are optional overrides.

## Files
`books/<b>/ledger.yaml`, `acts.yaml`, `chapters.yaml`, `scenes.yaml`; `books/<b>/validation/{ledger,acts,chapters,scenes,prose}.json`; per series: `workbench/prompts/` overrides.
