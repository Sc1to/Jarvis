"""Valid model replies for layers 4-6 of a small test book: 2 acts, 4 chapters, 2 scenes per chapter."""

import copy

import yaml

from bookforge.layers.runner import StepContext  # noqa: F401  (re-exported for convenience)

SMALL_CONFIG = """\
layers:
  acts: {count: [2, 2]}
  chapters: {count: [4, 4]}
  scenes: {per_chapter: [2, 3]}
research:
  scene_questions: 0
qc:
  review_structure: false
"""


def dump(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def acts(counts=(2, 2)):
    return {"acts": [
        {"id": f"b1.act{i}", "title": f"Act {i}", "summary": f"What happens in act {i}.", "purpose": "Its job.",
         "turning_point": f"The turn of act {i}.", "chapter_count": n}
        for i, n in enumerate(counts, 1)]}


def cast():
    return {"entities": [
        {"id": "anna", "kind": "character", "name": "Anna Voss", "facts": ["grey eyes", "left-handed"]},
        {"id": "jonas", "kind": "character", "name": "Jonas Reil", "facts": ["tall"]},
        {"id": "harbor", "kind": "place", "name": "The harbor town", "facts": ["always foggy"]},
        {"id": "vestry", "kind": "place", "name": "The vestry", "facts": ["cold stone room"]},
        {"id": "ledger", "kind": "object", "name": "The ledger", "facts": ["bound in black cloth"]},
    ], "rules": [{"id": "ledger-cost", "text": "each name crossed out costs a year of memory"}]}


def chapter(n, pov="anna", setting="harbor", tension=3):
    return {"id": f"b1.ch{n:02d}", "title": f"Chapter {n}", "purpose": f"Purpose {n}", "summary": f"Events of chapter {n}.",
            "pov": pov, "setting": setting, "tension": tension}


def chapters_act1():
    return {"chapters": [chapter(1), chapter(2)], "tracks": [
        {"id": "anna-wound", "entity": "anna", "kind": "physical",
         "plan": [{"from": "b1.ch02", "value": "deep cut, left shoulder; bleeding", "must_show": True}]},
        {"id": "jonas-knows", "entity": "jonas", "kind": "knowledge",
         "plan": [{"from": "b1.ch01", "value": "knows nothing about the ledger"}]},
    ]}


def chapters_act2():
    return {"chapters": [chapter(3, setting="vestry"), chapter(4)], "tracks": [
        {"id": "anna-wound", "plan": [{"from": "b1.ch04", "value": "healed; scar remains", "must_show": True}]},  # extends: no entity given
        {"id": "jonas-knows", "plan": [{"from": "b1.ch03", "value": "knows about the ledger"}]},
    ]}


def scene(ch, n, day, setting="harbor", **extra):
    return {"id": f"b1.ch{ch:02d}.s{n}", "purpose": f"Scene {ch}.{n} changes things.", "pov": "anna", "setting": setting,
            "characters": ["anna", "jonas"], "beats": ["Something happens.", "Anna decides."], "day": day, "time": "dusk", **extra}


SCENES = {
    1: ([1, 1], [{"id": "jonas-knows", "plan": [{"from": "b1.ch01.s1", "value": "knows nothing about the ledger"}]}]),
    2: ([2, 3], [{"id": "anna-wound", "plan": [{"from": "b1.ch02.s2", "value": "deep cut, left shoulder; bleeding", "must_show": True}]}]),
    3: ([10, 10], [{"id": "jonas-knows", "plan": [{"from": "b1.ch03.s1", "value": "knows about the ledger"}]}]),
    4: ([40, 41], [{"id": "anna-wound", "plan": [{"from": "b1.ch04.s1", "value": "healed; scar remains", "must_show": True}]}]),
}


def scenes_reply(ch, drop_tracks=False):
    days, tracks = SCENES[ch]
    setting = "vestry" if ch == 3 else "harbor"
    out = {"scenes": [scene(ch, i + 1, d, setting) for i, d in enumerate(days)]}
    if not drop_tracks:
        out["tracks"] = copy.deepcopy(tracks)  # callers mutate the reply; never share the module-level data
    return out


def rules():
    """RuleLLM rules answering every layer 4-6 call with a valid reply."""
    r = [
        ("Divide the book into ACTS", dump(acts())),
        ("List the CAST AND WORLD", dump(cast())),
        ("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(chapters_act1())),
        ("Plan exactly 2 chapters, b1.ch03 to b1.ch04", dump(chapters_act2())),
    ]
    for ch in range(1, 5):
        r.append((f"Scene ids are consecutive: b1.ch{ch:02d}.s1", dump(scenes_reply(ch))))
    return r


def small(project):
    """Reopen the project with the small-book config (2 acts, 4 chapters, 2-3 scenes per chapter)."""
    from bookforge.project import Project
    (project.root / "config.yaml").write_text(SMALL_CONFIG, encoding="utf-8")
    return Project.open(project.root)


def ready(project):
    """A small project with layers 1-3 accepted and the direction checkpoint approved, as if they had run."""
    from conftest import file_handler  # noqa: F401
    p = small(project)
    ns = "# T\n\n" + "\n\n".join(f"## {s}\nSome words about the {s.lower()} of the story and more words." for s in
                                  ("Premise", "Themes", "Emotional promise", "Tone", "Ending direction", "What it is not"))
    (p.root / "north-star.md").write_text(ns)
    (p.root / "books/b1/north-star.md").write_text(ns)
    (p.root / "books/b1/synopsis.md").write_text("A long synopsis. " * 40)
    for layer in ("series_north_star", "book_north_star", "synopsis"):
        p.state.set_layer_status(layer, "accepted")
    p.state.reach_checkpoint("direction")
    p.state.approve_checkpoint("direction")
    p.save_state()
    from bookforge import vcs
    vcs.commit(p.root, "test setup: layers 1-3 done")
    return p


def north_star_text(marker=""):
    return "# T\n\n" + "\n\n".join(f"## {s}\n" + " ".join([f"{s.split()[0].lower()}{marker}"] * 30) for s in
                                  ("Premise", "Themes", "Emotional promise", "Tone", "Ending direction", "What it is not"))


def direction_rules():
    """Valid replies for layers 1-3."""
    return [
        ("Write the SERIES NORTH STAR", north_star_text("aaa")),
        ("Write the NORTH STAR FOR BOOK", north_star_text("bbb")),
        ("Write the SYNOPSIS", "# Synopsis\n\n" + " ".join(["story"] * 500)),
    ]
