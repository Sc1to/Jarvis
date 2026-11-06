# BOOKFORGE — Architecture Spec and Install Guide
## Platform Phase 14

> **Status:** design only, nothing built. Adapted from the author's original bookforge spec for the Jarvis platform (2026-11-05). Source of truth for Phase 14 in `BUILD_SEQUENCE.md`.
> Model names, download sizes and speeds in this document are the author's plan and have **not** been verified on the MS-S1 Max (Phases 1–2 incomplete).

## Jarvis integration (read first)

Bookforge is a **separate tool that stands next to the writer app**. It shares no database, files or settings with `platform/writer`. It is a `platform`-domain app.

Differences from the original standalone spec, all decided 2026-11-05:

| Topic | Original spec | In Jarvis |
|---|---|---|
| Form | CLI plus files, repo at `~/bookforge` | Pipeline library + CLI + FastAPI service `platform-bookforge` in `platform/bookforge/`, route `/bookforge` via Caddy, React dashboard in `frontend/bookforge/` |
| Model backend | colibri on ports 8000 and 8001 | colibri on **8040** (fast writer) and **8041** (planner/critic). 8000/8001 belong to the admin panel and the Conductor. Ollama remains the backend for every other app. |
| Systemd names | `colibri-writer`, `colibri-critic` | `platform-colibri-writer`, `platform-colibri-critic`; `platform-bookforge` for the service |
| Web research | SearXNG in Docker on 8080 | Jarvis Playwright web tool (`platform/tools/web_tool.py`). No SearXNG, no extra Docker container. Agents never make direct HTTP calls to the internet. |
| Service port | n/a | 8100 (pinned in STACK.md; wired into `scripts/deploy.sh` and `scripts/build-frontends.sh` like the other first-party apps) |
| Data location | `series/` next to the repo | `/opt/platform/data/bookforge/<series>/`, one Git repo per series |
| Notifications | ntfy | Platform Web Push (see STACK.md, Web Push Notifications) |
| Dashboard binding | `127.0.0.1` over Tailscale | Behind Caddy like every app; Tailscale remains the only remote path |
| Repo `CLAUDE.md` | Own `CLAUDE.md` in `~/bookforge` | None. The Jarvis `CLAUDE.md` governs; the bookforge-specific rules are listed under Building it |

Jarvis hard rules that apply: own `venv/`, `requirements.txt`, `GET /health`, `{data, status}` responses, try/except on every endpoint, `logging` module (no prints), tests in `tests/`, Tailwind + React 18 + Vite with `dist/` output, mobile-responsive to 390px, app registered through the admin panel (never edit the Caddyfile by hand).

Git note: bookforge commits every accepted step inside its own series repositories. This is outside autocoder sessions, like the writer app's book repositories; the Conductor-only commit rule does not apply to it.

## Overview

`bookforge` turns a storyline into a full manuscript on one local machine: it researches, plans, drafts scene by scene, checks its own work, and stops at four human checkpoints. Everything runs locally on the MS-S1 MAX through colibri, except web research, which goes through the platform Playwright web tool.

**Goals**

- Input: a premise of a few paragraphs. Output: a revised manuscript in Markdown, plus a report of what was flagged.

- Quality is designed in: small focused contexts, a separate critic, mechanical checks, and human sign-off where errors cascade.

- Every artifact (bible, outline, research, scenes) is a plain file you can read and edit between stages.

- Resumable: any stage can be stopped and rerun without redoing finished work.

**Non-goals (for v1)**

- No cloud models. The command line plus files is enough for the first book; the dashboard (milestone 11) is a thin client on top of it, not a separate source of state.

- No publishing or formatting for print; export to Markdown, then use other tools.

- No fully hands-off mode. The four checkpoints are part of the design.

**Design principles**

1. Never feed the whole book to a model. Each call gets a briefing pack of 10–20k tokens.

2. Big model for few, short, high-stakes decisions; fast model for bulk work.

3. The writer never grades itself.

4. Objective checks in code, judgment checks by a model, taste decisions by you.

5. Every fact in the book traces back to a stored source.

6. Write top-down: series and book north stars, synopsis, acts, chapters, scenes, prose; each layer refines its parent.

7. The bible tracks state over time, and a change re-checks only what depends on it.

## Architecture

One Python orchestrator talks to two colibri model servers and the platform web tool over HTTP and keeps all state in plain project files. The `platform-bookforge` service and the CLI are two front ends on the same orchestrator library.

*(The original diagram, 1 orchestrator + 4 local services, is not reproduced here: orchestrator → colibri writer :8040, colibri critic :8041, platform web tool (Playwright), plain project files.)*

The orchestrator never holds the book in memory: it reads what a step needs from the project files, builds a briefing, calls a model, and writes the result back. You work with the same files directly at each checkpoint.

## Hardware and model plan

