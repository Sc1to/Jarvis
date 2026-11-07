"""Milestone 14.8: staleness detection, the fix ladder (re-check, patch, redraft) and change requests."""

import json
import re

import yaml
from typer.testing import CliRunner

from bookforge import changes, cli, scenefiles, stale
from bookforge.bible import store
from bookforge.deps import Deps, diff, tag
from bookforge.layers.runner import StepContext
from bookforge.project import Project
from conftest import RuleLLM
from qc_fakes import CONTINUITY, EXTRACT, REVISE, between, continuity, extractor, reviser, user
from test_prose_qc import COMMON, SID, book, calls, go, qc_rules, review, good  # noqa: F401  (book is a fixture)

S2 = "b1.ch01.s2"
BASE_VERSION = 3  # the version the layers leave the jonas-knows track at in this small book


def written(book, **kw):
    """The first chapter written and accepted (the run then waits at the voice checkpoint)."""
    llm = RuleLLM(qc_rules(**kw))
    go(book, llm)
    p = Project.open(book.root)
    assert p.state.items[SID].status == "accepted" and p.state.items[S2].status == "accepted"
    return p


def ctx(project, llm):
    return StepContext(project=project, layer="prose", llm=llm)


def edit_entity(project, entity, old, new):
    constants = store.load_constants(project)
    for e in constants.entities:
        if e.id == entity:
            e.facts = [new if f == old else f for f in e.facts]
    store.save_constants(project, constants)


def scan_ids(project):
    return [s.scene for s in stale.scan(project).scenes]


# ── dependency diff ─────────────────────────────────────────────────────────

def test_diff_names_what_changed_was_added_and_was_removed():
    old = Deps(scene=tag("s", "a"), bible=[tag("x", 1), tag("y", 1)], summaries=[tag("z", 1)])
    new = Deps(scene=tag("s", "a"), bible=[tag("x", 2), tag("w", 1)], summaries=[tag("z", 2)])
    assert [r.text() for r in diff(old, new)] == ["bible: x changed", "bible: y removed", "bible: w added"]  # summaries do not count


# ── detection ───────────────────────────────────────────────────────────────

def test_nothing_is_stale_right_after_writing(book):
    p = written(book)
    assert stale.scan(p).empty


