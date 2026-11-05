import subprocess

import pytest
from typer.testing import CliRunner

from bookforge import cli
from bookforge.bible import store
from bookforge.bible.lookup import state_at
from bookforge.bible.validate import validate_bible
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.llm import LLMError
from bookforge.project import Project
from bookforge.research.search import FakeWebClient
from bookforge.state import load_state

from conftest import RuleLLM
from structure_fakes import (
    SMALL_CONFIG, acts, chapters_act1, chapters_act2, direction_rules, dump, ready, rules, scenes_reply, small,
)


def go(project, llm, until=None, web=None):
    return run(project, llm, HANDLERS, until=until, web=web)


def git(project, *args):
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


@pytest.fixture
def base(project):
    return ready(project)


@pytest.fixture
def built(base):
    llm = RuleLLM(rules())
    summary = go(base, llm)
    assert summary.stopped == "checkpoint", summary.detail
    return base


# ── layer 4: acts ───────────────────────────────────────────────────────────

def test_acts_are_written_normalised_and_committed(base):
    llm = RuleLLM(rules())
    summary = go(base, llm, until="acts")
    assert summary.ran == ["acts"] and len(llm.calls) == 1
    written = store.load_acts(base)
    assert [a.id for a in written] == ["b1.act1", "b1.act2"] and sum(a.chapter_count for a in written) == 4
    assert "chapter_count: 2" in (base.root / "books/b1/acts.yaml").read_text()
    assert git(base, "log", "-1", "--format=%s").strip() == "b1.acts: accepted"
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "2 to 2 acts" in prompt and "between 4 and 4" in prompt and "A long synopsis." in prompt
    assert llm.calls[0]["role"] == "critic"


def test_acts_reply_with_problems_is_corrected(base):
    def reply(messages):
        return dump(acts((1, 1))) if len(messages) == 2 else dump(acts())

    llm = RuleLLM([("Divide the book into ACTS", reply)])
    assert go(base, llm, until="acts").ran == ["acts"]
    assert len(llm.calls) == 2
    assert "add up to 2" in llm.calls[1]["messages"][-1]["content"]


def test_acts_that_never_pass_flag_the_layer(base):
    llm = RuleLLM([("Divide the book into ACTS", dump(acts((9, 9))))])
    summary = go(base, llm, until="acts")
    assert summary.stopped == "failed" and "still has problems after 2 correction round" in summary.detail
    assert load_state(base.state_path).layers["acts"].status == "flagged"
    assert not (base.root / "books/b1/acts.yaml").exists()


# ── layers 4-6 together ─────────────────────────────────────────────────────

def test_full_structure_run_stops_at_the_structure_checkpoint(base):
    llm = RuleLLM(rules())
    summary = go(base, llm)
    assert summary.ran == ["acts", "chapters", "scenes"]
    assert summary.stopped == "checkpoint" and "structure" in summary.detail
    for f in ("books/b1/acts.yaml", "books/b1/chapters.yaml", "books/b1/scenes.yaml",
              "bible/constants.yaml", "bible/tracks.yaml", "bible/timeline.yaml"):
        assert f in summary.detail
    assert len(llm.calls) == 8  # acts, cast, 2 chapter calls, 4 scene calls
    assert base.state.checkpoints["structure"].status == "waiting"


def test_the_assembled_files_are_complete_and_consistent(built):
    chapters = store.load_chapters(built)
    assert [(c.id, c.act) for c in chapters] == [("b1.ch01", "b1.act1"), ("b1.ch02", "b1.act1"), ("b1.ch03", "b1.act2"), ("b1.ch04", "b1.act2")]
    assert [e.id for e in store.load_constants(built).entities] == ["anna", "jonas", "harbor", "vestry", "ledger"]
    scenes = store.load_scenes(built)
    assert [s.id for s in scenes] == [f"b1.ch0{c}.s{n}" for c in range(1, 5) for n in (1, 2)]
    assert [(t.id, t.day) for t in store.load_timeline(built)][:4] == [("b1.ch01.s1", 1), ("b1.ch01.s2", 1), ("b1.ch02.s1", 2), ("b1.ch02.s2", 3)]
    assert validate_bible(built, require_scenes=True) == []
    assert not (built.book_dir / "work").exists()


