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


# ── the book's length: told to the planner, checked against the plan ─────────

SCENE_TARGET_WORDS = 1800  # about what one scene is meant to come to when a target is set
WORDS_PER_BEAT_MID = 350


def chapter_budget(project, chapters, events: list) -> dict[str, int]:
    """Words each chapter should come to: `book.target_words` split over the chapters in proportion to the weight of the events each tells.
    Empty when there is no target, or when the author fixed the scene length (`layers.prose.words` wins, as it always did)."""
    target = project.config.book.target_words
    if target <= 0 or project.config.layers["prose"].words or not chapters:
        return {}
    weight = {e["id"] if isinstance(e, dict) else e.id: int((e.get("weight", 1) if isinstance(e, dict) else e.weight)) for e in events}
    per = {c.id: max(1, sum(weight.get(x, 1) for x in list(c.events_covered) + list(c.events_continued))) for c in chapters}
    total = sum(per.values())
    return {cid: round(target * w / total) for cid, w in per.items()}


def length_guidance(words: int | None) -> str:
    """The sentence the scenes prompt gets about length: the chapter's budget and what it means in scenes and beats, or the old advice with no target."""
    if not words:
        return "A chapter with little to tell gets one or two scenes; never stretch it."
    scenes = min(4, max(1, round(words / SCENE_TARGET_WORDS)))
    beats = min(9, max(3, round(words / scenes / WORDS_PER_BEAT_MID)))
    return (f"This chapter should come to about {words} words when written. That is about {scenes} scene{'s' if scenes != 1 else ''} of about {words // scenes} words, "
           f"each with about {beats} beats. Reach it by showing the chapter's events in more depth (the moments inside them, what each person does and notices, what it costs), "
           "never by inventing events, repeating one, or adding a scene that tells nothing new.")


def plan_vs_target(project, scenes) -> tuple[int, int, int]:
    """(planned low, planned high, target); the target is 0 when the author fixed the scene length or set none."""
    lo, hi = planned_words(project, scenes)
    target = project.config.book.target_words
    return lo, hi, 0 if project.config.layers["prose"].words else max(0, target)
