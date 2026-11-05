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
│   ├── cli.py                 new | run | status | approve | stale | report | bench
│   ├── llm.py                 OpenAI-compatible client, retries, logging
│   ├── layers/                runner.py (the shared loop) + one settings file per layer
│   ├── bible/                 tracks.py (state at a point), extract.py (prose → observed)
│   ├── deps.py                dependency graph, staleness, re-check queue
│   ├── vcs.py                 git commits, tags, change-request branches
│   ├── briefing.py            builds the per-call context pack
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
  mesa-vulkan-drivers vulkan-tools jq
vulkaninfo --summary               # should list the Radeon 8060S
```

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

3. The layer runner with layers 1–3 (north stars, synopsis) and the direction checkpoint (done 2026-11-05). Each layer asks the planner model for its document, checks the structure in code (the six north-star sections, one page = at most 600 words; synopsis 300–2500 words), and if the check fails asks for a correction, at most `qc.max_revision_rounds` times; unresolved layers are flagged. Review of these three layers is yours, at the direction checkpoint (as in the layer table); the model critic comes in milestone 14.7 and the research step in 14.4 (marked with a TODO in `layers/document.py`).

   - Prompts live in `bookforge/prompts/*.md` (`system`, `series_north_star`, `book_north_star`, `synopsis`, `correct`). Inputs are named slots like `{premise}`. A series can override any prompt by placing a file of the same name in `<series>/workbench/prompts/`. They are first drafts: expect to edit them after reading the first outputs.
   - Inputs: layer 1 reads `premise.md`; layer 2 reads the premise, the series north star and `ledger.yaml` ("none" for a first book); layer 3 reads both north stars. Outputs: `north-star.md`, `books/<book>/north-star.md`, `books/<book>/synopsis.md`.
   - If an output file already exists, bookforge checks it and adopts it instead of calling the model, so you can write a north star yourself. An existing file that fails the check is never overwritten; fix it or delete it to have it regenerated.
   - `run` stops once all three are accepted and lists the files to review. Edit them freely. `approve direction` commits everything in the series, including your edits, and tags `b1-direction-approved`.

4. The research step inside the runner: questions, web-tool search, fetch, notes, `sources.jsonl` (done 2026-11-05). After a layer's document is written, the step (`bookforge/research/`) works like this:

   - The planner model proposes at most `research.max_questions` factual questions the document depends on, each with a short search query and a `sensitive` flag (history, medicine, real places, real people). Questions already answered, in the series or the book, are skipped; unanswered ones are retried on the next run.
   - Each query goes through the web tool. The result links are read from the tool's `links` metadata (DuckDuckGo's redirect links are unwrapped); a results page with no usable links is reported as blocked or empty. Up to `research.pages_per_question` pages are fetched, never the same page twice.
   - The notes model (`research.notes_model`, default the fast writer) extracts up to 3 facts per page, each with a quote. **A fact is kept only if its quote appears verbatim in the page** (case, spacing and typographic quotes ignored), so the model cannot add facts the page does not contain. Page text is given to the models as data, never as instructions.
   - Files, per scope (`research/` for the series, `books/<book>/research/` for a book): `sources.jsonl` (one fact per line: id, claim, url, title, date fetched, quote, layer, question, sensitive), `questions.jsonl` (every question, answered or not, with the reason), and a readable `<layer>.md`. Fact ids are `s-0001` for the series and `b1-0001` for book b1; scenes will cite them.
   - Stored facts (newest first, within `research.notes_max_chars`) are shown to later layers as reference data in the `{research_notes}` slot.
   - Research is best-effort: a blocked search or unreadable page costs that question, and the layer's note reports it (for example `research: 1/3 questions answered, 2 facts (search … blocked or empty)`). Set `research.required: true` to make a layer fail instead when none of its questions has an answer; the document is kept and the rerun retries the research. `research.enabled: false` turns it off.
   - The shared web tool now returns the page's links in `ToolResult.metadata["links"]`, which is how result links are found. Without it, only the page text was available.

5. Layers 4–6 and the bible: constants, state tracks, timeline, state-at-a-point lookups (done 2026-11-05; formats under *Story bible*). The checks are structural only (ids, counts, references to the cast, track guards, timeline order); the critic's review of these layers was added in 14.7 (see below). Two choices the spec left open: the cast and world are created by the chapters layer, and the scenes layer researches `research.scene_questions` (default 2) questions per chapter before planning its scenes, so scenes can cite fact ids.

6. Briefing builder with `deps.yaml`, the prose layer, and the mechanical checker (done 2026-11-05). The checks described here are the first layer; the judge, continuity, critic, revision loop and extraction were added in 14.7 (see below), so a scene's best draft is accepted if it has no blocking problem left after them, and flagged otherwise.

   - **Briefing** (`bookforge/briefing.py`): the six parts of the briefing pack, within `briefing.max_tokens` (an estimate, about 3.5 characters per token). Over budget, it is cut in a fixed order: older chapter summaries, research notes, the previous scene's tail, sample passages, the style guide. The north stars, beats and story state are never cut; if they alone do not fit, the build fails with the largest parts named. `python -m bookforge briefing <series> b1.ch04.s3 [--full] [--tokens N]` shows the size of each part, or the whole text.
   - **deps.yaml** (per scene, written whenever a scene is drafted) records what the scene was built from as `id@fingerprint`. A fingerprint is the first 8 hex digits of the SHA-256 of the record's content, not a counter, so a hand edit counts as a change (this replaces the `@v3` style above). Tracks are fingerprinted by their state *at that scene*, so editing a later chapter's entry does not mark earlier scenes stale. Keys: `scene`, `parent`, `north_stars`, `style`, `bible`, `research`, `timeline`, `previous`, `summaries`. Staleness handling is milestone 14.8.
   - **Prose layer** (`bookforge/layers/prose.py`), per scene: write `layers.prose.drafts` drafts (the fast model; draft *i* uses the *i*-th temperature), run the mechanical checks on each, keep the one with the lowest score (a blocking problem costs 100, a warning 1; a tie goes to the first draft) as `final.md`, then write a 3-5 sentence `summary.md` with the fast model (if that fails, the plan's purpose stands in; `review.json` records which). Files per scene in `books/<book>/scenes/chNN/sN/`: `draft-N.md`, `final.md`, `summary.md`, `review.json` (chosen draft, all mechanical reports, briefing size), `deps.yaml`. Each scene is committed as `b1.ch05.s2: drafted, checked, accepted` (or `drafted, flagged`).
   - **Voice checkpoint.** Chapter 1 is written first and the run stops (exit code 0) with the files to review. Read it, edit `style/guide.md` and `style/banned.txt`, put sample passages in `style/samples/`, delete a scene's files to have it rewritten, then `approve voice`. Only then is the rest of the book written. `run` while the checkpoint waits does nothing.
   - **Flagged scenes** do not hold up the other scenes. When the book is finished the layer is `flagged` (exit code 1) and lists the scenes that need you; the next `run` rewrites only those. A `final.md` you write yourself is checked and adopted, never overwritten. Drafts left on disk by a stopped run are reused.
   - **Mechanical checks** (`bookforge/qc/mechanical.py`, no model): *blocking*: banned phrases, assistant chatter or formatting (headings, lists, "Scene 3:" labels, code fences), a cut-off ending, a length under half the minimum or over twice the maximum; *warnings*: phrases repeated from earlier scenes or inside the scene, overused words (names excluded), monotone sentence rhythm, over-long sentences, repeated sentence openings, dialogue share outside the range, a scene that opens by repeating the end of the previous one, tense and point-of-view slips and head-hopping. The last three use English-only heuristics and are skipped for other `book.language` values. Every finding carries the character span, for passage-level revision in 14.7. `python -m bookforge check <series> b1.ch01.s1 [--file x.md]` runs them on a scene or a file.
   - **`style/banned.txt`** is created with a starter list of common model clichés (English). It is yours: edit it, and add to it at the voice checkpoint. A line is a phrase (matched ignoring case and line breaks) or `re:` plus a regular expression; `#` starts a comment. The list is also given to the writer model.

7. Continuity (System One), critic, pairwise judge, revision loop, extraction into `observed` (done 2026-11-05). Quality control for a scene now runs cheapest layer first (`bookforge/qc/`):

   1. **Mechanical** on every draft (14.6).
   2. **Judge.** If more than one draft has no blocking problem, the planner model compares them pairwise, A against B and then B against A; if the two runs name different drafts the pair is a tie. With three drafts every pair is judged. Wins decide; ties go to the lower mechanical score, then the lower draft number. A judge that fails falls back to the mechanical score.
   3. **Continuity** on the chosen draft, only if it has no blocking mechanical problem. One yes/no question per relevant fact: every tracked state at the scene, the fixed facts of the people and places in it, the rules of the world, and the research facts it cites; changes marked `must_show` also get a "shown on the page?" question. P(contradiction) is the confidence for a yes and 1 - confidence for a no. A yes whose quoted evidence is really in the scene and whose P is above `qc.continuity_flag_threshold` is a flag; a hesitant answer, or a yes without quotable evidence, is only "unsure" (recorded, never revised). A `must_show` change that is not shown cannot be repaired by rewriting one passage, so that scene is left for you.
   4. **Critic** on the chosen draft, only if the cheaper layers passed. Six criteria scored 1-5 (stakes, voice, show_dont_tell, pacing, dialogue, beats_covered) and the three weakest lines quoted. A quote that is not in the scene is sent back. The rubric is `prompts/critic_rubric.md`; to calibrate the critic against your own reading, copy it to `<series>/workbench/prompts/` and reword it. The critic is given the scene, its beats and the voice (style guide and one sample), never the bible.
   5. **Revision**, at most `qc.max_revision_rounds` rounds. Flags come from blocking mechanical problems (banned phrases, a cut-off ending, chatter, formatting), continuity contradictions, and the critic's weakest lines when a score is under `qc.critic_min_score`. The fast model gets the paragraph around each flag, the problems, and (for the critic) the rubric line; only that paragraph is replaced, and several flags in one paragraph cost one call. Short chatter and formatting lines are deleted instead. A revised paragraph must stay within 0.4x-2.5x of the original length and must not contain a banned phrase. Layers 1-2 then run again; the critic runs again only if its scores were under the minimum.
   6. **What is left** (a blocking problem the revision could not fix, an unmet `must_show`, scores still under the minimum, a scene too short) is written to `review.json` as `blocking`, the scene is flagged, and its latest text is kept as `revised.md` (a flagged scene's drafts are rewritten on the next run).
   7. **Extraction.** After a scene is accepted the fast model reports, for each track with a state at the scene, what the prose shows (`extracted.yaml`, and into the track's `observed`). A verdict needs quotable evidence from the scene. A clear difference from the plan is a *gap*: recorded and counted in the scene's note, but it does not block the scene; a deliberate change of plan becomes a change request in 14.8.

   Layers 4-6 get the critic's **plan review**: each piece (the acts, the chapters of an act, the scenes of a chapter) is reviewed against its parent, both north stars and the state tracks, and problems are sent back for correction like structural ones. Problems still open after the correction rounds never fail the layer: they go to `books/<book>/reports/review-notes.jsonl` and are counted in the layer's note. The state-track check ("System One" for plans) is part of this one critic call.

   **System One.** Its request shape could not be verified, so the continuity questions are answered by the planner model. Its confidence is self-reported, which is less reliable than a probability read from the model, so the 0.3 threshold is applied to it conservatively. If colibri's endpoint turns out to exist, only `qc/decide.py` needs to change. `models.decide.url` is unused and `doctor` only checks that it answers.

   **Cost.** A scene can now take 15-25 model calls (2 drafts, 2 judge, 2-5 continuity batches, the critic, revisions and re-checks, a summary, an extraction), most of them on the slow planner model. Each model-based layer has a switch under `qc:` to make a run cheaper. `python -m bookforge review <series> b1.ch04.s3` shows how a scene went: draft choice, scores, flags, revisions, gaps.

8. Staleness and change requests: dependency graph, re-check / patch / redraft, `stale` command.

9. Morning report, assembly, `bench` command and benchmark scenes.

10. API endpoints on the service for runs, status, checkpoints and approvals (wrapping the same library as the CLI).

11. Dashboard (`frontend/bookforge/`): progress tree, checkpoint inbox, draft compare, track timeline; Web Push notifications.

12. `export`: DOCX, EPUB, print PDF, companion PDF, with Git tags.

13. The workbench, in this order: rules panel, briefing preview and X-ray, prompt A/B tests, feedback to rule, then the arc views.

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

- **Track timeline:** each state track as a bar across chapters (the wound from ch4 to ch10), with marks where `observed` disagrees with `plan`.

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

- Whether web search works from the mini PC. The platform web tool's search loads a DuckDuckGo results page; from the dev sandbox it returned a block page ("If this persists, please email us") that the tool still reported as success. The research step now reports such a page as blocked or empty instead of using it, but it has only been run against scripted search results. That DuckDuckGo result links look like `duckduckgo.com/l/?uddg=<url>` is an assumption from memory; check it on the first real run, and if search stays blocked, a different search page (or SearXNG, as an explicit exception to the Playwright-only rule) is needed.

- Whether colibri answers long requests without streaming. The client waits for the whole reply (`timeout_seconds`); if colibri supports streaming, switching to it would keep slow replies from hitting the timeout.

- Whether colibri's `/v1/systemone` exists and what its request shape is. `doctor` only checks that the URL answers; the continuity layer does not use it (the planner model answers the questions instead).