The target machine is a Minisforum MS-S1 MAX: Ryzen AI Max+ 395 (16 cores), Radeon 8060S iGPU, 128 GB unified LPDDR5x, one 4 TB NVMe SSD (PCIe 4.0 x4), Ubuntu. Models run through [colibri](https://github.com/JustVugg/colibri), which keeps the hot part of a mixture-of-experts model in RAM and streams the rest from the SSD.

| Role | Model (colibri `--model` id) | Download | Expected speed | Used for |
|---|---|---|---|---|
| Writer (fast) | Qwen3.6-35B-A3B (`qwen36-35b`) | 23 GB | Not yet measured on the 8060S; 9.9 tok/s on the weaker Radeon 780M | Research summaries, scene drafts, summaries, revisions |
| Planner and critic (big) | GLM-5.2 (`glm-5.2`) | 429 GB | About 1.8 tok/s on a 128 GB Ryzen AI Max+ 395, CPU only | Story bible, outline, critique, pairwise judging |
| Optional prose upgrade | Qwen3.8-Flash-Next (`qwen38-flash-next`) | 186 GB | Not yet measured on this machine | Drafting, if Qwen3.6 prose feels flat |

**Two servers, two ports.** Run the writer on port 8040 and the planner/critic on port 8041, each as its own `coli serve`. The writer takes roughly 20 GB of RAM, leaving the rest to the big model's expert cache. If both together run out of memory, run them one at a time: the pipeline groups calls by model so it only needs one loaded per stage.

**Disk budget (4 TB):** Ubuntu and tools ~100 GB, the three models ~640 GB, projects and logs under 50 GB. Plenty of room left for a second big model later.

**Time budget per novel:** a 90,000-word book is about 120k output tokens. One draft pass on the fast model takes a few hours; the critic reads every scene, so critique is the slow part. Plan one night per pass, 2–3 passes per book.

Open question: real tok/s on the 8060S. Measure with `coli tune` after install and update this table.

## Project layout and data model

The code lives in `platform/bookforge/` in the Jarvis repository; each series is its own folder of plain files and its own Git repository, with one subfolder per book. State lives in the files, so the pipeline can always resume.

```
platform/bookforge/            the tool (part of the Jarvis repository)
├── main.py                    FastAPI wrapper (health, runs, checkpoints)
├── requirements.txt
├── config.example.yaml
├── bookforge/
│   ├── cli.py                 new | run | status | approve | stale | changes | report | assemble | bench
│   ├── llm.py                 OpenAI-compatible client, retries, logging
│   ├── layers/                runner.py (the shared loop) + one settings file per layer
│   ├── bible/                 tracks.py (state at a point), extract.py (prose → observed)
│   ├── deps.py                content fingerprints, deps.yaml, what differs
│   ├── stale.py               staleness scan, plan snapshot, re-check / patch / redraft
│   ├── changes.py             change requests (filed from gaps, approved or rejected)
│   ├── vcs.py                 git commits, tags, change-request branches
│   ├── briefing.py            builds the per-call context pack
│   ├── rules.py rules_ai.py   the rules panel: storage, enforcement, hit counts, model-backed tests
│   ├── xray.py studio.py      briefing preview and X-ray; prompt overrides
│   ├── ab.py calibration.py arc.py   prompt A/B tests, your scores vs the critic, tension and threads
│   ├── report.py              morning report
│   ├── assemble.py            manuscript.md from the accepted scenes
│   ├── bench.py               benchmark runs and comparison
│   ├── qc/                    mechanical.py critic.py continuity.py judge.py
│   ├── research/              search.py (web tool) fetch.py notes.py
│   └── prompts/               one .md template per layer and check
├── tests/
└── benchmarks/                fixed scenes for regression runs

/opt/platform/data/bookforge/my-series/   one series = one git repository
├── north-star.md
├── ledger.yaml                open threads, foreshadowing, end-of-book states
├── style/                     guide.md, samples/*.md, banned.txt
├── bible/                     constants.yaml, tracks.yaml, timeline.yaml
├── research/                  shared notes and sources.jsonl
└── books/b1/
    ├── north-star.md
    ├── synopsis.md
    ├── acts.yaml  chapters.yaml  scenes.yaml
    ├── research/              book-specific notes
    ├── scenes/ch05/s1/        draft-1.md draft-2.md final.md review.json
    │                          summary.md extracted.yaml deps.yaml
    ├── change-requests/
    ├── state.json
    ├── reports/
    └── logs/calls.jsonl
```

**Key records**

| File | Holds | Written by | Edited by you? |
|---|---|---|---|
| `north-star.md` (series and book) | One page: premise, themes, emotional promise, tone, ending direction, what it is not | Layers 1–2 | Yes, you approve both |
| `bible/tracks.yaml` | Planned and observed states over time, with versions | Chapter and scene layers; extraction after prose | Yes |
| `bible/timeline.yaml` | In-story date and time per scene | Scene layer | Yes |
| `acts.yaml`, `chapters.yaml`, `scenes.yaml` | Per item: id, purpose, beats, POV, setting, research fact ids | Layers 4–6 | Skim acts; rarely below |
| `research/sources.jsonl` | One line per fact: claim, URL, date fetched, short quote | Research step of each layer | Spot-check |
| `scenes/…/deps.yaml` | Exact versions of everything the item was built from | Briefing builder | No |
| `scenes/…/extracted.yaml` | What the prose actually says about tracked states | Extraction after each scene | No |
| `change-requests/*.yaml` | Proposed parent change, reason, items it would make stale | Any layer | Approve or reject |
| `ledger.yaml` | Open threads and end-of-book states | After each book | Yes |
| `state.json` | Status per item: pending, drafted, checked, accepted, stale, flagged | Every step | No |

**The briefing pack** (assembled by `briefing.py` for each drafting call, target under 16k tokens):

1. Series and book north stars

2. Style guide and 1–2 sample passages

3. Bible constants, and every state track at this scene, for the characters and places in it

4. This scene's beats, its chapter's purpose, and its research notes

5. Summaries of the previous chapters (compressed further the older they are)

6. The last ~1,500 words of the previous scene, verbatim

## Pipeline: layered refinement

The book is written top-down through seven layers, each refining the one above it, and every layer runs the same four-step loop. In code this is one layer runner with per-layer settings, not seven separate stages.

| # | Layer | Count | Research | Review | Output |
|---|---|---|---|---|---|
| 1 | Series north star | 1 per series | Broad: genre, era, world | You | `north-star.md` |
| 2 | Book north star | 1 per book | What is specific to this book | You | `books/b1/north-star.md` |
| 3 | Synopsis | 1 | Gaps the synopsis reveals | You, quickly | `synopsis.md` |
| 4 | Acts | 3–4 | Rarely | Critic; you skim | `acts.yaml` |
| 5 | Chapters | 25–35 | Settings, events | Critic | `chapters.yaml`, new state tracks |
| 6 | Scenes | 80–100 | Concrete details | Critic + System One | `scenes.yaml` |
| 7 | Prose | 80–100 | None: uses scene notes | Full QC stack | `scenes/…/final.md` |

**The loop each layer runs**

1. **Refine:** expand each parent item into its children (big model for layers 1–6, fast model for prose).

2. **Research:** generate questions only this layer needs, search, store notes with sources.

3. **Review:** the critic checks each child against its parent and both north stars; System One checks it against the bible's state at that point.

4. **Correct:** fix only what review flagged, at most two rounds; anything unresolved goes to the morning report.

**Rules**

- **Constraints flow down, change requests flow up.** A lower layer never silently contradicts its parent; it files a change request (see Version control).

- **Research at the lowest layer that needs it.** No sensory details while planning acts.

- **North stars stay one page.** Premise, themes, emotional promise, tone, ending direction, and what the book is not. Both go into every briefing.

- **Scenes say what and why, not how.** Beats name events and purpose; the prose layer decides gestures and wording.

- **Chapter 1 goes first.** Its prose is written and reviewed alone before the rest (voice checkpoint).

- **Calls are grouped by model,** so only one model needs to be warm at a time.

## Story bible: state over time

The bible answers one question: what is true at this exact point in the story? It holds three kinds of entries, shared across all books of a series.

| Kind | Changes? | Examples | File |
|---|---|---|---|
| Constants | Never | Eye color, birthplace, how magic works | `bible/constants.yaml` |
| State tracks | Over time | Injuries, location, relationships, possessions, who knows which secret | `bible/tracks.yaml` |
| Timeline | Per scene | In-story date and time of every scene, travel durations | `bible/timeline.yaml` |

**A state track** (the wound example):

```yaml
- id: anna-shoulder-wound
  entity: anna
  version: 2
  plan:                          # written by the chapter and scene layers
    - from: b1.ch04.s3
      value: "deep cut, left shoulder; bleeding"
      must_show: true            # the injury happens on the page
    - from: b1.ch05.s1
      value: "stiff and painful; can't lift left arm or draw a bow"
    - from: b1.ch08.s1
      value: "healing; limited use, twinges under strain"
    - from: b1.ch10.s2
      value: "healed; scar remains"
      must_show: true            # the healing is noticed on the page
  observed: []                   # filled from the prose after each scene
```

**How it connects to the layers**

1. **Down:** the chapter layer creates the track ("wounded in ch4, healed by ch10"); the scene layer refines it to exact scenes and specifics.

2. **Across:** the briefing builder looks up every track touching the scene's characters and places at that scene, and adds them as hard constraints ("Anna can't use her left arm").

3. **Up:** after each scene, the fast model extracts what the prose actually says into `observed`. A gap between plan and observation is a continuity flag; a deliberate change becomes a change request.

**Checks this enables**

- **Obligations:** every `must_show` state must appear in its scene, or the scene fails review.

- **Plausibility:** healing, travel and aging depend on story time, not chapter numbers. Research supplies realistic durations; the critic compares them with `timeline.yaml`.

- **Knowledge:** "who knows the secret by ch12" is a track like any other, which prevents characters reacting to things they cannot know yet.

**File formats** (milestone 14.5; each file is written from validated records, unknown keys a model adds are dropped)

```yaml
# books/b1/acts.yaml  (layer 4)
acts:
  - {id: b1.act1, title: ..., summary: ..., purpose: ..., turning_point: ..., chapter_count: 8}

# books/b1/chapters.yaml  (layer 5)
chapters:
  - {id: b1.ch04, act: b1.act1, title: ..., purpose: ..., summary: ..., pov: anna, setting: harbor, tension: 6, research: [s-0003]}

# books/b1/scenes.yaml  (layer 6): what and why, not how
scenes:
  - id: b1.ch04.s3
    chapter: b1.ch04
    purpose: ...
    pov: anna
    setting: harbor
    characters: [anna, jonas]      # always includes the pov character
    beats: [Anna confronts Jonas about the ledger., He lies badly.]   # 2-8 events in order
    research: [b1-0002]

# bible/constants.yaml  (series-wide, created by the chapters layer, never changes during the story)
entities:                           # kind: character | place | object | group | concept
  - {id: anna, kind: character, name: Anna Voss, facts: [grey eyes, left-handed]}
rules:
  - {id: ledger-cost, text: each name crossed out costs a year of memory}

# bible/tracks.yaml  (the spec's track format, under a top-level `tracks:` key)
tracks:
  - id: anna-shoulder-wound
    entity: anna
    kind: physical                 # physical | location | relationship | possession | knowledge | status | other
    version: 3
    plan:
      - {from: b1.ch04.s3, value: "deep cut, left shoulder; bleeding", must_show: true}
    observed: []

# bible/timeline.yaml  (written by the scene layer; time is a story-day number so it works in invented calendars)
scenes:
  - {id: b1.ch04.s3, day: 12, time: evening, date: "14 March 1893", flashback: false, travel: ""}   # date, flashback, travel optional
```

How the pieces fit:

- **Positions.** A `from` is a chapter id (the state holds from the start of the chapter) or a scene id. Within a book, positions are ordered by (chapter, scene), and a chapter counts as scene 0. Ordering across books is not supported yet.
- **Who creates what.** Layer 4 writes the acts, with a chapter count per act that must add up to the configured range. Layer 5 first writes the cast and world to `constants.yaml` (the tracks and scenes need entity ids to point at), then plans the chapters of one act per model call, creating or extending tracks with chapter-level positions. Layer 6 plans the scenes of one chapter per call and gives each scene a story day and time.
- **Tracks are refined, never silently rewritten.** In layer 6 the model restates each track's entries for the chapter at scene level. Every track that already has entries in that chapter must be restated, with at least as many entries and as many `must_show` flags, or the reply is sent back for correction. A track's `version` starts at 1 and goes up by one for every chapter whose entries the scene layer changes. After layer 6 no `must_show` entry is left at chapter level.
- **State at a point.** `bookforge/bible/lookup.py` answers "what is true at scene X": for every track, the latest entry at or before X, with `since`, `begins_here`, `must_show` (only on the scene where the entry begins) and the `previous` value. `scene_entities` gives the characters and setting of a scene, which is the filter the briefing builder uses (milestone 14.6). `python -m bookforge state-at <series> b1.ch04.s1` prints it, with the scene's story day.
- **Timeline checks.** Story days must not go backwards between scenes unless a scene is marked `flashback: true`; every scene needs a timeline entry; `elapsed_days` gives the gap between two scenes for plausibility checks.
- **Resuming.** Each model reply for layers 5 and 6 is checked, corrected if needed, and saved in `books/<book>/work/<layer>/` (not tracked by Git). A stopped run reuses the saved pieces; when all pieces are in they are assembled, cross-checked (`validate_bible`), and the work folder is removed. Hand-written `acts.yaml`, `chapters.yaml` or `scenes.yaml` files are checked and kept, like the direction files.

**Series ledger** (`ledger.yaml`): open threads, foreshadowing still to pay off, and each track's state at the end of every book. The next book's north star starts from it.

## Version control and incremental updates

The series folder is a Git repository, and a dependency graph decides which scenes a change touches. Git gives history and safety; the graph gives surgical updates.

**How Git is used**

- **One commit per accepted step,** e.g. `b1.ch05.s2: drafted, checked, accepted`. Any scene's history and any rollback are one command away.

- **Tags at checkpoints:** `b1-direction-approved`, `b1-voice-approved`, `b1-draft-1`.

- **Branches for alternatives** ("what if the mentor survives?"), explored and compared, then merged or deleted.

- **Change requests as branches:** the proposed parent change plus the list of affected scenes, reviewed like a pull request.

- **Not one branch per scene.** Scenes share the bible and depend on each other in order, so per-scene branches would conflict constantly, and Git cannot see story conflicts, only text conflicts.

**Dependency tracking**

The briefing builder records exactly what each item was built from, with versions:

```yaml
# books/b1/scenes/ch08/s1/deps.yaml
parent: b1.ch08@v3
north_stars: [series@v1, b1@v2]
bible:
  - anna-shoulder-wound@v2
  - anna-knows-secret@v1
  - setting-harbor@v1
```

When any of those changes version, the item is marked stale and handled in escalating steps:

1. **Re-check:** System One asks whether the item still agrees with the new version. Usually yes, in seconds.

2. **Patch:** rewrite only the contradicting passage.

3. **Redraft:** only when the change is structural.

The same applies between planning layers: a changed act marks its chapters stale, a changed chapter its scenes. `bookforge stale` lists everything out of date and why.

**Change requests** (`books/b1/change-requests/*.yaml`) hold the proposing item, the parent change, the reason, and the stale items it would cause. The critic may accept changes inside one chapter; anything that touches an act, a north star or another book waits for you.

## Managing a series: books, titles, redo, editing, stopping (built for the first end-to-end run)

- **Books.** A series holds any number of books; a book's id (`b1`, `b2`) is written into every scene id, fact id, saved state and Git tag, so it never changes and an id a deleted book used is never handed out again (its tags stay in the history). What you call a book is its **title** (in the book's `state.json`; `python -m bookforge title <series> "The Ledger" --book b1`, the dashboard header, `PUT .../title`). `python -m bookforge add-book <series> --title "..." --brief "..."` (or `--brief-file`), the "Add book" form on the series list, or `POST /api/series/{s}/books` creates `b2`, `b3`, ... with its own folder, state and **brief** (`books/<id>/premise.md`: what this book is about; Documents tab "Book brief"). A book without a brief falls back to the series premise (the first book). The book north star is written from the book's brief, the series north star and the series ledger. A new book **inherits the series north star** when one exists (its `series_north_star` layer starts accepted, "inherited"), and an existing valid file is adopted by any book that finds it, so running book 2 never rewrites the series north star. `delete --book` removes a book and its entries in the shared bible files (as before).
- **Renaming a series** moves its folder (`rename-series <series-path> <new-name>`, the Rename button, `POST /api/series/{s}/rename`); the Git history and everything inside are unchanged; refused while a job runs or if the new name is taken.
- **Redo a planning layer** (`python -m bookforge redo <series> <layer> [--note "..."] [--cascade]`, the "Redo…" button on each layer in the Overview, `POST .../redo`; `GET .../redo/{layer}` says what else would be reset). It resets the layer to pending so the next `run` writes it again, steered by your note: the model sees the note and, for a layer that is one document (north stars, synopsis), the previous version. Layers after it that were built on it (acts, chapters, scenes) are reset too, but only with `--cascade` (the Overview ticks a box). The checkpoints they belong to go back to pending, so you review the new version. Nothing is deleted: what is on disk is committed first (so hand edits survive in the Git history) and is overwritten when the layer runs again, and **the research the reset layers made is moved to `research/archive/`** (`<time>-<layers>.jsonl` with their questions, facts and undecided needs, and their `<layer>.md` notes) so they research from scratch instead of building on facts gathered for the old plan; **decisions you made yourself stay** (anything approved, rejected or edited in the Inbox), a kept decision loses only its pointers to facts that moved, and a new fact never takes an archived fact's id. The series-wide research (`research/` at the series root) is only archived when the series has a single book, because another book's chapters may cite it. A layer that failed and is simply run again, without a redo, keeps its research on purpose, so a run continues without repeating its web searches; the note is removed once the layer is accepted. Refused once scenes have been written (use `rewrite`), because re-planning would orphan them. Redoing `series_north_star` rewrites the series-level file, which other books were built on; they are not reset.
- **Editing documents in the dashboard.** Every document except the research notes can be edited in the Documents tab (premise, book brief, north stars, synopsis, acts, chapters, scenes, cast, tracks, timeline, style guide, banned list), `PUT .../documents/{key}`. The edit is checked first: a north star must keep its sections, a synopsis its length, the plan files must parse and resolve their references. Only **new** problems refuse an edit (an older plan with an unrelated problem, or an older north star without the Realism section, can still be edited); a refused edit leaves the old text in place and says why. Saved edits are committed ("you edited ..."). Not while a job runs; a document longer than 400 KB is not editable in the app.
- **Stopping a job** (Stop in the Overview, `POST .../jobs/{id}/cancel`). The job stops before its next model call (one already running finishes first, up to a minute on a large model); the run reports `cancelled`, no layer is flagged, what was finished is kept and the rest is done on the next run. A cancelled job sends no notification. The stop is a `BaseException` (`bookforge/cancel.py`) so that the handlers that let a run survive one failed page or scene cannot swallow it.
- **Not built yet:** series config (models, target length, research switches) in the app; writing the series ledger when a book is finished, so a later book's north star carries over what ended the earlier one; a book switcher inside the series page.

## Knowledge needs: research, extrapolation, deviation and invention (steps 1-6 built; none yet run on a real model)

What research is for: bookforge notices that the story needs to know something, puts it as a question, asks it, and gets back what it needs to carry the story forward. The first implementation tuned the asking and reading of web pages and left the first two steps (notice, formulate) as one prompt and the last (does it help a scene) unmeasured. This section is the intended design; the research code described above is the engine for part of it.

**A knowledge need** is a record, not just a question: what it is for (the book, chapter or scene and beat that needs it), what kind of knowledge it is (a fact to get right, texture, a constraint, vocabulary), and a **stance** that says how it is to be handled.

| Stance | Meaning | What happens |
|---|---|---|
| ground | The real world must be right (history, medicine, real places and people, how real things work) | Web research with verbatim quotes, as now. Facts are kept as research facts. |
| extrapolate | A real basis, an imagined application (a laser rifle) | Research the real constraints (power, heat, visibility), then record what the story assumes, with the real basis beside it. |
| bend | The truth is known and deliberately changed for the story | Research the truth, then record the deviation and the reason. The critic and the continuity checks treat it as intended, not as an error. |
| invent | Nothing real to look up (a name, a made-up rule) | No search. The decision is written to the bible as a world rule so it stays the same in every scene. |

