# bookforge

Automated book-writing pipeline (Phase 14). Separate from the writer app: shares no database, files or settings with `platform/writer`.

- Spec: `docs/BOOKFORGE.md`. Build plan: `docs/BUILD_SEQUENCE.md`, Phase 14.
- Status: milestones 14.0–14.4 done: service shell, CLI skeleton, model client and doctor, layers 1–3 (north stars and synopsis) up to the direction checkpoint, and the research step. Layers 4–7 have no handlers yet, so `run` stops there (exit code 2). The prompts have not been run against a real model yet.
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
python -m bookforge doctor  [<series>] [--offline]   # --offline skips the endpoint checks and the web fetch
```

Exit codes: 0 ok (including stopping at a checkpoint), 1 error or failed layer, 2 `run` stopped because a layer has no implementation yet.

Prompts are in `bookforge/prompts/*.md`; copy one into `<series>/workbench/prompts/` to override it for a series. To write a layer's output yourself, create the file before `run`; it is checked and kept instead of regenerated.

Config: built-in defaults, then `config.yaml` here (copy `config.example.yaml`; gitignored) or the file named by `BOOKFORGE_CONFIG`, then `<series>/config.yaml`.

Every model and web call is appended to `<series>/books/<book>/logs/calls.jsonl` (full prompts and replies; not tracked by Git).

Research notes are written to `research/` (series) and `books/<book>/research/`: `sources.jsonl` (facts with a quote from their source page), `questions.jsonl` and one readable file per layer. Turn research off with `research.enabled: false`.

Research web access goes only through `platform/tools/web_tool.py` (Playwright); it needs `playwright install chromium` on the host.

Tests: `pytest tests` from this directory with the venv active.
