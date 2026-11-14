"""How long a scene should be: set by the author, or worked out from the scene's own beats.

A scene with one beat is short, a scene with six beats is long: the length follows from the material instead of from a fixed
target. `layers.prose.words` (and `book.target_words`) remain optional overrides; the planned total of a book is reported from
these ranges, it is not aimed at.
"""

WORDS_PER_BEAT = (250, 450)  # low and high words a beat tends to need
SCENE_FLOOR, SCENE_CEILING = 500, 3500


def scene_word_range(project, scene) -> tuple[int, int]:
    """The (min, max) words asked of a scene: the author's `layers.prose.words` if set, else from the number of beats."""
    forced = project.config.layers["prose"].words
    if forced:
        return tuple(forced)
    n = max(1, len(scene.beats)) if scene is not None and getattr(scene, "beats", None) else 0
    if not n:
        return (1500, 3000)
    lo = min(max(SCENE_FLOOR, n * WORDS_PER_BEAT[0]), SCENE_CEILING - 600)
    hi = min(max(lo + 400, n * WORDS_PER_BEAT[1]), SCENE_CEILING)
    return (lo, hi)


def planned_words(project, scenes) -> tuple[int, int]:
    """The total the plan comes to: the sum of every scene's range."""
    ranges = [scene_word_range(project, s) for s in scenes]
    return sum(r[0] for r in ranges), sum(r[1] for r in ranges)