def test_tracks_are_extended_by_later_acts_and_pinned_to_scenes(built):
    tracks = {t.id: t for t in store.load_tracks(built)}
    wound = tracks["anna-wound"]
    assert [(e.from_, e.must_show) for e in wound.plan] == [("b1.ch02.s2", True), ("b1.ch04.s1", True)]
    assert wound.entity == "anna" and wound.kind == "physical"
    assert [e.from_ for e in tracks["jonas-knows"].plan] == ["b1.ch01.s1", "b1.ch03.s1"]
    # created at version 1 by the chapters, then bumped once per chapter whose entries the scenes refined
    assert wound.version == 3 and tracks["jonas-knows"].version == 3


def test_state_lookups_work_on_the_built_bible(built):
    tracks = store.load_tracks(built)
    [s] = state_at(tracks, "b1.ch04.s1", ["anna"])
    assert s.value == "healed; scar remains" and s.begins_here and s.must_show and s.previous.startswith("deep cut")
    assert state_at(tracks, "b1.ch02.s1", ["anna"]) == []  # the wound has not happened yet
    assert state_at(tracks, "b1.ch03.s2", ["anna"])[0].value.startswith("deep cut")


def test_later_calls_see_the_earlier_results(built):
    llm = RuleLLM(rules())
    go(Project.open(built.root), llm, until="acts")  # nothing to do, layers are accepted; just a sanity check
    assert llm.calls == []


def test_prompts_carry_the_context_forward(base):
    llm = RuleLLM(rules())
    go(base, llm)
    act2 = llm.calls_matching("b1.ch03 to b1.ch04")[0]["messages"][1]["content"]
    assert "b1.ch01 Chapter 1" in act2 and "anna-wound" in act2 and "jonas-knows" in act2
    assert "anna (character): Anna Voss; grey eyes; left-handed" in act2
    ch3 = llm.calls_matching("Scene ids are consecutive: b1.ch03.s1")[0]["messages"][1]["content"]
    assert "previous scene (b1.ch02.s2) took place on day 3" in ch3
    assert "b1.ch02 Chapter 2" in ch3 and "b1.ch04 Chapter 4" in ch3
    ch2 = llm.calls_matching("Scene ids are consecutive: b1.ch02.s1")[0]["messages"][1]["content"]
    assert "planned: from b1.ch02: deep cut, left shoulder; bleeding [must_show]" in ch2


