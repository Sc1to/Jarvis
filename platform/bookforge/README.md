# bookforge

Automated book-writing pipeline (Phase 14). Separate from the writer app: shares no database, files or settings with `platform/writer`.

- Spec: `docs/BOOKFORGE.md`. Build plan: `docs/BUILD_SEQUENCE.md`, Phase 14.
- Status: milestones 14.0 (service shell), 14.1 (CLI skeleton) and 14.2 (model client, web wrapper, doctor checks) done. No layer handlers exist yet, so `run` does nothing useful until 14.3.
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

Config: built-in defaults, then `config.yaml` here (copy `config.example.yaml`; gitignored) or the file named by `BOOKFORGE_CONFIG`, then `<series>/config.yaml`.

Every model and web call is appended to `<series>/books/<book>/logs/calls.jsonl` (full prompts and replies; not tracked by Git).

Research web access goes only through `platform/tools/web_tool.py` (Playwright); it needs `playwright install chromium` on the host.

Tests: `pytest tests` from this directory with the venv active.
