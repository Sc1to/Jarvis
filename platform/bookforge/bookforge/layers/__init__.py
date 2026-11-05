"""Layer handlers, one per pipeline layer.

Layers 1-3 (direction) are implemented in `direction.py`, layers 4-6 (structure) in
`structure.py`, and the prose (layer 7) in `prose.py`. `run` stops at the first layer without a handler.
"""

from .direction import book_north_star, series_north_star, synopsis
from .runner import Handler
from .prose import prose
from .structure import acts, chapters, scenes

HANDLERS: dict[str, Handler] = {
    "series_north_star": series_north_star,
    "book_north_star": book_north_star,
    "synopsis": synopsis,
    "acts": acts,
    "chapters": chapters,
    "scenes": scenes,
    "prose": prose,
}