def test_a_changed_cast_fact_makes_the_scenes_with_that_character_stale(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    report = stale.scan(p)
    assert [s.scene for s in report.scenes] == [SID, S2]
    assert "bible: entity:anna changed" in report.scenes[0].why()
    assert report.scenes[0].level == "recheck"


def test_a_changed_chapter_or_scene_plan_is_a_reason_and_a_changed_scene_means_redraft(book):
    p = written(book)
    scenes = store.load_scenes(p)
    scenes[0].beats = ["A different thing happens.", "Anna decides otherwise."]
    store.save_scenes(p, scenes)
    first = stale.scan(p).scenes[0]
    assert first.scene == SID and first.level == "redraft" and any(r.key == "scene" for r in first.reasons)


def test_a_track_change_after_the_scene_does_not_make_it_stale(book):
    p = written(book)
    tracks = store.load_tracks(p)
    wound = next(t for t in tracks if t.id == "anna-wound")  # begins in chapter 2: not part of a chapter 1 scene
    wound.plan[0].value = "a different wound"
    store.save_tracks(p, tracks)
    assert stale.scan(p).empty


def test_sync_marks_scenes_stale_in_state_and_back_when_the_change_is_undone(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    stale.sync_status(p, stale.scan(p))
    assert Project.open(book.root).state.items[SID].status == "stale"
    edit_entity(p, "anna", "green eyes", "grey eyes")
    stale.sync_status(p, stale.scan(p))
    assert Project.open(book.root).state.items[SID].status == "accepted"


def test_the_prose_layer_leaves_stale_scenes_alone(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    stale.sync_status(p, stale.scan(p))
    llm = RuleLLM(qc_rules())
    summary = go(Project.open(book.root), llm)
    assert not llm.calls  # waiting at the voice checkpoint; and nothing was rewritten
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    llm = RuleLLM(qc_rules())
    go(Project.open(book.root), llm)
    assert not any(f"Write scene {SID} " in c["messages"][1]["content"] for c in llm.calls)
    assert Project.open(book.root).state.items[SID].status == "stale"


# ── fixing: re-check ────────────────────────────────────────────────────────

def test_a_recheck_that_finds_nothing_refreshes_the_scene_without_rewriting_it(book):
    p = written(book)
    before = scenefiles.final_path(p, SID).read_text()
    version = p.state.items[SID].version
    edit_entity(p, "anna", "grey eyes", "green eyes")
    llm = RuleLLM(qc_rules())
    results = stale.fix_all(ctx(p, llm))
    assert [(r.scene, r.action) for r in results] == [(SID, "rechecked"), (S2, "rechecked")]
    assert scenefiles.final_path(p, SID).read_text() == before
    assert calls(llm, CONTINUITY) and not calls(llm, REVISE) and not calls(llm, "Write scene")
    assert stale.scan(p).empty
    item = Project.open(book.root).state.items[SID]
    assert item.status == "accepted" and item.version == version and "still agrees" in item.note


def test_a_style_only_change_is_rechecked_mechanically_with_no_model_calls(book):
    p = written(book)
    banned = p.root / "style" / "banned.txt"
    banned.write_text(banned.read_text() + "\nzzyzx\n")
    assert [r.key for s in stale.scan(p).scenes for r in s.reasons] == ["style", "style"]
    llm = RuleLLM([])
    results = stale.fix_all(ctx(p, llm))
    assert [r.action for r in results] == ["rechecked", "rechecked"] and not llm.calls
    assert stale.scan(p).empty


def test_a_newly_banned_phrase_is_patched_in_its_paragraph(book):
    p = written(book)
    final = scenefiles.final_path(p, SID).read_text()
    phrase = " ".join(final.split()[2:7])  # five words from the first paragraph
    assert phrase in final
    banned = p.root / "style" / "banned.txt"
    banned.write_text(banned.read_text() + f"\n{phrase}\n")
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser({phrase: "five other words entirely"}))))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert [(r.scene, r.action) for r in results] == [(SID, "patched")]
    new = scenefiles.final_path(p, SID).read_text()
    assert phrase not in new and "five other words entirely" in new
    assert not calls(llm, CONTINUITY)  # a style change does not need the continuity questions


# ── fixing: patch ───────────────────────────────────────────────────────────

def contradicting_book(book):
    drafts = {SID: [good(SID, 1) + " " + COMMON, good(SID, 2) + " " + COMMON]}
    return written(book, overrides=drafts)


def test_a_contradiction_after_a_change_is_patched_and_the_scene_re_summarised(book):
    p = contradicting_book(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    state = {"n": 0}
    flagged = continuity({"green eyes": ("yes", 0.9, COMMON)})
    clean = continuity()

    def cont(messages):
        state["n"] += 1
        return flagged(messages) if state["n"] == 1 else clean(messages)

    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, cont), revise=(REVISE, reviser({"grey eyes": "green eyes"}))))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert [(r.scene, r.action) for r in results] == [(SID, "patched")]
    text = scenefiles.final_path(p, SID).read_text()
    assert "green eyes" in text and "grey eyes" not in text
    assert calls(llm, "Summarise the scene below") and calls(llm, EXTRACT)  # summary and extraction redone
    fixes = review(p)["stale_fixes"]
    assert fixes[0]["action"] == "patched" and "entity:anna" in fixes[0]["why"]
    item = Project.open(book.root).state.items[SID]
    assert item.status == "accepted" and item.version == 2
    assert SID not in scan_ids(p)


