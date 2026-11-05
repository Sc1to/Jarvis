"""Fixed vocabulary of the pipeline. See docs/BOOKFORGE.md (Pipeline, Human checkpoints)."""

# The seven layers, in the order they run.
LAYER_ORDER = (
    "series_north_star",
    "book_north_star",
    "synopsis",
    "acts",
    "chapters",
    "scenes",
    "prose",
)

# The four human checkpoints. direction and structure are attached to layers in
# config; voice (after chapter 1 prose) and final (after assembly) are reached
# explicitly by later milestones.
CHECKPOINTS = ("direction", "structure", "voice", "final")

# Item status values (docs/BOOKFORGE.md, Key records: state.json).
STATUSES = ("pending", "drafted", "checked", "accepted", "stale", "flagged")

CHECKPOINT_STATUSES = ("pending", "waiting", "approved")

STATE_SCHEMA_VERSION = 1