def test_every_step_is_committed_with_its_files(built):
    log = git(built, "log", "--format=%s").split("\n")
    assert log[:3] == ["b1.scenes: accepted", "b1.chapters: accepted", "b1.acts: accepted"]
    tracked = git(built, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert {"bible/constants.yaml", "bible/tracks.yaml", "bible/timeline.yaml", "books/b1/scenes.yaml"} <= set(tracked)
    assert not any("/work/" in t for t in tracked)
    assert git(built, "status", "--porcelain").strip() == ""


# ── correction, failure and resume ──────────────────────────────────────────

def test_a_bad_chapter_reply_is_corrected_and_the_corrected_piece_is_kept(base):
    bad = chapters_act1()
    bad["chapters"][0]["pov"] = "nobody"

    def reply(messages):
        return dump(bad) if len(messages) == 2 else dump(chapters_act1())

    llm = RuleLLM([r for r in rules() if "ch01 to b1.ch02" not in r[0]] + [("Plan exactly 2 chapters, b1.ch01 to b1.ch02", reply)])
    assert go(base, llm, until="chapters").ran == ["acts", "chapters"]
    correction = [c for c in llm.calls if len(c["messages"]) == 4][0]["messages"][-1]["content"]
    assert "'nobody' is not in the cast" in correction
    assert store.load_chapters(base)[0].pov == "anna"


def test_a_failure_part_way_keeps_finished_pieces_and_a_rerun_resumes(base):
    failing = {"on": True}

    def act2(messages):
        if failing["on"]:
            raise LLMError("colibri went away")
        return dump(chapters_act2())

    first = RuleLLM([r for r in rules() if "ch03 to b1.ch04" not in r[0]] + [("Plan exactly 2 chapters, b1.ch03 to b1.ch04", act2)])
    summary = go(base, first)
    assert summary.stopped == "failed" and "colibri went away" in summary.detail
    assert load_state(base.state_path).layers["chapters"].status == "flagged"
    assert sorted(p.name for p in (base.book_dir / "work/chapters").iterdir()) == ["act1.yaml", "cast.yaml"]
    assert not (base.book_dir / "chapters.yaml").exists()

    failing["on"] = False
    second = RuleLLM(first.rules)
    summary = go(Project.open(base.root), second)
    assert summary.stopped == "checkpoint"
    asked = [c["messages"][1]["content"] for c in second.calls]
    assert not any("List the CAST" in a for a in asked) and not any("b1.ch01 to b1.ch02" in a for a in asked)
    assert any("b1.ch03 to b1.ch04" in a for a in asked)
    assert len(second.calls) == 1 + 4  # act2's chapters, then the four chapters' scenes


def test_scenes_resume_chapter_by_chapter(base):
    go(base, RuleLLM(rules()), until="chapters")
    calls = {"n": 0}

    def ch3(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("offline")
        return dump(scenes_reply(3))

    flaky = RuleLLM([r for r in rules() if "b1.ch03.s1" not in r[0]] + [("Scene ids are consecutive: b1.ch03.s1", ch3)])
    assert go(Project.open(base.root), flaky).stopped == "failed"
    assert sorted(p.name for p in (base.book_dir / "work/scenes").iterdir()) == ["ch01.yaml", "ch02.yaml"]

    again = RuleLLM(flaky.rules)
    assert go(Project.open(base.root), again).stopped == "checkpoint"
    assert len(again.calls) == 2  # only chapters 3 and 4


def test_a_dropped_track_in_the_scenes_is_corrected(base):
    go(base, RuleLLM(rules()), until="chapters")

    def reply(messages):
        return dump(scenes_reply(2, drop_tracks=True)) if len(messages) == 2 else dump(scenes_reply(2))

    llm = RuleLLM([r for r in rules() if "b1.ch02.s1" not in r[0]] + [("Scene ids are consecutive: b1.ch02.s1", reply)])
    assert go(Project.open(base.root), llm).stopped == "checkpoint"
    correction = [c for c in llm.calls if len(c["messages"]) == 4][0]["messages"][-1]["content"]
    assert "track 'anna-wound' already has planned states in b1.ch02" in correction


def test_a_layer_that_cannot_pass_is_flagged_without_a_partial_file(base):
    llm = RuleLLM([r for r in rules() if "List the CAST" not in r[0]] + [("List the CAST AND WORLD", "entities: []")])
    summary = go(base, llm)
    assert summary.stopped == "failed" and "at least one" in summary.detail
    assert not (base.book_dir / "chapters.yaml").exists() and not (base.root / "bible/tracks.yaml").read_text().count("anna")


def test_chapters_require_accepted_acts_and_a_model(base):
    assert go(base, RuleLLM(rules()), until="acts").ran == ["acts"]
    (base.book_dir / "acts.yaml").write_text("acts: []\n")
    fresh = Project.open(base.root)
    assert "acts.yaml is missing or empty" in go(fresh, RuleLLM(rules()), until="chapters").detail
    assert go(Project.open(base.root), None, until="chapters").stopped == "failed"


# ── adoption ────────────────────────────────────────────────────────────────

def test_existing_structure_files_are_adopted_not_regenerated(built):
    for layer in ("chapters", "scenes"):
        built.state.set_layer_status(layer, "pending")
    built.state.checkpoints["structure"].status = "pending"
    built.save_state()
    llm = RuleLLM([])
    summary = go(Project.open(built.root), llm)
    assert summary.ran == ["chapters", "scenes"] and llm.calls == []
    assert summary.notes["chapters"] == "adopted existing file" and summary.notes["scenes"] == "adopted existing file"


def test_an_invalid_existing_file_is_refused_not_overwritten(built):
    built.state.set_layer_status("chapters", "pending")
    built.save_state()
    path = built.book_dir / "chapters.yaml"
    chapters = store.load_chapters(built)[:-1]  # one chapter short of the configured 4
    store.save_chapters(built, chapters)
    before = path.read_text()
    summary = go(Project.open(built.root), RuleLLM([]))
    assert summary.stopped == "failed" and "not acceptable" in summary.detail and "expected 4 to 4" in summary.detail
    assert path.read_text() == before


# ── per-chapter research ────────────────────────────────────────────────────

def research_rules(cite=False):
    q = '{"questions": [{"question": "How were harbor warehouses lit?", "query": "harbor warehouse lighting", "sensitive": false}]}'
    f = '{"facts": [{"claim": "Warehouses used oil lamps.", "quote": "warehouses were lit by oil lamps hung from the beams"}]}'
    out = [r for r in rules() if "b1.ch02.s1" not in r[0]]
    reply = scenes_reply(2)
    if cite:
        reply["scenes"][0]["research"] = ["b1-0001"]
    return out + [("Scene ids are consecutive: b1.ch02.s1", dump(reply)), ("Decide what the author needs", q), ("Source page: https://a.example/w", f)]


def research_web():
    from urllib.parse import quote
    return FakeWebClient(
        searches={"harbor warehouse lighting": "results"},
        links={"harbor warehouse lighting": [{"text": "w", "href": "https://duckduckgo.com/l/?uddg=" + quote("https://a.example/w", safe="")}]},
        pages={"https://a.example/w": "In those years warehouses were lit by oil lamps hung from the beams, and fires were common."},
    )


def test_scene_research_runs_per_chapter_before_its_scenes_and_scenes_may_cite_it(base):
    (base.root / "config.yaml").write_text(SMALL_CONFIG.replace("scene_questions: 0", "scene_questions: 1"))
    p = Project.open(base.root)
    go(p, RuleLLM(rules()), until="chapters")
    llm = RuleLLM(research_rules(cite=True))
    summary = go(Project.open(base.root), llm, web=research_web())
    assert summary.stopped == "checkpoint", summary.detail
    first = llm.calls_matching("Scene ids are consecutive: b1.ch01.s1")[0]["messages"][1]["content"]
    assert "[b1-0001] Warehouses used oil lamps." in first  # research for a chapter runs before its scenes are planned
    second = llm.calls_matching("Scene ids are consecutive: b1.ch02.s1")[0]["messages"][1]["content"]
    assert "[b1-0001] Warehouses used oil lamps." in second  # and stays available to the chapters after it
    assert store.load_scenes(base)[2].research == ["b1-0001"]
    assert "books/b1/research/sources.jsonl" in git(base, "ls-tree", "-r", "--name-only", "HEAD")


def test_a_scene_citing_an_unknown_fact_is_corrected(base):
    go(base, RuleLLM(rules()), until="chapters")
    bad = scenes_reply(2)
    bad["scenes"][0]["research"] = ["b1-0042"]

    def reply(messages):
        return dump(bad) if len(messages) == 2 else dump(scenes_reply(2))

    llm = RuleLLM([r for r in rules() if "b1.ch02.s1" not in r[0]] + [("Scene ids are consecutive: b1.ch02.s1", reply)])
    assert go(Project.open(base.root), llm).stopped == "checkpoint"
    assert "unknown research fact id(s) b1-0042" in [c for c in llm.calls if len(c["messages"]) == 4][0]["messages"][-1]["content"]


def test_scene_research_is_off_when_scene_questions_is_zero(base):
    web = research_web()
    llm = RuleLLM(rules() + [("Decide what the author needs", '{"questions": []}')])
    assert go(base, llm, web=web).stopped == "checkpoint"
    assert web.calls == []
    # research runs once after the acts and once after the chapters; none per chapter
    assert len(llm.calls_matching("Decide what the author needs")) == 2


# ── cross-checks on the finished files ──────────────────────────────────────

def mutate_tracks(project, fn):
    tracks = store.load_tracks(project)
    fn(tracks)
    store.save_tracks(project, tracks)


@pytest.mark.parametrize("mutate,needle", [
    (lambda t: setattr(t[0], "entity", "ghost"), "'ghost' is not in the cast"),
    (lambda t: setattr(t[0].plan[0], "from_", "b1.ch02.s9"), "b1.ch02.s9 is not a scene"),
    (lambda t: setattr(t[0].plan[0], "from_", "b1.ch09"), "b1.ch09 is not a chapter"),
    (lambda t: setattr(t[0].plan[0], "from_", "b1.ch02"), "must_show state at b1.ch02 is not pinned to a scene"),
    (lambda t: t[0].plan.append(t[0].plan[0].model_copy()), "two entries start at"),
])
def test_validate_bible_catches_track_problems(built, mutate, needle):
    mutate_tracks(built, mutate)
    assert any(needle in p for p in validate_bible(built, require_scenes=True))


def test_validate_bible_catches_timeline_and_structure_problems(built):
    timeline = store.load_timeline(built)
    store.save_timeline(built, timeline[:-1])
    assert any("b1.ch04.s2: missing from timeline.yaml" in p for p in validate_bible(built))
    timeline[2].day = 99
    store.save_timeline(built, timeline)
    assert any("before day 99" in p for p in validate_bible(built))

    chapters = store.load_chapters(built)
    chapters[1].act = "b1.act9"
    chapters[2].pov = "harbor"
    store.save_chapters(built, chapters)
    problems = validate_bible(built)
    assert any("act 'b1.act9' is not in acts.yaml" in p for p in problems) and any("'harbor' is a place" in p for p in problems)

    scenes = store.load_scenes(built)
    store.save_scenes(built, [s for s in scenes if s.id != "b1.ch01.s2"])
    assert any("b1.ch01: has 1 scenes, expected 2 to 3" in p for p in validate_bible(built))


def test_validate_bible_reports_unreadable_files(built):
    (built.root / "bible/tracks.yaml").write_text("tracks: [unclosed")
    assert any("not valid YAML" in p for p in validate_bible(built))


# ── through the CLI ─────────────────────────────────────────────────────────

def test_full_cli_flow_to_the_structure_checkpoint_and_state_lookups(tmp_path, monkeypatch):
    llm = RuleLLM(direction_rules() + rules())
    monkeypatch.setattr(cli, "build_client", lambda p: llm)
    monkeypatch.setattr(cli, "build_web_client", lambda p: None)
    runner = CliRunner()
    premise = tmp_path / "p.md"
    premise.write_text("A clerk finds a ledger.\n")
    series = tmp_path / "s"
    assert runner.invoke(cli.app, ["new", str(series), "--premise", str(premise)]).exit_code == 0
    (series / "config.yaml").write_text(SMALL_CONFIG)

    first = runner.invoke(cli.app, ["run", str(series)])
    assert first.exit_code == 0 and "approve direction" in first.output
    assert runner.invoke(cli.app, ["approve", str(series), "direction"]).exit_code == 0

    second = runner.invoke(cli.app, ["run", str(series)])
    assert second.exit_code == 0, second.output
    for line in ("accepted: acts", "accepted: chapters (4 chapters, 5 entities, 2 tracks)", "accepted: scenes (8 scenes in 4 chapters, 2 tracks)",
                 "approve structure", "bible/tracks.yaml"):
        assert line in second.output
    assert runner.invoke(cli.app, ["approve", str(series), "structure"]).exit_code == 0

    last = runner.invoke(cli.app, ["run", str(series)])
    assert last.exit_code == 2 and "layer 'prose' has no implementation yet" in last.output

    at = runner.invoke(cli.app, ["state-at", str(series), "b1.ch04.s1"])
    assert at.exit_code == 0, at.output
    assert "day 40, dusk" in at.output and "anna-wound (anna, physical) since b1.ch04.s1: healed; scar remains" in at.output
    assert "[begins here] [must show on the page]" in at.output and "before: deep cut, left shoulder; bleeding" in at.output

    early = runner.invoke(cli.app, ["state-at", str(series), "b1.ch01.s1"])
    assert "jonas-knows" in early.output and "anna-wound" not in early.output
    only = runner.invoke(cli.app, ["state-at", str(series), "b1.ch04.s2", "-e", "jonas"])
    assert "jonas-knows" in only.output and "anna-wound" not in only.output
    chapter = runner.invoke(cli.app, ["state-at", str(series), "b1.ch03", "-e", "jonas"])
    assert "jonas-knows" in chapter.output
    nothing = runner.invoke(cli.app, ["state-at", str(series), "b1.ch01", "-e", "anna"])
    assert "no tracked states apply here" in nothing.output
    bad = runner.invoke(cli.app, ["state-at", str(series), "chapter-four"])
    assert bad.exit_code == 1 and "not a position" in bad.output
