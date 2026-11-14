"""Stage validators: deterministic checks of what each planning stage produced.

Every validator is a plain function over parsed data (dicts or records) that returns a list of `Finding`s. They look for
failure PATTERNS (an event told twice, a state that flips back, a flat stretch, text copied between scenes), never for
particular story content, so they work for any book. See platform/bookforge/CONTRACTS.md.

Severity:
- `hard`: the stage's output is wrong. It is fed back to the model for a correction (at most `qc.max_revision_rounds`);
  if it survives that, the stage stops at its checkpoint and nothing flows downstream until the author resolves it.
- `soft`: worth a look. Recorded and shown, never blocks.
"""

from .findings import HARD, SOFT, Finding, hard, soft, summarize

__all__ = ["HARD", "SOFT", "Finding", "hard", "soft", "summarize"]
