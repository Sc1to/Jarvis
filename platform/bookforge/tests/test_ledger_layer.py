"""The story-event ledger layer: extraction, validation retries, thin synopses, author answers, state migration."""

import copy
import json
from pathlib import Path

import yaml
from conftest import skip_ledger  # noqa: F401

from bookforge import ops
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.ledger import answer_question, capacity
from bookforge.layers.runner import run
from bookforge.llm import FakeLLMClient
from bookforge.state import load_state

FIX = Path(__file__).parent / "fixtures" / "known_bad"
SYN = (FIX / "synopsis.md").read_text(encoding="utf-8")
GOOD = yaml.safe_load((FIX / "ledger.yaml").read_text(encoding="utf-8"))


def dump(d):
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True)


def prepared(project):
    """Layers 1-3 accepted, direction approved, the fixture synopsis in place."""
    for layer in ("series_north_star", "book_north_star", "synopsis"):
        project.state.set_layer_status(layer, "accepted")
    project.state.reach_checkpoint("direction")
    project.state.approve_checkpoint("direction")
    project.save_state()
    (project.root / "north-star.md").write_text("# Series\n\nA test.\n")
    (project.book_dir / "north-star.md").write_text("# Book\n\nA test.\n")
    (project.book_dir / "synopsis.md").write_text(SYN)
    return project


def thin_events():
    ev = copy.deepcopy(GOOD["events"])
    return ev


def run_ledger(project, replies):
    llm = FakeLLMClient({"critic": [r if isinstance(r, str) else dump(r) for r in replies]})
    return run(project, llm, HANDLERS, until="ledger"), llm


