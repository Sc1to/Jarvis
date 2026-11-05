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

briefing:
  max_tokens: 16000
  previous_scene_words: 1500

qc:
  continuity_flag_threshold: 0.3
  critic_min_score: 3
  max_revision_rounds: 2
  banned_phrases: style/banned.txt
  critic_may_accept: within_chapter  # larger change requests wait for you

git:
  commit_each_step: true
  tag_checkpoints: true
```

Layers tagged with the same `checkpoint` form a group: the pipeline stops once every layer in the group is accepted, and later layers wait until you run `approve`. The checkpoint table says Structure comes "after layers 4–6", so `scenes` carries `structure` too (the original config tagged only acts and chapters). The `voice` and `final` checkpoints are not tied to a layer; they are reached by the prose and assembly steps.

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
- Critic model: `http://127.0.0.1:8041/v1`, System One at `/v1/systemone`
- Web research: platform Playwright web tool

**Milestones**

0. Service shell (done): `platform/bookforge/` with `GET /health`, `{data, status}` envelope, venv, requirements, systemd unit, health test, deploy and Caddy wiring for `/bookforge`. Empty frontend placeholder. **Built 2026-11-05.**

1. Skeleton (done 2026-11-05): CLI (`new`, `run`, `status`, `approve`, `doctor`), config, `state.json`, fake LLM client for tests, Git commits through `vcs.py`. The layer runner is a thin loop with an empty handler registry, so `run` stops at the first layer (exit code 2) until milestone 14.3.

2. `llm.py` and `doctor` (done 2026-11-05): real OpenAI-compatible client for both colibri endpoints (3 attempts with 2 s / 4 s backoff on connection errors, timeouts, 408/429/5xx; a reply cut off by the token limit is an error, never silent text), a web wrapper over the Playwright tool (`bookforge/research/search.py`: http/https only, no private or loopback hosts, query encoding, retries), and a call log at `books/<book>/logs/calls.jsonl` with full prompts and replies (gitignored). `doctor` now checks both endpoints, System One and the web tool, including one real page fetch; `doctor --offline` skips the network checks. The `manage_service` start/stop of the critic is not wired up yet.

3. The layer runner with layers 1–3 (north stars, synopsis) and the direction checkpoint.

4. The research step inside the runner: questions, web-tool search, fetch, notes, `sources.jsonl`.

5. Layers 4–6 and the bible: constants, state tracks, timeline, state-at-a-point lookups.

6. Briefing builder with `deps.yaml`, the prose layer, and the mechanical checker.

7. Continuity (System One), critic, pairwise judge, revision loop, extraction into `observed`.

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

- Whether web search works from the mini PC. The platform web tool's search loads a DuckDuckGo results page; from the dev sandbox it returned a block page ("If this persists, please email us") that the tool still reported as success. Milestone 14.4 must detect empty or blocked results, and may need a different search page.

- Whether colibri answers long requests without streaming. The client waits for the whole reply (`timeout_seconds`); if colibri supports streaming, switching to it would keep slow replies from hitting the timeout.

- Whether colibri's `/v1/systemone` exists and what its request shape is. `doctor` only checks that the URL answers.

