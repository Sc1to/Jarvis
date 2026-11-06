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

# Files you review at each checkpoint ({book} is the book id; * matches any name). `run` lists the ones that exist.
CHECKPOINT_REVIEW_FILES = {
    "direction": ("north-star.md", "books/{book}/north-star.md", "books/{book}/synopsis.md",
                  "research/needs.md", "books/{book}/research/needs.md"),
    "voice": ("books/{book}/scenes/ch01/s*/final.md", "style/guide.md", "style/banned.txt"),
    "structure": ("books/{book}/acts.yaml", "books/{book}/chapters.yaml", "books/{book}/scenes.yaml",
                  "bible/constants.yaml", "bible/tracks.yaml", "bible/timeline.yaml", "books/{book}/research/needs.md"),
}


REDO_NOTE = "redo"  # the note on a layer the author asked to have written again: it must not be skipped as already there