**The realism setting** (built: the `## Realism` section of both north stars, written by the model from the premise and edited by you at the direction checkpoint; the book's section says "As the series." unless it differs; `bookforge/realism.py` `realism_setting` returns the statement that applies to the open book) decides the default stance. It is one plain statement, for example "hard SF: physics must hold", "space opera: plausible-sounding is enough", "historical: accurate to the decade". It is written in the series north star and may be overridden in a book's north star (both are read; the book wins). The same laser is *extrapolate* under the first, *invent* under the second. Two further inputs: the existing `sensitive` flag pushes towards *ground*; and consequence (does the plot depend on it, would a reader or critic notice) lets a cheap invention stand where a lookup would not change the story.

**Where needs are raised.** After each planning document, as now, and also when a scene brief is written (the point where "what does this office smell like" or "what does this weapon do" first becomes concrete). Needs the writer or the extraction pass finds later (a gap in the draft) are filed through the existing change-request path.

**Who decides.** The model proposes each need with its stance and a one-line reason; **the author approves**. Stances are listed in the direction and structure checkpoints (a short list, one line each) and can be edited there. A need raised at scene-brief time inside an unattended run takes the stance the realism setting implies; any stance that is *bend* or that differs from the default is listed in the morning report for the author to confirm or change, and the affected scenes are marked stale if it changes.

**What is stored and used.** `needs.jsonl` per scope (need, purpose, stance, status proposed/approved, reason, outcome: fact ids, world-rule id, or deviation note). The briefing for a scene carries the approved outcomes that scene depends on: research facts, world rules and deviations, each marked as such, so the writer cannot mistake an invented rule for a real fact, and the checkers can tell an intended deviation from a mistake.

**Measuring it.** Not "did the search return a page" but: for a premise, were the needs the right ones, were the stances sensible, and does a scene that depends on a need carry its outcome. A batch check runs every need of a series through the real code and prints one table (stance, answered or recorded, facts, claims whose quote does not support them). It is run on premises from different eras and places, not only one.

**Built so far (step 3).** After each planning document the model proposes needs, each with a stance, a one-line reason and, for extrapolate, bend and invent, a proposed assumption, deviation or rule (`research_questions` prompt; it reads the realism setting, and asks for things a web page can answer: how an institution, trade, place or practice worked, not one job title or a relationship that exists only in the story; something the story invents is `invent`, or `extrapolate` if it grows from something real, not a lookup of the invention itself). Every need is recorded in `needs.jsonl` per scope (ids `s-n001`, `b1-n001`; a decision appends a line, it never rewrites one) and `research/needs.md` / `books/<book>/research/needs.md` list them, shown at the direction and structure checkpoints and in the dashboard's Documents tab. Lookups (ground, and the research half of extrapolate and bend) run at once; an invented rule, an assumption or a deviation stays `proposed` and has no effect until you decide. `python -m bookforge needs <series>` lists what waits; `--approve ID`, `--reject ID` (a rejected need is not proposed again), `--edit ID --stance S --rule "..."` (an edit puts it back to `proposed`; it is not an approval), `--all` also shows lookups. The API has `GET .../needs` and `POST .../needs/{id}` (`action`: approve|reject, `stance`, `rule`). Waiting decisions are listed in the morning report under "Needs you" and in the dashboard's Inbox, in a "Decisions about the world" card above the change requests: each shows the question, the model's reason, a stance menu and an editable text box, with Approve (with your changes, if you made any), Reject, and Save to decide later; Approve is disabled for a stance that needs text while the box is empty; what you have decided is kept in a collapsed list. The Inbox badge and the Overview note count them. **Step 4.** Approved decisions (invent, extrapolate and bend needs with a rule) reach the work: the scene briefing has a section "The author's decisions about this world (canon: invented or changed on purpose, not real-world fact)" (never trimmed, like the cast and rules), each marked invented, assumed or changed on purpose; the writer's system prompt says they hold whatever the real world is like; continuity asks one yes/no question per decision ("Author's decision about this world"); and each decision is a `decision:<id>` fingerprint in the scene's `deps.yaml`, so approving or editing one makes the scenes written without it or with the old text stale. Proposed and rejected ones are never shown. **Step 5.** Scene planning raises needs per chapter (before that chapter's scenes are planned, from the chapter's text; the focus now includes what a made-up or changed thing does when the scenes use it), and a need raised there applies to that chapter (`applies_to`, chapter or scene ids; empty means the whole book). A scene's briefing, its continuity questions and its `decision:` fingerprints use only the approved decisions that apply to it, so a rule made for chapter 7 does not fill the briefing of chapter 2 and does not make chapter 2 stale. Every planning prompt (acts, chapters, scenes, questions) also lists the approved decisions beside the research notes, so plans do not contradict them. Change where one applies with `needs --edit ID --applies-to b1.ch03 [--applies-to b1.ch04.s2]` (`--applies-to all` for the whole book; this does not reopen an approved decision), through `POST .../needs/{id}` (`applies_to`), or by ticking "apply it to the whole book" in the Inbox card. Needs raised by the direction and structure layers apply to the whole book. **Step 6: the batch check.** `python -m bookforge research-eval <series> [--document premise.md] [--recorded] [--max 8] [--realism "Hard SF: physics must hold."] [--no-audit]` judges the whole research stage for one story and stores nothing. It proposes the story's needs from a document (the premise by default; any file works, such as a north star or the synopsis, so no layer has to have run), or with `--recorded` takes the lookup needs already recorded; runs every lookup exactly as the pipeline does (invented needs are only listed, with their proposed rule); then reports the claims the pipeline's own audit dropped for saying more than their quote (and, when `research.check_support` is off, runs the same audit itself and reports the claims it would have dropped). `--realism` proposes the needs under a realism setting you give instead of the series' own: run the same premise under "Hard SF" and "Space opera" to see whether the stances change (a series with no north star has no realism setting, and the model then guesses from the premise). The output is one table (stance, result, question, the model's reason, the proposed rule, each kept fact with its page, each unsupported claim with why) and a summary: needs by stance, decisions waiting, lookups answered against the stated bar (at least half), facts kept, claims their quote does not support. It exits 1 when fewer than half of the lookups were answered. Run it on premises from different eras and places (a Victorian port, a space opera, a modern thriller): tuning against one setting proves little. Not yet built: running the lookup when a need's stance is edited into a lookup stance. For extrapolate and bend the assumption is drafted by the model at the same time as the lookup, so read it next to the facts before approving.

**Claim drift (fixed in step 1, not yet seen on a real model).** A fact's claim can drift towards the wording of the question (asked about a clerk, a page about surveyors and boatmen yielded "a customs clerk supervised the staff"). The reader prompt now requires a claim to say only what its quote says, using the page's own role names, and the relevance check drops a claim whose quote does not support it.

## Quality control

Quality control runs in four layers, cheapest first; a scene only reaches the expensive layers after passing the cheap ones.

| Layer | What it checks | How | Automation |
|---|---|---|---|
| 1. Mechanical | Banned phrases, repeated n-grams across chapters, overused words, sentence-length variety, dialogue ratio, tense and POV slips, scene length vs. target | Plain Python in `qc/mechanical.py`, no model | Fully automatic |
| 2. Continuity | Contradictions with `facts.yaml` and character states, timeline order, research facts used correctly | System One yes/no questions, one per relevant fact; flag when P(contradiction) > 0.3 or confidence is low | Fully automatic |
| 3. Critic | Stakes, voice match with samples, show-don't-tell, pacing, dialogue, beats covered | Big model with a fixed rubric (1–5 per criterion), must quote the 3 weakest lines | Automatic; you calibrate it once |
| 4. Judge | Which of 2–3 drafts is best | Big model, pairwise A vs B, run twice with order swapped; disagreement = tie | Fully automatic |

**Revision rules**

- Revise only flagged passages, never a whole scene. The fast model gets the passage, the issue, and the quoted rubric line.

- Re-run layers 1–2 after each revision; layer 3 only if the first critique scored under 3.

- Stop after two revision rounds. Anything still failing goes to the morning report as "needs you".

**Calibration (once, at checkpoint 2)**

Score 5 chapter-1 scenes yourself on the same rubric. If the critic's ranking disagrees with yours on more than one pair, adjust the rubric wording before continuing.

**Regression benchmarks**

`benchmarks/` holds 5–10 fixed scene briefs. After any change to a prompt, model or setting, `bookforge bench` redrafts them and compares mechanical stats and pairwise judgments against the last accepted run. A change ships only if it does not lose.

**Known limits**

- Model judges favor longer text and their own style; the order swap and the separate critic reduce this but don't remove it.

- Passing every check means competent, not good. Your reading at the checkpoints is the final quality gate.

## Human checkpoints and morning report

The pipeline stops at four checkpoints and waits for `bookforge approve`; everything between them runs unattended.

| Checkpoint | When | You review | Typical time |
|---|---|---|---|
| 1. Direction | After layers 1–3 | Series and book north stars, synopsis | 1–2 hours |
| 2. Structure | After layers 4–6 | Skim acts and chapters; decide pending change requests | About 1 hour |
| 3. Voice | After chapter 1 prose | Read closely, score 5 scenes for critic calibration, extend `banned.txt` | 1–2 hours |
| 4. Final | After assembly | Full read, spot-check flagged facts, check nothing resembles existing works too closely | A few days |

**Morning report** (`reports/<date>.md`, written at the end of every run)

- Progress: scenes accepted, flagged, still pending; time and tokens used

- Needs you: scenes that failed after two revision rounds, with the reason

- Unsure: continuity checks with low confidence, critic scores near the threshold

- Suggestions: phrases that appear unusually often, as candidates for `banned.txt`

- Facts to verify: research facts on sensitive ground (history, medicine, real places, real people)

- Samples: 3 random before/after revision pairs, so you can see whether revisions help

The principle: the report tells you where to look, so you read 5 scenes instead of 80.

## Installation guide (Ubuntu)

Docker is not needed. Installation takes an evening of hands-on work plus an overnight download of about 640 GB. Paths in angle brackets are placeholders; `coli status` and `coli serve --help` give the real names on your machine.

**Step 1. System packages and GPU driver**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip build-essential \
  mesa-vulkan-drivers vulkan-tools jq pandoc
vulkaninfo --summary               # should list the Radeon 8060S
```

`pandoc` is for `export`. For PDFs also install one engine: Typst (a single binary from its releases page) or LaTeX (`sudo apt install -y texlive-xetex`). `python -m bookforge doctor` shows what is found.

**Step 2. colibri and the fast model**

```bash
git clone https://github.com/JustVugg/colibri ~/colibri
cd ~/colibri
./start-here.sh --model qwen36-35b --backend vulkan
```

The setup builds the engine, downloads 23 GB, starts the server and opens the dashboard. Chat with it briefly, then press Ctrl+C.

**Step 3. The big model**

```bash
cd ~/colibri
./start-here.sh --model glm-5.2 --reconfigure   # 429 GB, resumable: rerun if interrupted
c/coli status                                   # note the model folder names
```

**Step 4. Tune and measure**

```bash
c/coli tune --model ~/colibri-models/<qwen36-folder>
c/coli tune --model ~/colibri-models/<glm52-folder>
```

Record the tok/s in the hardware table above. Also try the big model with and without `--backend vulkan`; on an integrated GPU either can win.

**Step 5. Run both servers as services**

Create `/etc/systemd/system/platform-colibri-writer.service` (and a copy named `platform-colibri-critic.service` with the big model and port 8041):

```ini
[Unit]
Description=Platform colibri writer model
After=network.target

[Service]
User=<you>
WorkingDirectory=/home/<you>/colibri/c
Environment=COLI_VULKAN=1
ExecStart=/home/<you>/colibri/c/coli serve --model /home/<you>/colibri-models/<qwen36-folder> <port option for 8040>
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now platform-colibri-writer
curl -s http://127.0.0.1:8040/v1/models | jq     # should list the model
```

If memory runs short with both servers up, enable only the writer and let `bookforge` start and stop the critic per stage (see Configuration).

**Step 6. Web research**

Nothing extra to install beyond the platform's Playwright setup (STACK.md, Playwright: `playwright install chromium`, once per host). The `playwright` Python package comes with bookforge's `requirements.txt`. Research uses the Jarvis web tool only. `bookforge doctor` checks that the tool is importable and can fetch a test page.

**Step 7. bookforge itself**

Built with Claude Code (next sections) inside the Jarvis repository, deployed like any platform service with `scripts/deploy.sh bookforge`. The Caddy route comes from `scripts/build-frontends.sh`. Then:

```bash
cd /opt/platform/bookforge
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
python -m bookforge doctor   # checks both model endpoints and the web tool
```

**Step 8. Smoke test**

```bash
python -m bookforge new /opt/platform/data/bookforge/test-series --premise premise.md
python -m bookforge run /opt/platform/data/bookforge/test-series --book b1 --until synopsis
```

A short premise should produce both north stars and a synopsis, then pause at the direction checkpoint.

## Configuration

All settings live in one `config.yaml`; a project can override any key in its own `projects/<name>/config.yaml`.

```yaml
models:
  writer:
    base_url: http://127.0.0.1:8040/v1
    model: <id from coli status>
    temperature: [0.7, 0.85, 1.0]   # one per draft
  critic:
    base_url: http://127.0.0.1:8041/v1
    model: <id from coli status>
    temperature: 0.2
    manage_service: platform-colibri-critic  # optional: start/stop per step to save RAM (not wired up yet)
    timeout_seconds: 1800            # max wait for one reply; the writer defaults to 600
  decide:
    url: http://127.0.0.1:8041/v1/systemone

layers:                            # model for the refine step; review is always the critic
  series_north_star: {model: critic, checkpoint: direction}
  book_north_star:   {model: critic, checkpoint: direction}
  synopsis:          {model: critic, checkpoint: direction}
  acts:              {model: critic, count: [3, 4], checkpoint: structure}
  chapters:          {model: critic, count: [25, 35], checkpoint: structure}
  scenes:            {model: critic, per_chapter: [2, 4], checkpoint: structure}
  prose:             {model: writer, drafts: 2, words: [1500, 3000]}

research:
  search: playwright_web_tool      # platform/tools/web_tool.py; no direct HTTP
  source: wikipedia                # wikipedia | duckduckgo (search-engine pages are blocked to headless browsers)
  wikipedia_language: en           # which Wikipedia to search: en, de, fr, ...
  results_per_question: 5

book:
  target_words: 90000
  pov: third-limited
  tense: past
  language: English                # language of the book; section headings stay in English

briefing:
  max_tokens: 16000                # estimated at about 3.5 characters per token
  previous_scene_words: 1500
  sample_passages: 2               # style/samples/*.md files included
  recent_chapters_full: 2          # chapters before this one summarised scene by scene; older ones in a line each

qc:
  continuity_flag_threshold: 0.3
  critic_min_score: 3
  max_revision_rounds: 2
  banned_phrases: style/banned.txt
  critic_may_accept: within_chapter  # larger change requests wait for you
  dialogue_ratio: [0.05, 0.75]     # share of words inside quotes; outside it is a warning
  sentence_variation_min: 0.45     # stdev / mean of sentence length; below it the rhythm is flagged
  overused_word_percent: 1.0       # a content word above this share of the scene is flagged (names excluded)
  overused_word_min_count: 8
  repeat_ngram_size: 5             # words in a phrase checked for repetition across scenes
  repeat_ngram_scenes: 2           # earlier scenes that must contain a phrase before it is flagged
  judge_drafts: true               # choose between drafts with the pairwise judge (otherwise by mechanical score)
  continuity_check: true           # yes/no questions about the story state, the cast and the world
  critic_check: true               # the rubric critique
  extract_observed: true           # record what each accepted scene says about the tracked states
  review_structure: true           # critic review of acts, chapters and scene plans against their parents
  continuity_batch_size: 8         # questions per model call
  continuity_max_questions: 40     # per scene

git:
  commit_each_step: true
  tag_checkpoints: true
```

A layer may also set `temperature` to override its model's own (for example `synopsis: {model: critic, temperature: 0.7}`). Layers tagged with the same `checkpoint` form a group: the pipeline stops once every layer in the group is accepted, and later layers wait until you run `approve`. The checkpoint table says Structure comes "after layers 4–6", so `scenes` carries `structure` too (the original config tagged only acts and chapters). The `voice` and `final` checkpoints are not tied to a layer; they are reached by the prose and assembly steps.

Config is merged in this order: built-in defaults, the host `config.yaml` (`BOOKFORGE_CONFIG`, or `platform/bookforge/config.yaml`), then `<series>/config.yaml`. Unknown keys are errors. `platform/bookforge/config.example.yaml` lists every default.

The values above are starting points, not tested settings. Tune them on chapter 1 and the benchmarks.

## Building it with Claude Code

Bookforge is built inside the Jarvis repository by Claude Code, one milestone at a time, following `CLAUDE.md` and `BUILD_SEQUENCE.md` Phase 14. There is no separate `SPEC.md` or repo-level `CLAUDE.md`; this file is the spec.

**Setting up colibri.** colibri ships [docs/AI_SETUP.md](https://github.com/JustVugg/colibri/blob/main/docs/AI_SETUP.md) for exactly this; Claude Code can run installation steps 1–5 with it and asks before downloads and system packages. This happens on the mini PC, after Phases 1–2.

**Bookforge-specific build rules** (in addition to the Jarvis `CLAUDE.md` hard rules):
- Python 3.12, standard library first. Dependencies: httpx, pyyaml, typer, pydantic, fastapi, uvicorn, pytest. Anything else needs approval.
- Every layer reads and writes files in the series folder and updates `state.json`. No hidden state. Every accepted step is a Git commit in the series repository.
- All model calls go through `bookforge/llm.py` and are logged to `logs/calls.jsonl`.
- Prompts live in `bookforge/prompts/*.md`, never inline in code.
- Tests use a fake LLM client with recorded responses and a fake web tool; never call real models or the internet in tests. This also means milestones 1–10 can be built and tested before the mini PC is ready.
- Build one milestone at a time; stop and show the result before starting the next.

**Model and service endpoints**
- Writer model: `http://127.0.0.1:8040/v1` (OpenAI-compatible)
- Critic model: `http://127.0.0.1:8041/v1`. (`models.decide.url`, System One at `/v1/systemone`, is not used: see milestone 7.)
- Web research: platform Playwright web tool

**Milestones**

0. Service shell (done): `platform/bookforge/` with `GET /health`, `{data, status}` envelope, venv, requirements, systemd unit, health test, deploy and Caddy wiring for `/bookforge`. Empty frontend placeholder. **Built 2026-11-05.**

1. Skeleton (done 2026-11-05): CLI (`new`, `run`, `status`, `approve`, `doctor`), config, `state.json`, fake LLM client for tests, Git commits through `vcs.py`. The layer runner is a thin loop with an empty handler registry, so `run` stops at the first layer (exit code 2) until milestone 14.3.

2. `llm.py` and `doctor` (done 2026-11-05): real OpenAI-compatible client for both colibri endpoints (3 attempts with 2 s / 4 s backoff on connection errors, timeouts, 408/429/5xx; a reply cut off by the token limit is an error, never silent text), a web wrapper over the Playwright tool (`bookforge/research/search.py`: http/https only, no private or loopback hosts, query encoding, retries), and a call log at `books/<book>/logs/calls.jsonl` with full prompts and replies (gitignored). `doctor` now checks both endpoints, System One and the web tool, including one real page fetch; `doctor --offline` skips the network checks. The `manage_service` start/stop of the critic is not wired up yet.

3. The layer runner with layers 1–3 (north stars, synopsis) and the direction checkpoint (done 2026-11-05). Each layer asks the planner model for its document, checks the structure in code (the seven north-star sections, Realism among them, one page = at most 600 words; synopsis 300–2500 words), and if the check fails asks for a correction, at most `qc.max_revision_rounds` times; unresolved layers are flagged. Review of these three layers is yours, at the direction checkpoint (as in the layer table); the model critic comes in milestone 14.7 and the research step in 14.4 (marked with a TODO in `layers/document.py`).

   - Prompts live in `bookforge/prompts/*.md` (`system`, `series_north_star`, `book_north_star`, `synopsis`, `correct`). Inputs are named slots like `{premise}`. A series can override any prompt by placing a file of the same name in `<series>/workbench/prompts/`. They are first drafts: expect to edit them after reading the first outputs.
   - Inputs: layer 1 reads `premise.md`; layer 2 reads the premise, the series north star and `ledger.yaml` ("none" for a first book); layer 3 reads both north stars. Outputs: `north-star.md`, `books/<book>/north-star.md`, `books/<book>/synopsis.md`.
   - If an output file already exists, bookforge checks it and adopts it instead of calling the model, so you can write a north star yourself. An existing file that fails the check is never overwritten; fix it or delete it to have it regenerated.
   - `run` stops once all three are accepted and lists the files to review. Edit them freely. `approve direction` commits everything in the series, including your edits, and tags `b1-direction-approved`.

4. The research step inside the runner: questions, web-tool search, fetch, notes, `sources.jsonl` (done 2026-11-05). After a layer's document is written, the step (`bookforge/research/`) works like this:

   - The planner model proposes at most `research.max_questions` factual questions the document depends on, each with a short search query and a `sensitive` flag (history, medicine, real places, real people). Questions already answered, in the series or the book, are skipped; unanswered ones are retried on the next run.
   - **Where results come from (`research.source`).** The default is `auto`: **SearXNG** if it answers, otherwise Wikipedia only (with a warning in the log and a `searxng` warning in `doctor`). SearXNG is a self-hosted metasearch engine (docker, `scripts/setup-searxng.sh`, localhost port 8060, see STACK.md) that asks several search engines at once and returns JSON, so a question reaches the real web; Google, Bing, Brave and DuckDuckGo answer a headless browser with block pages, so they cannot be asked directly. Bookforge sends the search request through the platform web tool like every other page (so it is logged in the internet log), with one narrow exception: the web wrapper normally refuses local addresses, and the configured `research.searxng_url` is the only local address it will fetch. Result pages are then fetched through the web tool as usual (Wikipedia articles through Wikipedia's text API, quoted against that text). Other sources: `wikipedia` (article titles and text from Wikipedia's API; thin on niche topics), `duckduckgo` (a search-engine results page; usually blocked). When SearXNG finds nothing, the error names the engines that did not answer and why (for example `google (CAPTCHA)`), so a block is never mistaken for "nothing found".
   - **Reading the results (found on the first real run: 2 of 18 questions answered, from irrelevant pages; then, with SearXNG, a round of tuning from `research-test`).** Results from `research.skip_domains` (social media, shops, video, forums, and paywalled or archive sites such as JSTOR, ResearchGate, Ancestry and rootsweb by default; a `config.yaml` that sets its own `skip_domains` replaces the list) and Wikipedia pages that are not articles (Category:, File:, Talk:, Special: and the like, English names) are not read. The rest are ranked by how many of the question's words, the setting's era words (`1880s`, `1883`, `19th century`, `victorian`) and place words (`England` also means english, british, london and `.uk` addresses) appear in the result's title, excerpt and address (ties keep the search engine's order), list articles last, and each site's first result before a second one from the same site. Then, unless `research.model_pick: false`, the model is shown the remaining titles and excerpts (`research_pick` prompt) and names the ones to read first (`pages_per_question` + 2); those are read in its order, the rest follow in word-match order. Word counting alone put a page about Ellis Island above the one about an English customs house; the model sees at once that a result is about the wrong place. If the model cannot be asked or answers badly, the word-match order stands. A page that comes back with practically no text (under 40 characters: script-only pages and block pages) is a failed fetch and does not use up a page slot. Reading stops once `research.facts_per_question` (3) facts are kept from at least `research.sources_per_question` (2) different pages, or `research.pages_per_question` (5) pages have been read. A long page is not cut at its first characters (menus, notices) but shown as the windows of 1,500 characters that mention the question's words, up to `research.page_max_chars`. A fact is still kept only with a verbatim quote from the page, a claim audit and a relevance check against the setting. **Claim audit (`research.check_support`, default on):** one small call per page with facts shows the model each claim next to its own quote and nothing else, and drops any claim that says more than its quote (a person, role, place, date, number or cause the quote does not state, or a claim about a clerk whose quote is about a comptroller); it is separate from the relevance check because a focused question catches what a combined one let through (found by `research-eval`: "steamers could not ply at 8 am" against a quote about later in the day). If the audit cannot be done the facts are kept. The relevance check says why it drops a fact, keeps a fact about the setting's own time and place or a practice the page shows lasted into it, keeps a closely related role or procedure in the same institution as the question's subject (a question about a clerk is helped by facts about the officers around the clerk), and does not drop a fact only because a word in it sounds old (tuned after the first real `research-test`, where it dropped tidesmen from one page and kept the same tide-waiters from another). **`python -m bookforge research-test <series> "question" [--query "words to search"] [--setting "England, 1880s"]`** runs one question through exactly this code and prints the source, what was searched, the results and the order they are read in, each page (characters read, facts the model reported, how many were dropped because the quote was not on the page or did not fit the setting, the facts kept with their quotes, and each dropped fact with the reason), and the verdict; it stores nothing and exits 1 if no fact was kept. **`--show-pages`** also prints, for each page, the text the model was shown and its raw reply, to tell a page with no facts from a reader that missed them. A question that could not be answered says what happened to every page, not only the last one: how many were read with no supported facts, and for each page that could not be read the site and the error (for example `no supported facts in the 3 page(s) read; 2 page(s) could not be read (www.jstor.org: no readable text ...)`). Use it to tune queries, sources and skipped sites in a minute instead of rerunning a layer. A page that fills itself in with scripts (FamilySearch, some archives) used to come back empty; the shared platform web tool now waits, when a page has under 200 characters of text, for the network to go quiet (up to 8 s) and for text to appear (up to 3 s more). A normal page is read at once. A page that redirects itself while it is being read ("Execution context was destroyed, most likely because of a navigation") is read again once the new page has loaded (up to three times). Sites that block the headless browser by its user agent are still blocked.
   - The notes model (`research.notes_model`, default the fast writer) extracts up to 3 facts per page, each with a quote. **A fact is kept only if its quote appears verbatim in the page** (case, spacing and typographic quotes ignored), so the model cannot add facts the page does not contain. Page text is given to the models as data, never as instructions.
   - **Relevance (found on the first real run).** A real quote is not enough: the first run kept modern UK court-adviser and police-medal facts for a 19th-century town. Now each question carries a `setting` (the time and place an answer must fit, for example `England, 1880s`), the search query includes the era or place, and the page reader is told to skip facts about another period or place and that returning no facts is fine. A second call (`research_check`, skipped with `research.check_relevance: false`) then judges each page's facts together against the question, the setting and the start of the story; a reply it cannot read keeps nothing. Articles titled `List of ...`, `Index of ...` and similar are read last. A question whose facts were all dropped is shown in the notes as `No answer found: N fact(s) found but none fit the question and the story's setting`.
   - Files, per scope (`research/` for the series, `books/<book>/research/` for a book): `sources.jsonl` (one fact per line: id, claim, url, title, date fetched, quote, layer, question, sensitive), `questions.jsonl` (every question, answered or not, with the reason), and a readable `<layer>.md`. Fact ids are `s-0001` for the series and `b1-0001` for book b1; scenes will cite them.
   - Stored facts (newest first, within `research.notes_max_chars`) are shown to later layers as reference data in the `{research_notes}` slot.
   - Research is best-effort: a blocked search or unreadable page costs that question, and the layer's note reports it (for example `research: 1/3 questions answered, 2 facts (search … blocked or empty)`). Set `research.required: true` to make a layer fail instead when none of its questions has an answer; the document is kept and the rerun retries the research. `research.enabled: false` turns it off.
   - The shared web tool now returns the page's links in `ToolResult.metadata["links"]`, which is how result links are found. Without it, only the page text was available.

5. Layers 4–6 and the bible: constants, state tracks, timeline, state-at-a-point lookups (done 2026-11-05; formats under *Story bible*). The checks are structural only (ids, counts, references to the cast, track guards, timeline order); the critic's review of these layers was added in 14.7 (see below). Two choices the spec left open: the cast and world are created by the chapters layer, and the scenes layer researches `research.scene_questions` (default 2) questions per chapter before planning its scenes, so scenes can cite fact ids.

6. Briefing builder with `deps.yaml`, the prose layer, and the mechanical checker (done 2026-11-05). The checks described here are the first layer; the judge, continuity, critic, revision loop and extraction were added in 14.7 (see below), so a scene's best draft is accepted if it has no blocking problem left after them, and flagged otherwise.

   - **Briefing** (`bookforge/briefing.py`): the six parts of the briefing pack, within `briefing.max_tokens` (an estimate, about 3.5 characters per token). Over budget, it is cut in a fixed order: older chapter summaries, research notes, the previous scene's tail, sample passages, the style guide. The north stars, beats and story state are never cut; if they alone do not fit, the build fails with the largest parts named. `python -m bookforge briefing <series> b1.ch04.s3 [--full] [--tokens N]` shows the size of each part, or the whole text.
   - **deps.yaml** (per scene, written whenever a scene is drafted) records what the scene was built from as `id@fingerprint`. A fingerprint is the first 8 hex digits of the SHA-256 of the record's content, not a counter, so a hand edit counts as a change (this replaces the `@v3` style above). Tracks are fingerprinted by their state *at that scene*, so editing a later chapter's entry does not mark earlier scenes stale. Keys: `scene`, `parent`, `north_stars`, `style`, `bible`, `research`, `timeline`, `previous`, `summaries`. Staleness handling is described under item 8 below.
   - **Prose layer** (`bookforge/layers/prose.py`), per scene: write `layers.prose.drafts` drafts (the fast model; draft *i* uses the *i*-th temperature), run the mechanical checks on each, keep the one with the lowest score (a blocking problem costs 100, a warning 1; a tie goes to the first draft) as `final.md`, then write a 3-5 sentence `summary.md` with the fast model (if that fails, the plan's purpose stands in; `review.json` records which). Files per scene in `books/<book>/scenes/chNN/sN/`: `draft-N.md`, `final.md`, `summary.md`, `review.json` (chosen draft, all mechanical reports, briefing size), `deps.yaml`. Each scene is committed as `b1.ch05.s2: drafted, checked, accepted` (or `drafted, flagged`).
   - **Voice checkpoint.** Chapter 1 is written first and the run stops (exit code 0) with the files to review. Read it, edit `style/guide.md` and `style/banned.txt`, put sample passages in `style/samples/`, use `python -m bookforge rewrite <series> b1.ch01.s1` (or `b1.ch01` for the whole chapter) to have scenes written again, and `run` to write them, as often as you like; then `approve voice`. Only then is the rest of the book written. While the checkpoint waits, `run` writes only chapter-1 scenes that are not accepted (nothing, if they all are). **Deleting a scene's files does not make it be rewritten**: an accepted scene is skipped whatever is on disk, so `rewrite` puts it back to pending (removing its drafts, text, summary, review, deps and what was observed from it) and the prose layer back to unfinished. Text you wrote yourself is kept unless `--force`; everything stays in Git history.
   - **Flagged scenes** do not hold up the other scenes. When the book is finished the layer is `flagged` (exit code 1) and lists the scenes that need you; the next `run` rewrites only those. A `final.md` you write yourself is checked and adopted, never overwritten. Drafts left on disk by a stopped run are reused.
   - **Mechanical checks** (`bookforge/qc/mechanical.py`, no model): *blocking*: banned phrases, assistant chatter or formatting (headings, lists, "Scene 3:" labels, code fences), a cut-off ending, a length under half the minimum or over twice the maximum; *warnings*: phrases repeated from earlier scenes or inside the scene, overused words (names excluded), monotone sentence rhythm, over-long sentences, repeated sentence openings, dialogue share outside the range, a scene that opens by repeating the end of the previous one, tense and point-of-view slips and head-hopping. The last three use English-only heuristics and are skipped for other `book.language` values. Every finding carries the character span, for passage-level revision in 14.7. `python -m bookforge check <series> b1.ch01.s1 [--file x.md]` runs them on a scene or a file.
   - **`style/banned.txt`** is created with a starter list of common model clichés (English). It is yours: edit it, and add to it at the voice checkpoint. A line is a phrase (matched ignoring case and line breaks) or `re:` plus a regular expression; `#` starts a comment. The list is also given to the writer model.

7. Continuity (System One), critic, pairwise judge, revision loop, extraction into `observed` (done 2026-11-05). Quality control for a scene now runs cheapest layer first (`bookforge/qc/`):

   1. **Mechanical** on every draft (14.6).
   2. **Judge.** If more than one draft has no blocking problem, the planner model compares them pairwise, A against B and then B against A; if the two runs name different drafts the pair is a tie. With three drafts every pair is judged. Wins decide; ties go to the lower mechanical score, then the lower draft number. A judge that fails falls back to the mechanical score.
   3. **Continuity** on the chosen draft, only if it has no blocking mechanical problem. One yes/no question per relevant fact: every tracked state at the scene, the fixed facts of the people and places in it, the rules of the world, and the research facts it cites; changes marked `must_show` also get a "shown on the page?" question. P(contradiction) is the confidence for a yes and 1 - confidence for a no. A yes whose quoted evidence is really in the scene and whose P is above `qc.continuity_flag_threshold` is a flag; a hesitant answer, or a yes without quotable evidence, is only "unsure" (recorded, never revised). A `must_show` change that is not shown is repaired by **inserting a short passage** that shows it (the writer is given the change and an outline of the scene, and says after which paragraph it goes; `prompts/insert.md`). A state that **begins in this scene** gets only that "shown" question and no fixed-fact question, because the scene may start before the change; and your approved **decisions about the world** are asked about as **warnings only** (recorded as unsure, never revised). Each problem goes to the revision prompt specifically: the exact words quoted, the fact they contradict, what to do, and anything you told the writer about it.
   4. **Critic** on the chosen draft, only if the cheaper layers passed. Six criteria scored 1-5 (stakes, voice, show_dont_tell, pacing, dialogue, beats_covered) and the three weakest lines quoted. A quote that is not in the scene is sent back. The rubric is `prompts/critic_rubric.md`; to calibrate the critic against your own reading, copy it to `<series>/workbench/prompts/` and reword it. The critic is given the scene, its beats and the voice (style guide and one sample), never the bible.
   5. **Revision**, at most `qc.max_revision_rounds` rounds. Flags come from blocking mechanical problems (banned phrases, a cut-off ending, chatter, formatting), continuity contradictions, and the critic's weakest lines when a score is under `qc.critic_min_score`. The fast model gets the paragraph around each flag, the problems, and (for the critic) the rubric line; only that paragraph is replaced, and several flags in one paragraph cost one call. Short chatter and formatting lines are deleted instead. A revised paragraph must stay within 0.4x-2.5x of the original length and must not contain a banned phrase. Layers 1-2 then run again; the critic runs again only if its scores were under the minimum.
   6. **What is left** (a blocking problem the revision could not fix, an unmet `must_show`, scores still under the minimum, a scene too short) is written to `review.json` as `blocking`, the scene is flagged, and its latest text is kept as `revised.md` (a flagged scene's drafts are rewritten on the next run).
   7. **Extraction.** After a scene is accepted the fast model reports, for each track with a state at the scene, what the prose shows (`extracted.yaml`, and into the track's `observed`). A verdict needs quotable evidence from the scene. A clear difference from the plan is a *gap*: recorded and counted in the scene's note, but it does not block the scene; a deliberate change of plan becomes a change request (item 8 below).

   Layers 4-6 get the critic's **plan review**: each piece (the acts, the chapters of an act, the scenes of a chapter) is reviewed against its parent, both north stars and the state tracks, and problems are sent back for correction like structural ones. Problems still open after the correction rounds never fail the layer: they go to `books/<book>/reports/review-notes.jsonl` and are counted in the layer's note. The state-track check ("System One" for plans) is part of this one critic call.

   **System One.** Its request shape could not be verified, so the continuity questions are answered by the planner model. Its confidence is self-reported, which is less reliable than a probability read from the model, so the 0.3 threshold is applied to it conservatively. If colibri's endpoint turns out to exist, only `qc/decide.py` needs to change. `models.decide.url` is unused and `doctor` only checks that it answers.

   **Cost.** A scene can now take 15-25 model calls (2 drafts, 2 judge, 2-5 continuity batches, the critic, revisions and re-checks, a summary, an extraction), most of them on the slow planner model. Each model-based layer has a switch under `qc:` to make a run cheaper. `python -m bookforge review <series> b1.ch04.s3` shows how a scene went: draft choice, scores, flags, revisions, gaps.

8. Staleness and change requests (done 2026-11-05): `bookforge/stale.py`, `bookforge/changes.py`, commands `stale` and `changes`.

   - **Detection.** Building a written scene's briefing again gives its current fingerprints; each difference from its `deps.yaml` is a reason (`bible: entity:anna changed`, `north_stars: b1 changed`, `previous: b1.ch01.s1 changed`). Reasons count for the keys `scene`, `parent`, `north_stars`, `style`, `bible`, `research`, `timeline` and `previous`. `summaries` is deliberately left out: a regenerated summary is never word-for-word the same, so counting it would mark the rest of the book stale after every patch; what matters in a summary is held by the tracked bible. `python -m bookforge stale <series>` lists everything out of date and why, marks those scenes `stale` in `state.json`, and exits 1 if anything is stale (a scene that is fine again goes back to `accepted`). The prose layer leaves stale scenes alone and says how many there are.
   - **Planning layers.** Approving the structure checkpoint saves `books/<book>/plan-deps.yaml` (a fingerprint of every act and chapter, and which version of its parent each chapter and scene was planned from). Afterwards a chapter whose act changed, and a scene whose chapter changed, are listed as "plan out of date". They are not repaired automatically: review them, then `stale --accept <chapter or scene id>`. Edits made before the approval are part of the approved plan and are not reported.
   - **Fixing** (`stale <series> --fix [--only <scene>]`), scene by scene in book order, each scene looked at when its turn comes so that a patch that changes the end of one scene is seen by the next:
     1. *Re-check.* The mechanical checks, plus the continuity questions unless the only change is in `style`. If nothing is wrong, the fingerprints are refreshed and the scene is accepted again without being touched (no new version).
     2. *Patch.* Only the passages that contradict the new version are rewritten, with the same passage reviser as the revision loop. The result is checked again; then a new summary and a new extraction follow, and the scene's version goes up. `review.json` gets a `stale_fixes` entry.
     3. *Redraft.* When the scene's own plan changed (its beats, purpose or timeline entry), or the patch could not fix it, the scene is written again from scratch.
     - A continuity check that cannot answer leaves the scene stale rather than guessing. A change to `style` does not rewrite anything that still passes the mechanical checks; to have a scene rewritten in a new voice, `rewrite` it.
     - **Text you wrote** (`review.json` says `source: adopted`) is never patched or redrafted. If it no longer agrees, the scene is flagged with the reasons. `stale --accept <scene>` says a scene is fine as it is and refreshes it with no model call.
   - **Change requests** (`books/<book>/change-requests/cr-NNNN.yaml`). When extraction finds a gap (the prose shows a tracked state differently from the plan), one request is filed per scene and track. It holds the proposing scene, the track, what the plan says, what the prose shows with its quotation, and the scenes whose state for that track would change (`affects`, the proposing scene included). Scope is `within_chapter` if all of them are in the proposing scene's chapter, otherwise `later_chapters`.
     - With `qc.critic_may_accept: within_chapter` (the default) a request inside one chapter is applied at once (`decided_by: auto`); `never` makes every request wait. Anything that reaches another chapter always waits. No model is involved in this decision. Acts, north stars and other books are not touched by change requests: only the track's plan.
     - `python -m bookforge changes <series>` lists them; `--approve cr-0001` adds a plan entry to the track from the proposing scene on (the track's version goes up), which makes the scenes that depend on it stale; `--reject cr-0001` keeps the plan, and the proposing scene is then listed as stale with the rejection as its reason, so `stale --fix` patches the passage to agree with the plan (the request is then marked `fixed`).
     - Git: the requests and the track change are committed with the scene or the command that made them. The spec's idea of a branch per change request is not used: a request is a small file, and the stale scan shows what it would touch.
   - Not done here, left for later: the critic accepting changes through a model call (the rule above is mechanical), change requests for anything other than a track state (beats, acts), and acting on a hand edit of `final.md` (the next scene notices a changed ending through `previous`, the edited scene itself is not re-checked).

9. Morning report, assembly, `bench` command and benchmark scenes (done 2026-11-05): `bookforge/report.py`, `assemble.py`, `bench.py`, the shipped `benchmarks/*.yaml`.

   - **Morning report.** `run` writes `books/<book>/reports/<date>.md` at the end of every run, however it stopped, and prints the path (a second report on the same day gets a time suffix). `report <series> [--write]` prints one at any time. It reads only files the pipeline already keeps, so it costs no model calls. Sections: *Progress* (layers, scene counts, words against the target; model calls, failed calls, time and tokens, from `logs/calls.jsonl`, counting only this run when written by `run`; tokens read "the server did not report usage" if colibri sends none); *Needs you* (waiting checkpoints, flagged layers, flagged and stale scenes with the reason, pending change requests with the command to decide them, plan items out of date, unresolved plan-review notes); *Unsure* (continuity answers that were hesitant, scenes passing the critic only at the minimum score, gaps between plan and prose); *Suggestions for banned.txt* (four-word phrases found in at least 3 scenes and 10% of them that are not banned yet; names and all-stopword phrases left out; at most 10); *Facts to verify* (research facts marked sensitive, with their source and the scenes that cite them); *Revision samples* (3 before/after passages, chosen by a shuffle seeded with the date so a report is repeatable).
   - **Assembly.** `assemble <series> [--partial]` writes `books/<book>/manuscript.md`: each act a `#` heading, each chapter a `##` heading, scenes within a chapter separated by `* * *`; no title page or styling (export adds those). It refuses unless every scene is accepted and nothing is stale or out of date, and names what is in the way. `--partial` writes the accepted scenes to `manuscript-partial.md` with no tag and no checkpoint. A full assembly is committed, reaches the `final` checkpoint, and is tagged `<book>-draft-N` when the text differs from the last assembly. `run` assembles by itself when every layer is accepted. Read the manuscript, then `approve final`.
   - **Benchmarks.** Five briefs ship in `platform/bookforge/benchmarks/` (quarrel, pursuit, reunion, discovery, farewell); `<series>/workbench/benchmarks/*.yaml` adds more, and a file with the same id replaces a shipped one. A brief is self-contained (purpose, point-of-view character, setting, cast with facts, beats, word range): no bible and no earlier scenes, so only the prompt, model or settings can change the result. `bench <series> [--only id] [--no-judge] [--accept [--force]]` writes one draft per brief with the writer (first draft temperature, the series' style guide, sample and banned list), checks it mechanically, and saves it under `workbench/experiments/bench-<stamp>/` (`<id>.md` and `results.json`, committed). Compared with the accepted run (`workbench/experiments/bench-accepted.json`), each brief gets the mechanical change and a pairwise judgment (new against old, run twice with the order swapped; a split is a tie; a judge that fails is "unknown", not a loss). The output lists which settings differ from the baseline (writer model and temperature, the `prose` and `prose_system` templates, style, banned list). **A change ships** if no brief gained a blocking problem it did not have and it does not lose more briefs than it wins; `bench` exits 1 otherwise. `--accept` makes the run the baseline, refusing a losing one unless `--force`. The first run has no baseline and just reports; accept it to start one.
   - Not done here: judging only the briefs a change could affect, your own blind vote on benchmark pairs, and A/B tests of two prompt versions side by side (workbench, 14.13).

10. Service API (done 2026-11-05): `platform/bookforge/bookforge/api.py` (router), `jobs.py`, `ops.py`; mounted by `main.py`.

   - **One library, two front ends.** The multi-step operations the CLI runs (`run` with assembly and report, `stale` with accept/fix, `bench`, approving a checkpoint, deciding a change request) now live in `bookforge/ops.py`; the CLI and the API both call them, so they cannot drift apart.
   - **Routes** (all under `/api`; Caddy strips `/bookforge`; envelope `{data, status}` / `{error, status, detail}`; a library error is a 400 with its message, an unknown series, book, scene, report or job is a 404). Series and book ids are validated before they touch the file system: series names are `^[a-z0-9][a-z0-9_-]{0,63}$` under `BOOKFORGE_DATA_DIR`, report names must be `*.md` with no path.

     | Route | Does |
     |---|---|
     | `GET /doctor?offline=&series=` | the same checks as `doctor` |
     | `GET /series`, `POST /series {name, premise, book}` | list; create (409 if it exists) |
     | `GET …/books/{b}/status` | layers, checkpoints, scene counts by status, pending change requests, whether a manuscript exists, the running job |
     | `GET …/scenes`, `GET …/scenes/{id}` | list with status, version, words; one scene with plan, text, summary, `review.json` and its change requests |
     | `DELETE /series/{s}`, `DELETE …/books/{b}`, `GET /trash`, `POST /trash/{name}/restore`, `POST /trash/empty` | delete a series (moved to the trash) or a book; see *Deleting* below. Refused with 409 while a job runs on the series |
     | `GET …/documents`, `GET …/documents/{key}` | the files you review, read-only: premise, both north stars, synopsis, acts, chapters, scene plans, cast and rules, tracks, timeline, style guide, banned phrases, research notes. A fixed list of keys, never a path from the request; a file that is only a starter placeholder reads as "not written yet"; files over 400 KB are cut and say so |
     | `GET …/report`, `…/reports`, `…/reports/{name}` | the morning report now; the saved ones |
     | `GET …/manuscript[?partial=true]` | the assembled Markdown |
     | `GET …/stale` | what is out of date and why (reads only: it does not mark scenes stale) |
     | `GET …/changes`, `POST …/changes/{id}/approve\|reject` | change requests; decide one |
     | `POST …/approve/{checkpoint}` | approve a waiting checkpoint |
     | `POST …/assemble {partial}` | assemble now (no model calls) |
     | `POST …/run {until}`, `POST …/stale/fix {only, accept}`, `POST …/bench {only, judge, accept, force}` | start a **background job**; answer 202 with the job |
     | `GET …/jobs`, `GET …/jobs/{id}` | job history and one job |

   - **Jobs.** A run takes hours, so a request starts a thread and returns the job record (`id`, `kind`, `status`: running / done / failed / interrupted, `started`, `finished`, `params`, `result`, `error`). `result` holds what the CLI would print (for a run: where it stopped and why, the layers that ran and their notes, the assembly, the report path). Records are saved to `books/<book>/logs/jobs/<id>.json` at start and at end; one still saying `running` that this process does not know is shown as `interrupted` (the service restarted mid-run; start the run again, finished scenes are kept).
   - **One job at a time per series** (the series is one Git repository). While one runs, anything that changes the series' files (approve, decide a change request, assemble, start another job) answers 409; reads always work. The job worker is a thread in the service process, so restarting `platform-bookforge` stops a run in progress.
   - **Added in 14.11 for the dashboard:** `GET …/structure` (acts > chapters > scenes with status), `GET …/tracks` (plan and observed per track, with the scene order), `GET …/research` (facts with the scenes that cite them), `drafts` in the scene detail, and Web Push: `GET /push/key`, `POST /push/subscribe`, `/push/unsubscribe`, `/push/test`.
   - **Not done here:** authentication (the app sits behind the platform's reverse proxy and Tailscale, like the other apps), live progress inside a run (the dashboard polls `status`), editing files through the API, and cancelling a job.

**Deleting** (`bookforge/deletion.py`, added after the first real run). `python -m bookforge delete <series> [--book b1] [--yes]`, `python -m bookforge trash [<data dir>] [--restore NAME | --empty]`, the API above, and buttons in the dashboard (a Delete button on each series, a Trash list with Restore and Empty trash on the series page, "Delete this book" at the bottom of a book's Overview; each asks to confirm, none asks you to type the name).
- **A series** is moved to `<data dir>/.trash/<name>-<timestamp>/`, not deleted: the series folder is its own Git repository, so Git cannot bring it back. Restore moves it back under its original name (refused if that name is in use); Empty trash removes what is in the trash for good.
- **A book** loses its folder `books/<book>/` and its entries in the series-wide files: its plan and observed entries in `bible/tracks.yaml` (a track only that book used goes entirely), its scenes in `bible/timeline.yaml`, and its scores and threads in `workbench/`. The cast and rules, style, banned phrases, premise and other books stay. Rules in `workbench/rules.yaml` scoped to the book are not deleted; the result counts them ("no longer apply"). It is a Git commit (`delete book b1: ...`), so the book can be recovered from history (`git checkout <commit before> -- books/b1`). Deleting a series' last book is allowed and leaves an empty series.

11. Dashboard (done 2026-11-05): `frontend/bookforge/` (React 18, Vite, Tailwind 4, no router or data library), `bookforge/push.py` on the service side.

   - **A pure client of the API.** It keeps no state of its own beyond what is on screen; every number comes from a request. Hash routes (`#/series/<series>/<book>/<tab>/<id>`), so the static files need no server-side fallback. Tested at 390 px: no horizontal scroll on any view, 40 px minimum touch targets, the tab row scrolls sideways.
   - **Views.** *Documents* (added after the first real run: you could not read the direction files in the app): the files above grouped as Direction, Structure, Story bible, Voice and Research, read-only; the Overview's checkpoint card links to exactly the files that checkpoint asks you to review, next to the Approve button. *Series*: the series on disk, create one from a premise. *Overview*: the running job (the page polls every 4 s while a job runs, 20 s otherwise), waiting checkpoints with an Approve button, Run (to the next checkpoint or `until` a layer) and Assemble, scene counts, layers with their notes. *Progress*: the tree act > chapter > scene as coloured dots (accepted green, flagged red, stale amber, pending grey); chapters with a flagged or stale scene open by themselves. *Scene*: text and summary; **Compare** (both drafts side by side on a wide screen, stacked on a phone, the chosen one marked, the judge's wins and both orderings of each pair, the critic's scores with the weakest lines quoted and marked in the chosen draft); Review (what needs you, each revision round as a before/after, continuity flags and doubts, gaps between plan and prose); Plan (beats and the change requests from this scene). *Inbox*: change requests as a plan/prose diff with Approve and Reject, what is out of date with Fix all, and the morning report. *Tracks*: each state as a bar across the scenes with a segment per plan entry, and a dot at every scene where the extraction compared prose and plan (green agrees, red differs, grey unclear). *Research*: facts with their quotation and source, filtered by search text, by the scene that uses them, and by "verify first". *Read*: the manuscript. *Jobs*: the history.
   - **Web Push.** "Notify me" in the header registers the browser (service worker `sw.js`, scope `/bookforge/`). The service sends a notification when a run stops at a checkpoint, a layer needs you, the book is finished, a job fails, or a benchmark loses; tapping it opens the series. VAPID keys and subscriptions are kept in `<data dir>/push.db`, outside the series folders (the trading app's scheme, but not its database, so the keys never enter a series' Git history). A browser that blocks notifications shows "Blocked"; iPhones need the page added to the home screen first. Browsers only offer service workers / push on https, so open the dashboard at the `https://<host>.<tailnet>.ts.net/bookforge/` address (see STACK.md Caddy section, SETUP.md "Enable HTTPS"); on plain `http://<ip>` the button is hidden.
   - Not done here: editing a scene in the browser (v3), the workbench (13), dragging track bars to preview a change, a link out to colibri's own dashboard, and component tests for the frontend (checked with the type checker, the build and screenshots against a seeded service).


12. Export (done 2026-11-05): `bookforge/export.py`, `data/scene-break.lua`, `data/epub.css`, command `export`, API `POST …/export`.

   - **Command.** `python -m bookforge export <series> [-f docx|epub|pdf|companion|all] [--draft]` builds from `books/<book>/manuscript.md` with Pandoc (3.1 or newer). It refuses unless the `final` checkpoint is approved; `--draft` overrides that and marks the export a draft. Output is `books/<book>/exports/<tag>/` with the files and an `export.json` (formats, files, skipped formats, warnings, the manuscript's SHA-256, the commit, the Pandoc version, the PDF engine, the metadata). Exports are not kept in Git (`books/*/exports/` is added to the series' `.gitignore`): they can be rebuilt from the tag.
   - **Git.** Before building, the manuscript and the matter files are committed (`b1: export source (<hash>)`), so what is built is exactly what the tag points at; after a successful build the commit is tagged `b1-export-<date>` (`b1-export-draft-<date>` for drafts; `-2`, `-3` if the name is taken) with the file names and the manuscript's hash in the tag message. Nothing built means no folder and no tag. If `manuscript.md` no longer equals what the accepted scenes assemble to (you edited it at the final read, or scenes changed afterwards) the export goes ahead from the file and says so in its warnings: the file is the single source.
   - **Settings** (`export:` in the config): `title` (falls back to the series folder's name, with a warning), `subtitle`, `author`, `rights`, `pdf_engine` (`auto` picks the first installed of Typst, XeLaTeX, LuaLaTeX), `page_width_in` / `page_height_in` (6 x 9), `margin_in`, `font_size_pt`, `reference_docx`, `cover_image`. The book language becomes the document language.
   - **Front and back matter.** Markdown files in `books/<book>/matter/front/` and `.../back/`, added in file-name order around the manuscript (`01-epigraph.md`, `02-dedication.md`, ...). The title page comes from the metadata. Nothing format-specific is ever written into the pipeline's own files.
   - **DOCX** is a standard manuscript: Times New Roman 12 pt, double spaced, indented paragraphs (none after a heading or scene break), black headings, acts as the top level. The styles are made by patching Pandoc's default reference document at export time; `reference_docx` replaces them with your own.
   - **EPUB** (EPUB 3): table of contents, one file per chapter, a small stylesheet, the cover image if set. A cover path that does not exist fails that format.
   - **PDF** is the print interior at the configured trim size. Typst gets the page size, margins, justification and first-line indent from an include-in-header file; the LaTeX engines get `geometry`, the book class and parts as the top division. **Not verified:** no PDF engine was installed on the development machine, so the PDF commands are tested only by their arguments, never against a real Typst or LaTeX. Run one export on the mini PC and look at it before trusting the layout. Without an engine, `export` makes the other formats and reports `skipped pdf`.
   - **Scene breaks** (`* * *` in the manuscript) are centred asterisks in every format, through one Lua filter, not a ruled line.
   - **Companion** (`<book>-companion.md`, and `.pdf` with an engine): characters with their fixed facts and how their tracked states change through the book, places, other things, rules of the world, a timeline table (day, time, scene, chapter, viewpoint, place), the act and chapter outline, and the series ledger once it has content. Built only from the bible files, so it shows what the story bible says, which may differ from what the prose says where there are gaps.
   - **API and dashboard.** `POST …/export {formats, draft}` is a background job (kind `export`); `GET …/exports` lists them; `GET …/exports/{name}/{file}` downloads a file (names are checked: no path, no hidden file, `export.json` is not served). The Read tab has an Export card with the formats, a draft switch and download links. `doctor` warns when Pandoc or a PDF engine is missing.
   - Not done here: front-matter templates (a title page is the metadata only), a covers/ISBN/barcode workflow, store-specific EPUB validation (run EPUBCheck yourself before uploading), and checking that nothing resembles existing works too closely (a human task at the final checkpoint).

13. The workbench (done 2026-11-05, in the order the spec gives): `bookforge/rules.py`, `rules_ai.py`, `xray.py`, `studio.py`, `ab.py`, `calibration.py`, `arc.py`, routes in `api_workbench.py`, the **Workbench** tab of the dashboard. Everything it writes is a file under `<series>/workbench/` (`rules.yaml`, `prompts/`, `experiments/`, `calibration.yaml`, `threads.yaml`) and is versioned with the series. All of it was checked with scripted models and, for the screens, at 390 px against a seeded service; none of it has met a real model.

   - **Rules** (`workbench/rules.yaml`; fields id, type, scope, target, severity, text, example, phrase, enabled). Types and what enforces them: *banned_phrase* is a mechanical check (a phrase, or `re:` plus a regular expression) and goes into the writer's "never use" list (block and warn only); *style_rule* and *character_voice* go into the writer's briefing ("The author's rules for this scene") and into the critic's prompt, where a broken MUST rule caps its criterion at 2; *hard_constraint* becomes an extra continuity question ("Author's rule <id>: ...") on every scene it applies to. Severity: `block` fails the check and is revised (phrase rules join the revision's own banned list); `warn` is reported; `note` is recorded and costs nothing (a mechanical `note` issue is never counted in the score). A `warn` or `note` hard constraint is recorded as an unsure answer and never revised. Scope: series, book, character (scenes where the character is present or the viewpoint), scene.
   - **Staleness.** A rule that applies to a scene is part of its `deps.yaml` (style rules and phrase rules under `style`, hard constraints under `bible`), so editing a rule marks the scenes it touches stale: a style or phrase rule needs only the mechanical re-check (a blocking phrase is patched out), a hard constraint also the continuity questions. A scene with no applicable rule has no extra entry, so books written before the rules panel do not go stale.
   - **How often a rule fired** (`rules.stats`, read from each scene's `review.json`): banned phrases from the final mechanical report, hard constraints from the continuity flags and "yes" doubts; style and voice rules are judged by the critic and have no count. **Rule health** lists rules that never fire (after 5 written scenes), fire in 80% or more of them, contradict (a phrase that appears in your own sample passages or in another rule's example), or duplicate another phrase.
   - **Test before saving** (`POST …/workbench/rules-test`, a job): a phrase rule is matched exactly against the written scenes of chapter 1 (up to five); other types ask the planner model per scene, and a violation counts only with a quotation that is really in the scene. **Feedback to rule** (`rules-propose`, a job): a passage and your comment become a proposed rule (type, scope, target, severity, text, example) made consistent with the scene (a character voice gets that character as its target); it is not saved until you edit and save it.
   - **Briefing preview and X-ray.** `GET …/workbench/briefing/{scene}`: the exact briefing with the size of each part against the budget. `GET …/xray/{scene}`: input findings with no model call (a character missing from the cast, no style guide or samples, no previous text, no timeline entry, parts cut to fit the budget, `must_show` changes, rules that apply). `POST …/xray/{scene}` (a job) also asks the planner model which planned beats are on the page; a beat counts as done only with a verified quotation ("beat 3 never happened"). The **diagnosis** names one cause: *missing input* if any input finding is a problem or warning; else *weak prompt* if beats are missing and you have overridden `prose` or `prose_system`; else *model limit*; else none.
   - **Prompt studio.** Every template with its slots; your override is saved to `workbench/prompts/<name>.md`. An override may use only slots the shipped template has (otherwise the code could not fill it: refused); leaving a slot out is allowed and warned about. "Back to shipped" deletes the override.
   - **A/B tests** (`POST …/workbench/ab`, a job; `prose` and `prose_system` only). The current prompt (A) and your candidate (B) are both run on the benchmark briefs; each pair gets the mechanical numbers and the pairwise judge (twice, order swapped). The experiment folder `workbench/experiments/ab-<stamp>/` holds both prompts, their diff, every text and `results.json`. **Your blind vote:** the two texts are shown in a random order per benchmark; which is which, and the judge's verdict for that benchmark, appear only after you have voted on it, and the judge's totals only after you have voted on every pair. "Adopt the candidate" saves it as your override.
   - **Calibration.** You score scenes 1-5 on the critic's six criteria (`workbench/calibration.yaml`); per criterion the chart shows the mean absolute difference, the bias and the share within one point, and the ranking of the scenes you both scored is compared pair by pair. More than one disagreeing pair (with at least three compared) says to reword `workbench/prompts/critic_rubric.md`, as the spec asks.
   - **Arc.** The tension curve from the chapters' 1-10 field with two warnings (no climax: the highest value is 7 or less, or it comes before the last third; a flat stretch: four chapters or more within one point). Changing a chapter's tension shows the consequence first ("affects 2 scenes, 2 of them written") and writes only on Apply; the chapter changes, so its written scenes go stale. **Thread map** (`workbench/threads.yaml`: id, note, setup scene, payoff scene): a setup with no payoff is red, as is a payoff that comes before its setup or points at a scene that does not exist.
   - **Not built:** the *character arc lanes* (an inner state such as trust or fear as a line across chapters: the bible holds no numeric inner state to draw), dragging a point on the curve (it is a tap and a number, which works on a phone, and it edits `chapters.yaml` directly rather than filing a change request), an arc shape in the book north star to draw the curve over, and linking threads to the series ledger.

**First prompt to give Claude Code**

> Read CLAUDE.md, docs/BOOKFORGE.md and docs/STACK.md. Build milestone 0 (service shell) with tests, and stop when tests pass and show me how to run it. Then propose file structure and data schemas for milestone 1.

Use the regular Claude models in Claude Code to build the tool; the local models are for running it.

## User interface

The UI is built in three levels, each usable on its own; v1 needs no UI code at all. The service API (milestone 10) is what the dashboard and any other client use.

| Level | What | Built in | Enough for |
|---|---|---|---|
| v1: files + editor | Open the series folder in Obsidian or VS Code; Git shows history; edit YAML and Markdown at checkpoints | Nothing extra | The first book |
| v2: local dashboard | React app at `/bookforge`, reached from phone or laptop over Tailscale | Milestones 10–11 | Daily use |
| v3: editing in the UI | Edit a scene in the browser; the edit becomes an observation and triggers staleness checks | Later | Hands-on rewriting |

**Dashboard views (v2)**

- **Progress tree:** series → book → act → chapter → scene, colored by status: accepted, flagged, stale, pending.

- **Checkpoint inbox:** the morning report, change requests shown as diffs, approve and reject buttons that call `bookforge approve`.

- **Draft compare:** two drafts side by side with the judge's verdict and the critic's quoted weak lines.

- **Track timeline:** each state track as a bar across chapters (across scenes once they are planned) (the wound from ch4 to ch10), with marks where `observed` disagrees with `plan`.

- **Research browser:** facts with their sources, filterable by the scenes that use them.

**Design rules**

- The dashboard is a pure client of the service API, which wraps the files and the CLI; it never holds state of its own.

- Served through Caddy and reached only through Tailscale; no port open to the internet.

- Push notifications through the platform Web Push system when a checkpoint is reached or a run fails.

- Model monitoring stays in colibri's own dashboard; bookforge links to it rather than rebuilding it.

## Workbench: tuning bookforge

The workbench is a second dashboard mode for tuning the tool itself: story structure, rules, prompts, and how you work with the AI. Like the dashboard, it only edits files, all versioned in Git, so every tuning change is reversible and testable against the benchmarks.

**Story arc view**

- **Tension curve:** planned intensity per chapter (a 1–10 field in `chapters.yaml`), drawn over the arc shape chosen in the book north star. Flat stretches and missing climaxes are visible at a glance.

- **Character arc lanes:** each character's inner state (trust, fear, resolve) as a line across chapters, beside the state-track bars.

- **Thread map:** each setup linked to its payoff; foreshadowing without a payoff is marked red.

- **Edit by dragging:** moving a point previews the consequence ("affects 7 scenes") before it creates a change request.

**Rules panel (do's and don'ts)**

Rules are structured records in `workbench/rules.yaml`; a rule's type decides which checker enforces it.

| Field | Values | Effect |
|---|---|---|
| Scope | Series, book, character, scene | Which briefings and checks include it |
| Type | Banned phrase · style rule · hard constraint · character voice | Mechanical checker · critic rubric · System One · critic, per character |
| Severity | Block, warn, note | Fails review · morning report · logged only |
| Text | The rule in plain words, plus an example | Goes into briefings and checker prompts |

Each rule shows how often it fired and recent hits. A **test button** runs a new rule against chapter 1 before saving, so you see what it would catch.

**Prompt studio**

- Prompts are templates with named slots (`{north_star}`, `{track_states}`, `{beats}`); series-specific overrides live in `workbench/prompts/`.

- **Briefing preview:** the exact assembled prompt for any item, with a bar showing how the token budget splits across slots.

- **A/B tests:** run two prompt versions on the benchmark scenes; results show the judge's verdict, your own blind vote, and the diff between versions.

**Aids for working with the AI**

- **Briefing X-ray:** for any scene, what the model was given, with gaps highlighted ("beat 3 never happened"). It separates the three causes of a bad result: missing input, weak prompt, or model limits.

- **Feedback to rule:** annotate a passage ("too purple"), and the UI proposes a rule with a suggested type and scope. Your comments become lasting rules instead of one-off fixes.

- **Calibration chart:** your scores against the critic's, per criterion, showing where you disagree.

- **Rule health:** rules that never fire, fire constantly, or contradict each other.

**Files**

```
/opt/platform/data/bookforge/my-series/workbench/
├── rules.yaml          do's and don'ts, structured
├── prompts/            overrides of the tool's default templates
├── benchmarks/         series-specific test scenes
└── experiments/        A/B results, one folder per test
```

## Output and export

The manuscript stays clean Markdown as the single source; `export` turns it into every other format with Pandoc, as a separate step after assembly.

| Format | For | Tool |
|---|---|---|
| DOCX, standard manuscript format | Editors, agents, beta readers | Pandoc with a reference .docx |
| EPUB | E-readers and ebook stores | Pandoc, plus cover image and metadata |
| PDF, print interior (e.g. 6 × 9 in) | Print-on-demand | Pandoc with Typst or LaTeX template |
| Companion PDF | Character sheets, timeline, series ledger | Generated from the bible files |

**Rules**

- Format never leaks into the pipeline: no page breaks, styling or front matter in scene files.

- Front and back matter (title page, dedication, acknowledgments) live in `books/b1/matter/` and are added at export.

- Every export is tagged in Git (`b1-export-<date>`), so any shipped file can be traced to its exact text.

- Before self-publishing, check the store's rules on AI-generated content; Amazon KDP, for example, asks for disclosure.

## Operations and troubleshooting

The first run on real models has its own step-by-step plan, with go / no-go points: `docs/BOOKFORGE_FIRST_RUN.md`.

A typical run: start it in the evening with `python -m bookforge run /opt/platform/data/bookforge/my-series` (or start the run from the dashboard), read the morning report, act on "needs you", run again.

| Symptom | Likely cause | Fix |
|---|---|---|
| Out of memory with both servers up | Big model's expert cache plus writer exceed 128 GB | Set `manage_service` so the critic runs only during its stages |
| Big model extremely slow | Experts streaming from disk, cold cache | Run `coli tune`; speed improves as colibri learns which experts you use |
| Very long wait before first token | Long prompt on the big model | Keep critic briefings short; send the scene plus the rubric, not the bible |
| Same phrases everywhere | Model tics | Grow `banned.txt` from the report's suggestions |
| Critic scores everything 4 | Vague rubric | Recalibrate at checkpoint 2 with your own scores |
| A server stops answering | Crash or update | `c/coli logs -n 50`, then `sudo systemctl restart platform-colibri-writer` |
| After `git pull` in colibri | Engine needs rebuilding | Rerun `./start-here.sh` |

**Open questions**

- Real tok/s for both models on the 8060S, CPU vs Vulkan

- Whether both servers fit in RAM together, or the critic must start and stop

- Whether Qwen3.6 prose is good enough, or drafting needs Qwen3.8-Flash-Next

- Rubric criteria and banned phrases for your genre

- Language of the books (affects model choice and the banned-phrase list)

- Search: on the mini PC (2026-11-05) the web tool's DuckDuckGo, Bing and Brave pages all loaded but returned a block page or an empty page, so `research.source` defaults to Wikipedia, whose API answered. `doctor` now runs a real search (`web_search`) so this shows up at once. Wikipedia-only research is a real limit; a general-web source was needed. Decided 2026-11-05: a self-hosted SearXNG in Docker (an infrastructure service, like Open WebUI), reached through the web tool with one narrow local exception (see `research.source`).

- Whether colibri answers long requests without streaming. The client waits for the whole reply (`timeout_seconds`); if colibri supports streaming, switching to it would keep slow replies from hitting the timeout.

- Whether colibri's `/v1/systemone` exists and what its request shape is. `doctor` only checks that the URL answers; the continuity layer does not use it (the planner model answers the questions instead).


**A layer flagged with "the reply is not valid YAML".** The acts, cast, chapters and scenes layers ask the model for YAML, and a model often leaves a colon unquoted inside a sentence (`summary: Anna finds it: the ledger`), which YAML cannot read. Found on the first end-to-end run (acts flagged after two correction rounds). `bible/validate.py` `load_reply_yaml` now repairs such replies itself (it puts double quotes around plain single-line values that contain `: `, ` #` or end in a colon, and leaves quoted values, flow values and `|` / `>` blocks alone), and when a reply still cannot be read the message to the model names the line. A flagged layer is run again by the next `run`; nothing needs to be deleted.

**A chapters or scenes layer flagged with "'the-kestrel' is a object, expected a place".** Found on the first end-to-end run: the cast listed a ship as an object and a chapter used it as its setting. A setting may now be a **place or an object** (a thing people are inside: a ship, a carriage); characters, groups and concepts are still refused. The cast prompt says a ship, train, carriage, house or room that people are inside is a place, and a refused setting now lists the ids that would do (`use one of: harbor, the-kestrel`), so a correction round can choose one. A flagged layer is run again by the next `run`; an already written cast is kept.

**State tracks that do not show up.** Found on the first end-to-end run. (1) The chapters layer saves `bible/tracks.yaml` (and the cast) only when it has planned **every act**, so while the layer is flagged part-way there is nothing to show; the pieces are kept in `books/<id>/work/chapters/` and a rerun continues from them. (2) The Tracks tab used to draw only once scenes existed, but tracks are created with the chapters; it now shows them **by chapter** until the scenes are planned (and says so), and when chapters exist but there are no tracks it says that the model defined none. (3) A model could return no tracks without anyone noticing; an act's reply must now create or extend at least one state track (`<act> defines no state tracks: ...` goes back to the model as a correction, and a saved piece without tracks is asked for again on the next run).

**A scenes layer flagged with "tracks[3].entity: Field required".** Found on the first end-to-end run. The scenes layer may add new state tracks, and a new track needs an `entity` (a cast id); the model left it out, and the message did not say what to do. `_parse_tracks` now fills in the owner of a new track from its id when the id starts with exactly one cast id (`jonas-trust-in-anna` belongs to `jonas`; the longest match wins when cast ids overlap, like `anna` and `anna-voss`), and otherwise says which track is meant, that its id is not an existing track, which ids exist and which cast ids can own a new one. Extending an existing track without repeating its owner still works as before.

**A layer flagged with "beats.3: Input should be a valid string" (or any text field).** Found on the first end-to-end run (scenes of chapter 11). A beat such as `- Jonas confronts her: she lies` is **valid** YAML, so the colon repair does not fire, but YAML reads it as the one-entry mapping `{"Jonas confronts her": "she lies"}`, not as a sentence; a title like `1883` is read as a number and `date: 1883-04-12` as a date. `bible/models.py` `as_text` now turns these back into the text the model wrote (a one-entry mapping becomes `key: value`, a number or date becomes its text) for every text field, so the correction rounds are not spent on them. Anything that is still the wrong shape (several keys, a nested list) is reported as `beats.1: must be one piece of text but is a mapping (key: value); write it as a single sentence inside double quotes`.

**A scene that is flagged ("the scene contradicts a fixed fact: ...").** The continuity check asks up to 40 yes/no questions per scene (each tracked state, each fixed fact of the people and places, every world rule, the research facts it cites, your hard rules, your approved decisions) and the critic-role model answers. A scene is flagged when an answer is **yes**, the quoted words **really are in the scene** and the confidence is **above `qc.continuity_flag_threshold` (0.3)**; a yes without a real quote, or a hesitant no, is only recorded as unsure. Flagged findings are revised paragraph by paragraph, at most `qc.max_revision_rounds` (2) rounds, re-checked each time; what is still wrong then leaves the scene **flagged**: no `final.md` and no summary, the drafts, `revised.md` and `review.json` kept, the run goes on to the next scenes (they see the flagged scene's best draft as "the end of the previous scene"), and the layer ends "N need you".

*What happens to a flagged scene next (added after the first prose run, where every scene was flagged).* The next `run` first **revises its saved text with the findings** (`qc.revise_flagged`, default on): the same check and the specific revision prompts as above, for another round or two. Only if that does not get it accepted is the scene **written again from scratch**, and then the writer is told, in a section "Problems found in the previous attempt at this scene", what the check found (the fact, the words, your instructions). In the scene's **Review** tab each finding has two controls: **"What should the writer do about it?"** (an instruction, added to that finding's problem in the revision and in the next draft) and **"False alarm"** (the finding is not asked about again for this scene). Both are kept in `findings.json` next to the scene, are applied the next time the scene runs, and can be undone; the CLI equivalent is `python -m bookforge finding <series> <scene> --question "<the fact>" --dismiss | --instruct "..." | --clear`. Text you put in `final.md` yourself is adopted with only the mechanical checks, as before. Two causes of false flags found on the first run are removed: a state that begins in the scene is no longer asked about as a fixed fact for the whole scene, and your approved decisions only warn.

**"writer model reply was cut off (finish_reason=length)".** Found on the first prose run. Every call tells the model how many tokens it may write (for a scene draft: the longest scene in `layers.prose.words` x 1.6 + 300, or `layers.prose.max_tokens` if you set it), and a reply that reaches it is stopped mid-sentence. Two things were learned from the call log (about 53 tokens/s on the MS-S1 with qwen3.5:35b): scenes can run far over their maximum (one draft passed 10,200 tokens, over 7,000 words, in 192 s), and asking again with more tokens only costs minutes. So: **a scene draft is never asked again with a larger limit**; a draft that hits it is a failed draft (not saved) and the other draft carries the scene; if every draft is cut off, the scene is flagged with "every draft was cut off at N tokens, more than the W words a scene may have" and the run goes on with the next scene. The **small calls** (revising a paragraph, the summary, an inserted passage, the checks) are asked again with a larger limit (doubled, at least +1000, twice, never above 16000 tokens, no waiting). A reply that is mostly **repeated text** (at least 40% of its 8-word runs occur more than once) is not given more tokens in any call, and the message says "the model is repeating itself". `books/<id>/logs/calls.jsonl` records every attempt with its error; a cut-off one also has `response_chars`, `response_tail` (the last 300 characters) and `repeated_share`, so a repeating model can be told from a merely long reply:

```
jq -r 'select(.response_tail) | "\(.repeated_share) \(.response_chars) chars: \(.response_tail[-120:])"' books/*/logs/calls.jsonl
```

If scenes keep coming back too long, lower `layers.prose.words` (the model aims at the middle of the range) and, so that the cut-off point does not move down with it, set `layers.prose.max_tokens` explicitly (for example 5100). Check the scene's beats too: ten beats make a long scene.

**Checking in on a run that seems to make no progress.** While a job runs, the Overview's job card shows what it is doing now (`bookforge/activity.py`, in memory, returned with the job in the status poll every few seconds): the layer, the scene and the step ("writing drafts", "comparing the drafts", "checking continuity", "the critic is reading it", "revising (round 2)", "summarising", "recording what the scene shows"), the number of model calls and scenes finished this run, and either "Waiting for the model for N s: '<what the call is>'" or "Last model call finished N s ago". The times count from the server's clock (`server_time` in the status), not the phone's. A single scene is many calls and takes roughly 6 to 10 minutes on qwen3.5:35b (two drafts of 70 to 90 s each, then the checks), so a quiet quarter of an hour can be normal; one call waiting more than 3 minutes is shown with a note. Stop (above the panel) ends the job before its next model call. From the shell, all read-only: `journalctl -u platform-bookforge -f` (the service's log), `tail -qn 3 /opt/platform/data/bookforge/*/books/*/logs/calls.jsonl | jq -r '"\(.ts) \(.role) \(.duration_seconds)s ok=\(.ok)"'` (a call is logged when it finishes; compare with `date -u`), `for d in /opt/platform/data/bookforge/*/; do git -C "$d" log --format='%ar  %s' -n 5; done` (each finished scene is a commit), and `ollama ps` if the backend is Ollama. The activity is not kept when the service restarts, and a CLI run (`python -m bookforge run`) has no panel (its log is on the terminal).

**Writing the prose again (the "Write again…" button).** The prose layer has no Redo (that is for the planning layers); written scenes are reset with `rewrite`, now also in the dashboard: on the **prose** row of the Overview's Layers card, **Write again…** opens a panel with a scope menu (all scenes of the book, or one chapter), a **preview** of what would be reset ("8 scene(s) will be reset (6 accepted, 2 flagged); 1 scene with text you wrote yourself is kept"), and two options: *Also discard text I wrote myself* (otherwise a scene whose `final.md` you wrote is kept) and, when chapter 1 is included, *Ask me to approve the voice again* (the voice checkpoint goes back to pending, so the next Run writes chapter 1 only and waits for you; without it the voice stays approved and the next Run writes everything). It resets the scenes to pending and removes their drafts, text, summary, review, extraction and dependencies; what the scenes had added to the state tracks is removed; the plan, the research, your decisions and your notes on findings are untouched; everything finished stays in the Git history. Not while a job runs (Stop it first). From the shell: `python -m bookforge rewrite <series> all [--force] [--reset-voice]` (or chapter and scene ids), and `GET .../rewrite-plan?targets=all` / `POST .../rewrite {targets, force, reset_voice}` in the API; `all` (or the book id) means every scene.

**Scenes flagged although they agree with the facts ("the scene contradicts a fixed fact: Eli Vance: born on a Dominion transport vessel").** Found on the first prose run: the flags' quotes *confirmed* the fact (the fact "abandoned mining tunnels on Erebus-7", the quote "abandoned mining tunnels on Erebus-7"), always at confidence 1.0. The continuity questions were bare facts tagged `[contradiction]` with a yes/no answer, and the model answered "yes" meaning "the scene shows this" and quoted the supporting words; the pipeline only checks that the quote exists in the scene, so each one flagged it. Now every question gets a **relation**, not yes/no: for a fact `contradicts` (the scene states or clearly implies the opposite, with the conflicting words quoted), `agrees` (consistent with it, or confirming it; words that repeat the fact are `agrees`, never `contradicts`) or `silent` (does not touch it, the usual answer); for a change that must be shown, `shown` or `not_shown`. Only `contradicts` (with a real quote, above `qc.continuity_flag_threshold`) flags a scene and only `not_shown` triggers the inserted passage. The prompt also says that traits, manner and voice are tendencies one line does not contradict. An answer with any other relation is sent back for correction, and `review.json` keeps the relation of every unsure answer. Scenes already flagged are re-checked on the next Run (from their saved text, `qc.revise_flagged`), so most pass without being rewritten.

## Operations note: Ollama request isolation

**Reasoning models (found on the first real run, 2026-11-05).** `qwen3.5:35b` on Ollama's OpenAI-compatible endpoint spends the token budget on hidden thinking by default: a 900-token request came back with an empty `content`, 3,638 characters of `reasoning` and `finish_reason=length`. Sending `reasoning_effort: none` fixes it (a 372-word scene in 8 s at about 56 tokens/s). Set it per model with `models.<role>.extra_body` (any extra request fields; the keys bookforge sets itself are refused), for example `extra_body: {reasoning_effort: none}`. A reply that is only thinking now fails with a message that says so and names this setting, instead of "empty reply".

Symptom seen on the first real run: a layer's reply was about the wrong task (for example JSON about another topic instead of a Markdown document). Cause: Ollama carried leftover state from the previous request when both requests began with the same words (the shared system prompt). Fix: `HttpLLMClient` puts a unique first line (`Request <random>.`) at the start of the system message of every call. It is on by default; switch off per endpoint with `isolate_requests: false` (for example for colibri, where the prefix cache is wanted). Cost: long prompts are processed in full on every call. The call log keeps the original messages without the added line.