def test_a_patch_that_does_not_fix_it_falls_back_to_a_redraft(book):
    p = contradicting_book(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    # the contradiction is reported in the old text; the redrafted text does not contain it, so it passes
    def cont(messages):
        scene = between(user(messages), "scene")
        return continuity({"green eyes": ("yes", 0.9, COMMON)} if COMMON in scene else {})(messages)

    llm = RuleLLM(qc_rules(overrides={SID: [good(SID, 3), good(SID, 4)]}, continuity=(CONTINUITY, cont), revise=(REVISE, reviser({}))))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert [(r.scene, r.action) for r in results] == [(SID, "redrafted")]
    assert COMMON not in scenefiles.final_path(p, SID).read_text()
    assert Project.open(book.root).state.items[SID].status == "accepted"


def test_text_the_author_wrote_is_never_patched_or_redrafted(book):
    p = contradicting_book(book)
    review_file = scenefiles.review_path(p, SID)
    r = json.loads(review_file.read_text())
    r["source"] = "adopted"
    review_file.write_text(json.dumps(r))
    before = scenefiles.final_path(p, SID).read_text()
    edit_entity(p, "anna", "grey eyes", "green eyes")
    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, continuity({"green eyes": ("yes", 0.9, COMMON)}))))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert [(r.scene, r.action) for r in results] == [(SID, "needs-author")]
    assert scenefiles.final_path(p, SID).read_text() == before and not calls(llm, REVISE)
    assert Project.open(book.root).state.items[SID].status == "flagged"


def test_a_continuity_check_that_cannot_answer_leaves_the_scene_stale(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, "not json at all")))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert results[0].action == "skipped" and "could not re-check" in results[0].note
    assert SID in scan_ids(p)


# ── fixing: redraft ─────────────────────────────────────────────────────────

def test_a_changed_scene_plan_is_redrafted_from_scratch(book):
    p = written(book)
    old = scenefiles.final_path(p, SID).read_text()
    scenes = store.load_scenes(p)
    scenes[0].beats = ["A different thing happens.", "Anna decides otherwise."]
    store.save_scenes(p, scenes)
    llm = RuleLLM(qc_rules(overrides={SID: [good(SID, 5), good(SID, 6)]}))
    results = stale.fix_all(ctx(p, llm), {SID})
    assert [(r.scene, r.action) for r in results] == [(SID, "redrafted")]
    assert calls(llm, "A different thing happens.")
    assert scenefiles.final_path(p, SID).read_text() != old
    assert SID not in scan_ids(p) and Project.open(book.root).state.items[SID].status == "accepted"


# ── the planning layers ─────────────────────────────────────────────────────

def test_a_changed_act_marks_its_chapters_and_a_changed_chapter_its_scenes(book):
    p = Project.open(book.root)
    stale.record_plan(p)
    assert stale.scan(p).empty
    acts = store.load_acts(p)
    acts[0].summary = "A rewritten summary of the first act."
    store.save_acts(p, acts)
    assert [(x.id, x.kind) for x in stale.scan(p).plan] == [("b1.ch01", "chapter"), ("b1.ch02", "chapter")]
    chapters = store.load_chapters(p)
    chapters[2].purpose = "A new purpose."
    store.save_chapters(p, chapters)
    ids = [x.id for x in stale.scan(p).plan]
    assert "b1.ch03.s1" in ids and "b1.ch03.s2" in ids


def test_accepting_a_planned_chapter_clears_it(book):
    p = Project.open(book.root)
    stale.record_plan(p)
    acts = store.load_acts(p)
    acts[0].summary = "A rewritten summary of the first act."
    store.save_acts(p, acts)
    stale.record_plan(p, {"b1.ch01"})
    assert [x.id for x in stale.scan(p).plan] == ["b1.ch02"]


def test_approving_structure_takes_the_snapshot(book):
    p = Project.open(book.root)
    p.state.checkpoints["structure"].status = "waiting"
    p.save_state()
    assert CliRunner().invoke(cli.app, ["approve", str(p.root), "structure"]).exit_code == 0
    assert stale.plan_deps_path(p).exists()


# ── change requests ─────────────────────────────────────────────────────────

