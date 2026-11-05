# bookforge

Automated book-writing pipeline (Phase 14). Separate from the writer app: shares no database, files or settings with `platform/writer`.

- Spec: `docs/BOOKFORGE.md`. Build plan: `docs/BUILD_SEQUENCE.md`, Phase 14.
- Status: milestone 14.0, service shell only (health and error envelope). The pipeline starts at 14.1.
- Port 8100; systemd unit `platform-bookforge`; route `/bookforge` (API under `/bookforge/api`).
- Data: `$BOOKFORGE_DATA_DIR` (default `/opt/platform/data/bookforge`), one Git repo per series.

Run locally:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8100
```

Tests: `pytest tests` from this directory with the venv active.
