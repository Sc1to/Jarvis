# bookforge

Automated book-writing pipeline (Phase 14). Separate from the writer app: shares no database, files or settings with `platform/writer`.

- Spec: `docs/BOOKFORGE.md`. Build plan: `docs/BUILD_SEQUENCE.md`, Phase 14.
- Status: milestones 14.0–14.7 done: service shell, CLI skeleton, model client and doctor, layers 1–3 (north stars and synopsis) up to the direction checkpoint, the research step, layers 4–6 (acts, chapters, scenes) with the story bible up to the structure checkpoint, and the prose layer (drafts, mechanical checks, summaries) with the voice checkpoint after chapter 1. Each scene goes through quality control, cheapest layer first: mechanical checks, the pairwise judge, continuity questions, the rubric critic, and passage-level revision (at most 2 rounds). What is left is flagged for you; each model-based layer can be switched off under `qc:` to make a run cheaper. The prompts have not been run against a real model yet.
- Port 8100; systemd unit `platform-bookforge`; route `/bookforge` (API under `/bookforge/api`).
- Data: `$BOOKFORGE_DATA_DIR` (default `/opt/platform/data/bookforge`), one Git repo per series.

Run locally:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8100
```

Command line (from this directory, venv active):

```bash
python -m bookforge new /opt/platform/data/bookforge/my-series --premise premise.md
python -m bookforge status  <series> [--book b1] [--json]
python -m bookforge run     <series> [--book b1] [--until synopsis]
python -m bookforge approve <series> direction
python -m bookforge state-at <series> b1.ch04.s3 [-e anna]   # what the bible says is true at that point
python -m bookforge briefing <series> b1.ch04.s3 [--full]    # what the model is given for a scene, and how big each part is
python -m bookforge check <series> b1.ch04.s3 [--file x.md]  # mechanical checks on a scene's text
python -m bookforge review <series> b1.ch04.s3                # how the scene went through quality control
python -m bookforge stale  <series> [--fix] [--accept b1.ch04.s3]   # what is out of date and why; --fix re-checks, patches or redrafts
python -m bookforge changes <series> [--approve cr-0001 | --reject cr-0001]   # the prose says something the plan does not
python -m bookforge doctor  [<series>] [--offline]   # --offline skips the endpoint checks and the web fetch
```

Exit codes: 0 ok (including stopping at a checkpoint), 1 error, failed layer, or a finished layer with scenes that need you, 2 `run` stopped because a layer has no implementation yet.

Prompts are in `bookforge/prompts/*.md`; copy one into `<series>/workbench/prompts/` to override it for a series. To write a layer's output yourself, create the file before `run`; it is checked and kept instead of regenerated.

Config: built-in defaults, then `config.yaml` here (copy `config.example.yaml`; gitignored) or the file named by `BOOKFORGE_CONFIG`, then `<series>/config.yaml`.

Every model and web call is appended to `<series>/books/<book>/logs/calls.jsonl` (full prompts and replies; not tracked by Git).

Research notes are written to `research/` (series) and `books/<book>/research/`: `sources.jsonl` (facts with a quote from their source page), `questions.jsonl` and one readable file per layer. Turn research off with `research.enabled: false`.

Research looks things up on Wikipedia by default (`research.source: wikipedia`, `wikipedia_language: en`): search-engine pages are blocked to headless browsers, and `doctor` tells you whether search works from your network.

Research web access goes only through `platform/tools/web_tool.py` (Playwright); it needs `playwright install chromium` on the host.

Tests: `pytest tests` from this directory with the venv active.