def gap_book(book, with_inner_entry=False):
    p = Project.open(book.root)
    if with_inner_entry:  # a later entry in the same chapter: a change at s1 reaches only s1
        tracks = store.load_tracks(p)
        jonas = next(t for t in tracks if t.id == "jonas-knows")
        from bookforge.bible.models import PlanEntry
        jonas.plan.insert(1, PlanEntry(**{"from": S2, "value": "suspects something"}))
        store.save_tracks(p, tracks)
        import subprocess
        subprocess.run(["git", "-C", str(p.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(p.root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "inner entry"], check=True)
    with_gap, without, n = extractor(gap="jonas-knows"), extractor(), {"n": 0}

    def extract(messages):  # only the first scene shows a gap
        n["n"] += 1
        return (with_gap if n["n"] == 1 else without)(messages)

    go(Project.open(book.root), RuleLLM(qc_rules(extract=(EXTRACT, extract))))
    return Project.open(book.root)


def test_a_gap_that_reaches_later_chapters_waits_for_the_author(book):
    p = gap_book(book)
    [cr] = changes.list_requests(p)
    assert (cr.status, cr.scope, cr.proposed_by, cr.track) == ("pending", "later_chapters", SID, "jonas-knows")
    assert cr.planned == "knows nothing about the ledger" and cr.observed == "something else" and SID in cr.affects and "b1.ch02.s1" in cr.affects
    assert review(p)["extraction"]["change_requests"] == [cr.id]
    jonas = next(t for t in store.load_tracks(p) if t.id == "jonas-knows")
    assert jonas.version == BASE_VERSION and len(jonas.plan) == 2  # the plan is untouched
    assert "1 change request(s) filed, 1 waiting for you" in p.state.items[SID].note


def test_a_gap_inside_one_chapter_is_applied_at_once(book):
    p = gap_book(book, with_inner_entry=True)
    cr = changes.get(p, "cr-0001")
    assert (cr.status, cr.scope, cr.decided_by, cr.affects) == ("applied", "within_chapter", "auto", [SID])
    jonas = next(t for t in store.load_tracks(p) if t.id == "jonas-knows")
    assert jonas.version == BASE_VERSION + 1 and jonas.plan[0].value == "something else"


def test_never_means_no_change_request_is_applied_without_the_author(book):
    (book.root / "config.yaml").write_text((book.root / "config.yaml").read_text() + "  critic_may_accept: never\n")
    p = gap_book(book, with_inner_entry=True)
    assert changes.get(p, "cr-0001").status == "pending"


def test_one_request_per_scene_and_track(book):
    p = gap_book(book)
    scene = store.load_scenes(p)[0]
    again = changes.file_gaps(p, scene, store.load_scenes(p), [{"track": "jonas-knows", "planned": "x", "observed": "y", "evidence": ""}])
    assert again == [] and len(changes.list_requests(p)) == 1


def test_approving_applies_the_change_and_makes_the_dependent_scenes_stale(book):
    p = gap_book(book)
    assert stale.scan(p).empty
    changes.approve(p, "cr-0001")
    jonas = next(t for t in store.load_tracks(p) if t.id == "jonas-knows")
    assert jonas.version == BASE_VERSION + 1 and [e.from_ for e in jonas.plan][:2] == [SID, "b1.ch03.s1"] and jonas.plan[0].value == "something else"
    assert scan_ids(p) == [SID, S2]


def test_a_request_can_only_be_decided_once(book):
    p = gap_book(book)
    changes.approve(p, "cr-0001")
    for fn in (changes.approve, changes.reject):
        try:
            fn(p, "cr-0001")
        except changes.ChangeError as e:
            assert "already applied" in str(e)
        else:
            raise AssertionError("expected an error")


def test_a_dismissed_request_leaves_both_prose_and_plan_alone(book):
    p = gap_book(book)
    before = store.load_tracks(p)
    changes.dismiss(p, "cr-0001")
    assert changes.get(p, "cr-0001").status == "dismissed"
    assert store.load_tracks(p) == before  # the plan is untouched
    assert stale.scan(p).empty  # nothing is stale, nothing to patch
    assert not changes.open_rejections(p)
    try:
        changes.dismiss(p, "cr-0001")
    except changes.ChangeError as e:
        assert "already dismissed" in str(e)
    else:
        raise AssertionError("expected an error")


def test_a_rejected_request_patches_the_scene_to_agree_with_the_plan(book):
    p = gap_book(book)
    changes.reject(p, "cr-0001")
    st = stale.scan(p).scenes
    assert [s.scene for s in st] == [SID] and st[0].level == "patch" and "change request cr-0001 rejected" in st[0].why()[0]
    log = []

    def edit(messages):
        passage = between(user(messages), "passage")
        log.append(user(messages))
        return passage + " Jonas knew nothing."

    llm = RuleLLM(qc_rules(revise=(REVISE, edit)))
    results = stale.fix_all(ctx(p, llm))
    # the patch changed the end of the scene, which the next scene is built from: that one is re-checked
    assert [(r.scene, r.action) for r in results] == [(SID, "patched"), (S2, "rechecked")]
    assert "make the passage agree with the plan" in log[0] and "knows nothing about the ledger" in log[0]
    assert changes.get(p, "cr-0001").fixed is True and stale.scan(p).empty


# ── accepting as is ─────────────────────────────────────────────────────────

def test_accepting_a_scene_as_is_refreshes_it_without_any_model_call(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    stale.sync_status(p, stale.scan(p))
    stale.accept_as_is(Project.open(book.root), SID)
    assert scan_ids(Project.open(book.root)) == [S2]
    assert Project.open(book.root).state.items[SID].status == "accepted"


# ── the commands ────────────────────────────────────────────────────────────

def test_the_stale_command_lists_reasons_and_exits_1(book):
    p = written(book)
    runner = CliRunner()
    assert "nothing is out of date" in runner.invoke(cli.app, ["stale", str(p.root)]).output
    edit_entity(p, "anna", "grey eyes", "green eyes")
    out = runner.invoke(cli.app, ["stale", str(p.root)])
    assert out.exit_code == 1 and f"{SID}: stale, start with recheck" in out.output and "bible: entity:anna changed" in out.output
    assert Project.open(book.root).state.items[SID].status == "stale"


def test_the_stale_command_fixes_with_a_model(book, monkeypatch):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    monkeypatch.setattr(cli, "build_client", lambda project: RuleLLM(qc_rules()))
    out = CliRunner().invoke(cli.app, ["stale", str(p.root), "--fix"])
    assert out.exit_code == 0, out.output
    assert f"{SID}: rechecked (still agrees)" in out.output and "nothing is out of date" in out.output


def test_the_stale_command_accepts_a_scene_or_a_chapter(book):
    p = written(book)
    edit_entity(p, "anna", "grey eyes", "green eyes")
    out = CliRunner().invoke(cli.app, ["stale", str(p.root), "--accept", SID, "--accept", S2])
    assert out.exit_code == 0 and "nothing is out of date" in out.output
    bad = CliRunner().invoke(cli.app, ["stale", str(p.root), "--accept", "b1.ch99"])
    assert bad.exit_code == 1 and "not a scene or chapter" in bad.output


def test_the_changes_command_lists_approves_and_rejects(book):
    p = gap_book(book)
    runner = CliRunner()
    out = runner.invoke(cli.app, ["changes", str(p.root)])
    assert "cr-0001 [pending]" in out.output and "plan 'knows nothing about the ledger' -> prose 'something else'" in out.output
    out = runner.invoke(cli.app, ["changes", str(p.root), "--approve", "cr-0001"])
    assert "cr-0001: applied" in out.output and "stale --fix" in out.output
    assert "cr-0001 [applied, author]" in runner.invoke(cli.app, ["changes", str(p.root)]).output
    assert runner.invoke(cli.app, ["changes", str(p.root), "--reject", "cr-0001"]).exit_code == 1