def test_a_synopsis_with_enough_story_is_accepted_and_waits_at_the_ledger_checkpoint(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4  # the small test synopsis weighs 22 = 11 chapters
    summary, llm = run_ledger(p, [GOOD])
    assert summary.ran == ["ledger"] and summary.stopped == "checkpoint" and "ledger" in summary.detail
    led = store.load_ledger(p)
    assert len(led.events) == 10 and not led.thin and led.capacity["estimated_chapters"] == 11.0
    assert p.state.checkpoints["ledger"].status == "waiting"
    report = json.loads((p.book_dir / "validation" / "ledger.json").read_text())
    assert report["summary"]["hard"] == 0 and report["capacity"]["formula"]


def test_a_failed_check_is_fed_back_and_survivors_stop_the_layer(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    bad = copy.deepcopy(GOOD)
    bad["events"] = [e for e in bad["events"] if not e["ending"]]  # the resolution is missing
    summary, llm = run_ledger(p, [bad, GOOD])
    assert summary.ran == ["ledger"] and len(llm.calls) == 2
    fed_back = llm.calls[1]["messages"][-1]["content"]
    assert "no_resolution" in fed_back or "synopsis_not_covered" in fed_back

    q = prepared(__import__("conftest").Project.create(p.root.parent / "second", "x\n"))
    q.config.ledger.min_chapters = 4
    summary, _ = run_ledger(q, [bad, bad, bad])
    assert summary.stopped == "failed" and q.state.layers["ledger"].status == "flagged"  # never flows downstream
    assert store.load_ledger(q) is None


def test_a_thin_synopsis_asks_questions_and_stops(project_with_ledger):
    p = prepared(project_with_ledger)  # the default minimum is 12 chapters; this synopsis carries 11
    thin_no_questions = copy.deepcopy(GOOD)
    with_q = copy.deepcopy(GOOD)
    with_q["questions"] = [dict(id="q1", question="What stands between Mara and the ferry?", why="the middle of the book is empty",
                                options=["a rival salvager wants the ferry", "the ferry is impounded"])]
    summary, llm = run_ledger(p, [thin_no_questions, with_q])
    assert len(llm.calls) == 2 and "Do not pad" in llm.calls[1]["messages"][-1]["content"]  # padding refused, questions required
    assert summary.stopped == "checkpoint" and p.state.layers["ledger"].status == "drafted"
    led = store.load_ledger(p)
    assert led.thin and led.questions[0].status == "open" and len(led.events) == 10
    assert "estimated_chapters" in led.capacity and led.capacity["minimum_chapters"] == 12
    # still waiting: running again makes no model call
    summary2, llm2 = run_ledger(p, [])
    assert summary2.stopped == "checkpoint" and llm2.calls == []


def test_author_answers_revise_the_ledger_and_rerun_the_validators(project_with_ledger):
    p = prepared(project_with_ledger)
    with_q = copy.deepcopy(GOOD)
    with_q["questions"] = [dict(id="q1", question="What stands between Mara and the ferry?", why="empty middle", options=["a rival salvager"])]
    run_ledger(p, [with_q])
    answer_question(p, "q1", "A rival salvager, Teague, wants the ferry too and sabotages the yard gate.")
    revised = copy.deepcopy(GOOD)
    revised["events"].insert(2, dict(id="e11", text="Rival salvager Teague sabotages the yard gate", once_only=True, after=["e2"], kind="event", weight=3,
                                     pov="", ending=False, pays_off="", source="author", parent="", excerpt=""))
    revised["events"].insert(3, dict(id="e12", text="Mara outwits Teague at the gate", once_only=True, after=["e11"], kind="event", weight=3,
                                     pov="", ending=False, pays_off="", source="author", parent="", excerpt=""))
    summary, llm = run_ledger(p, [revised])
    assert len(llm.calls) == 1 and "Teague" in llm.calls[0]["messages"][-1]["content"]
    led = store.load_ledger(p)
    assert led.revision == 2 and [e.id for e in led.events if e.source == "author"] == ["e11", "e12"]
    assert led.questions[0].applied and led.questions[0].status == "answered"
    assert led.capacity["estimated_chapters"] == 14.0 and not led.thin  # 22 + 6 = 28 weight
    assert summary.ran == ["ledger"]


def test_a_revision_may_not_change_synopsis_events(project_with_ledger):
    p = prepared(project_with_ledger)
    with_q = copy.deepcopy(GOOD)
    with_q["questions"] = [dict(id="q1", question="?", why="thin", options=["x"])]
    run_ledger(p, [with_q])
    answer_question(p, "q1", "Add a rival.")
    tampered = copy.deepcopy(GOOD)
    tampered["events"][0]["text"] = "Mara owes nothing"
    summary, llm = run_ledger(p, [tampered, tampered, tampered])
    assert summary.stopped == "failed" and "must stay exactly as it was" in llm.calls[1]["messages"][-1]["content"]
    assert store.load_ledger(p).revision == 1  # the saved ledger is untouched


def test_approving_the_checkpoint_dismisses_open_questions(project_with_ledger):
    p = prepared(project_with_ledger)
    with_q = copy.deepcopy(GOOD)
    with_q["questions"] = [dict(id="q1", question="?", why="thin", options=["x"])]
    run_ledger(p, [with_q])
    ops.approve_checkpoint(p, "ledger")
    summary, llm = run_ledger(p, [])
    assert summary.ran == ["ledger"] and llm.calls == []
    assert store.load_ledger(p).questions[0].status == "dismissed"


def test_derived_events_and_capacity_numbers():
    ev = [dict(id="e1", weight=3, source="synopsis"), dict(id="e1.1", weight=1, source="derived"), dict(id="e2", weight=1, carried_in=True), dict(id="e3", weight=2, source="author")]
    cap = capacity(ev, 2.0, 12)
    assert cap["total_weight"] == 5 and cap["estimated_chapters"] == 2.5 and cap["thin"] is True


def test_books_planned_before_the_ledger_carry_on(tmp_path):
    from bookforge.project import Project
    p = Project.create(tmp_path / "old", "premise\n")
    raw = json.loads(p.state_path.read_text())
    del raw["layers"]["ledger"], raw["checkpoints"]["ledger"]
    for layer in ("series_north_star", "book_north_star", "synopsis", "acts"):
        raw["layers"][layer]["status"] = "accepted"
    p.state_path.write_text(json.dumps(raw))
    st = load_state(p.state_path)
    assert st.layers["ledger"].status == "accepted" and st.checkpoints["ledger"].status == "approved"
    raw["layers"]["acts"]["status"] = "pending"
    p.state_path.write_text(json.dumps(raw))
    assert load_state(p.state_path).layers["ledger"].status == "pending"  # not yet planned: the ledger will run


def test_a_setup_that_names_the_text_instead_of_the_id_is_repaired_without_a_correction_round(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    sloppy = copy.deepcopy(GOOD)
    e7 = next(e for e in sloppy["events"] if e["id"] == "e7")
    next(e for e in sloppy["events"] if e["id"] == "e9")["pays_off"] = e7["text"]  # the text, not "e7"
    summary, llm = run_ledger(p, [sloppy])
    assert summary.ran == ["ledger"] and len(llm.calls) == 1
    assert next(e for e in store.load_ledger(p).events if e.id == "e9").pays_off == "e7"
