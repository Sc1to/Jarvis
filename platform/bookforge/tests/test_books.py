"""Adding books, titles, renaming a series, a book's own brief, redoing a layer, editing documents, stopping a job."""

import json
import subprocess
import threading
import time

import pytest

from bookforge import books, cancel, documents, ops
from bookforge.constants import REDO_NOTE
from bookforge.errors import BookforgeError
from bookforge.jobs import JobManager
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.llm import FakeLLMClient
from bookforge.project import Project
from conftest import RuleLLM
from test_direction import good_script, north_star, synopsis, commits, go


def git(project, *args):
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


# ── titles, new books, renaming a series ────────────────────────────────────

def test_a_book_title_is_kept_and_cleaned(project):
    assert books.set_title(project, "  The   Ledger \n") == "The Ledger"
    assert Project.open(project.root).state.title == "The Ledger"
    assert books.titles(project.root) == {"b1": "The Ledger"}
    assert "b1: titled 'The Ledger'" in commits(project)[0]


def test_bad_titles_are_refused(project):
    for bad in ("", "   ", "x" * 200):
        with pytest.raises(BookforgeError):
            books.set_title(project, bad)


def test_a_new_book_gets_the_next_id_a_brief_a_title_and_its_own_state(project):
    b2 = books.add_book(project.root, "The Second Book", "Anna returns to the harbour.")
    assert (b2.book, b2.state.title) == ("b2", "The Second Book")
    assert books.brief_path(project.root, "b2").read_text() == "Anna returns to the harbour.\n"
    assert books.book_ids(project.root) == ["b1", "b2"]
    assert all(i.status == "pending" for i in b2.state.layers.values())  # no series north star exists yet
    assert books.add_book(project.root, "Third", "More.").book == "b3"
    assert "series: added book b2 'The Second Book'" in commits(project)


def test_a_new_book_inherits_an_existing_series_north_star(project):
    go(project, FakeLLMClient(good_script()), until="series_north_star")
    b2 = books.add_book(project.root, "Two", "Brief two.")
    item = b2.state.layers["series_north_star"]
    assert (item.status, item.note) == ("accepted", books.INHERITED)
    assert b2.state.layers["book_north_star"].status == "pending"


def test_an_id_a_deleted_book_used_is_never_handed_out_again(project):
    from bookforge import deletion, vcs
    b2 = books.add_book(project.root, "Two", "Brief.")
    vcs.tag(project.root, "b2-direction-approved")  # what approving its checkpoint would have left behind
    deletion.delete_book(project.root, "b2")
    assert books.book_ids(project.root) == ["b1"]
    assert books.add_book(project.root, "Again", "Brief.").book == "b3"  # b2's tags are still in the history


def test_without_any_tags_the_next_id_follows_the_folders(project):
    assert books.next_book_id(project.root) == "b2"


def test_adding_a_book_needs_a_series_a_brief_and_a_free_id(project, tmp_path):
    with pytest.raises(BookforgeError, match="brief is empty"):
        books.add_book(project.root, "T", "  ")
    with pytest.raises(BookforgeError, match="not a series"):
        books.add_book(tmp_path / "nothing", "T", "B")
    with pytest.raises(BookforgeError, match="already has a book"):
        books.add_book(project.root, "T", "B", book="b1")
    with pytest.raises(BookforgeError, match="not a valid book id"):
        books.add_book(project.root, "T", "B", book="B 2")


def test_the_book_north_star_is_written_from_the_books_own_brief(project):
    books.brief_path(project.root, "b1").write_text("THE BRIEF OF BOOK ONE\n")
    llm = FakeLLMClient(good_script())
    go(project, llm, until="book_north_star")
    prompt = llm.calls[1]["messages"][-1]["content"]
    assert "THE BRIEF OF BOOK ONE" in prompt and "A clerk finds a ledger" not in prompt


def test_a_book_without_a_brief_falls_back_to_the_series_premise(project):
    llm = FakeLLMClient(good_script())
    go(project, llm, until="book_north_star")
    assert "A clerk finds a ledger" in llm.calls[1]["messages"][-1]["content"]


def test_a_second_book_adopts_the_series_north_star_without_asking_the_model(project):
    go(project, FakeLLMClient(good_script("S1", "B1")), until="synopsis")
    b2 = books.add_book(project.root, "Two", "Brief two.")
    llm = FakeLLMClient({"critic": [north_star(marker="B2"), synopsis()]})
    summary = go(b2, llm)
    assert summary.ran == ["book_north_star", "synopsis"] and len(llm.calls) == 2  # no call for the series north star
    assert "S1" in (project.root / "north-star.md").read_text()  # the series north star is untouched


def test_renaming_a_series_moves_the_folder_and_keeps_its_history(project):
    data_dir = project.root.parent
    dest = books.rename_series(data_dir, project.root.name, "renamed")
    assert dest.name == "renamed" and not project.root.exists()
    again = Project.open(dest)
    assert again.book == "b1" and "series: initialized" in git(again, "log", "--format=%s")


def test_renaming_a_series_refuses_bad_names_clashes_and_missing_series(project, tmp_path):
    data_dir = project.root.parent
    other = Project.create(data_dir / "other", "Another premise.\n")
    with pytest.raises(BookforgeError, match="already exists"):
        books.rename_series(data_dir, project.root.name, "other")
    with pytest.raises(BookforgeError, match="lowercase"):
        books.rename_series(data_dir, project.root.name, "Bad Name")
    with pytest.raises(BookforgeError, match="same as the old"):
        books.rename_series(data_dir, project.root.name, project.root.name)
    with pytest.raises(BookforgeError, match="no series"):
        books.rename_series(data_dir, "ghost", "x")
    assert other.root.exists()


# ── redo ────────────────────────────────────────────────────────────────────

def direction_done(project):
    go(project, FakeLLMClient(good_script("OLD-S", "OLD-B")))
    return project


def test_redo_resets_the_layer_its_checkpoint_and_asks_for_a_cascade(project):
    direction_done(project)
    assert ops.redo_plan(project, "book_north_star") == ["synopsis"]
    with pytest.raises(BookforgeError, match="also resets synopsis"):
        ops.redo_layer(project, "book_north_star", "darker")
    out = ops.redo_layer(project, "book_north_star", "darker", cascade=True)
    assert out == {"layer": "book_north_star", "reset": ["book_north_star", "synopsis"], "note": True,
                   "archived": {"questions": 0, "facts": 0, "needs": 0}}
    assert project.state.layers["book_north_star"].status == "pending" and project.state.layers["synopsis"].status == "pending"
    assert project.state.layers["series_north_star"].status == "accepted"  # not built on the book north star
    assert project.state.checkpoints["direction"].status == "pending"
    assert (project.book_dir / "notes" / "book_north_star.md").read_text() == "darker\n"


def test_redo_commits_what_is_there_first_so_nothing_is_lost(project):
    direction_done(project)
    (project.book_dir / "synopsis.md").write_text("MY OWN HAND-WRITTEN SYNOPSIS " * 40)  # an uncommitted edit
    ops.redo_layer(project, "synopsis", "")
    log = git(project, "log", "--format=%s")
    assert "before redoing synopsis" in log and "redo synopsis" in log
    saved = git(project, "show", "HEAD~1:books/b1/synopsis.md")
    assert "MY OWN HAND-WRITTEN SYNOPSIS" in saved


def test_a_redone_document_is_written_again_with_the_note_and_the_previous_version(project):
    direction_done(project)
    ops.redo_layer(project, "book_north_star", "darker, and keep Anna's job", cascade=True)
    llm = FakeLLMClient({"critic": [north_star(marker="new"), synopsis()]})
    summary = go(project, llm)
    assert summary.ran == ["book_north_star", "synopsis"]  # the old valid file was NOT adopted
    prompt = llm.calls[0]["messages"][-1]["content"]
    assert "darker, and keep Anna's job" in prompt and "The previous version" in prompt and "premise" in prompt.split("The previous version")[1]
    assert "new" in (project.book_dir / "north-star.md").read_text()
    assert not (project.book_dir / "notes" / "book_north_star.md").exists()  # used up once accepted
    assert project.state.layers["book_north_star"].note != REDO_NOTE


def test_redo_without_a_note_just_writes_it_again_without_the_old_text(project):
    direction_done(project)
    ops.redo_layer(project, "synopsis", "")
    llm = FakeLLMClient({"critic": [synopsis()]})
    go(project, llm)
    assert "The previous version" not in llm.calls[0]["messages"][-1]["content"]


def test_redo_only_for_planning_layers_and_never_over_written_scenes(project):
    direction_done(project)
    with pytest.raises(BookforgeError, match="only planning layers"):
        ops.redo_layer(project, "prose")
    scene = project.book_dir / "scenes" / "ch01" / "s1"
    scene.mkdir(parents=True)
    (scene / "final.md").write_text("Written prose.")
    with pytest.raises(BookforgeError, match="already been written"):
        ops.redo_layer(project, "synopsis")
    assert project.state.layers["synopsis"].status == "accepted"  # nothing was touched


def test_the_notes_of_a_layer_not_being_redone_are_not_used(project):
    direction_done(project)
    ops.redo_layer(project, "synopsis", "make it shorter")
    llm = FakeLLMClient({"critic": [synopsis()]})
    go(project, llm)
    from bookforge import steering
    assert steering.read(project, "synopsis") == ""


# ── editing documents ───────────────────────────────────────────────────────

def doc(project, key):
    return documents.find(project, key)


def test_a_valid_north_star_edit_is_saved_and_committed(project):
    go(project, FakeLLMClient(good_script()), until="series_north_star")
    edited = north_star(marker="mine")
    documents.save(project, doc(project, "series_north_star"), edited)
    assert "mine" in (project.root / "north-star.md").read_text()
    assert commits(project)[0] == "b1: you edited Series north star"


def test_a_north_star_edit_that_breaks_it_is_refused_and_the_old_text_stays(project):
    go(project, FakeLLMClient(good_script()), until="series_north_star")
    before = (project.root / "north-star.md").read_text()
    with pytest.raises(documents.EditRefused) as e:
        documents.save(project, doc(project, "series_north_star"), north_star(drop=("Tone",)))
    assert any("Tone" in p for p in e.value.problems)
    assert (project.root / "north-star.md").read_text() == before


def test_an_older_north_star_without_realism_can_still_be_edited(project):
    old = north_star(drop=("Realism",))
    (project.root / "north-star.md").write_text(old)
    documents.save(project, doc(project, "series_north_star"), old.replace("tone", "tone2"))  # no new problem: allowed
    with pytest.raises(documents.EditRefused):
        documents.save(project, doc(project, "series_north_star"), old.replace("## Tone", "## Mood"))


def test_empty_text_and_research_notes_are_refused_but_the_banned_list_may_be_emptied(project):
    with pytest.raises(BookforgeError, match="empty"):
        documents.save(project, doc(project, "premise"), "  ")
    (project.root / "research" / "series_north_star.md").write_text("# notes\n- a fact\n")
    research = next(d for d in documents.catalog(project) if d.group == "Research")
    assert not documents.editable(research)
    with pytest.raises(BookforgeError, match="cannot be edited"):
        documents.save(project, research, "x")
    documents.save(project, doc(project, "banned"), "")
    assert (project.root / "style" / "banned.txt").read_text() == ""


def test_an_acts_edit_with_broken_yaml_is_refused_and_restored(project):
    from structure_fakes import ready
    p = ready(project)
    (p.root / "books" / "b1" / "acts.yaml").write_text("acts: []\n")
    with pytest.raises(documents.EditRefused):
        documents.save(p, doc(p, "acts"), "acts: [this is: not valid yaml\n")
    assert (p.root / "books" / "b1" / "acts.yaml").read_text() == "acts: []\n"


def test_the_book_brief_can_be_created_by_editing_it(project):
    brief = doc(project, "book_brief")
    assert not brief.exists
    documents.save(project, brief, "A brief about the second voyage.")
    assert books.brief_path(project.root, "b1").read_text() == "A brief about the second voyage.\n"


# ── stopping a job ──────────────────────────────────────────────────────────

def test_a_cancelled_handler_stops_the_run_without_flagging_the_layer(project):
    def stops(ctx):
        raise cancel.Cancelled()

    summary = run(project, FakeLLMClient({}), {**HANDLERS, "series_north_star": stops})
    assert summary.stopped == "cancelled" and summary.exit_code == 0 and "paused at your request" in summary.detail
    assert project.state.layers["series_north_star"].status == "pending"  # not flagged: it is simply done again next time


def test_cancel_is_not_swallowed_by_the_handlers_that_survive_failures():
    def swallows():
        try:
            cancel.bind(threading.Event())
            cancel._local.event.set()
            cancel.check()
        except Exception:
            return "swallowed"
        return "not reached"

    with pytest.raises(cancel.Cancelled):
        swallows()
    cancel.bind(None)


def test_a_running_job_can_be_stopped_and_ends_cancelled(tmp_path):
    jobs = JobManager()
    started = threading.Event()

    def work():
        started.set()
        for _ in range(500):
            time.sleep(0.01)
            cancel.check()  # what the model client does before every call
        return {"finished": True}

    job = jobs.start(tmp_path, "s", "b1", "run", {}, work)
    assert started.wait(2)
    assert jobs.cancel(tmp_path, "s", job.id).cancel_requested
    jobs.wait(job.id, 5)
    assert job.status == "cancelled" and job.result is None and jobs.busy("s") is None
    saved = json.loads((tmp_path / "books" / "b1" / "logs" / "jobs" / f"{job.id}.json").read_text())
    assert saved["status"] == "cancelled" and saved["cancel_requested"] is True


def test_a_job_that_returns_after_a_stop_request_is_cancelled_too(tmp_path):
    jobs = JobManager()
    release = threading.Event()
    job = jobs.start(tmp_path, "s", "b1", "run", {}, lambda: (release.wait(2), {"stopped": "cancelled"})[1])
    jobs.cancel(tmp_path, "s")
    release.set()
    jobs.wait(job.id, 5)
    assert job.status == "cancelled"


def test_there_is_nothing_to_cancel_when_nothing_runs(tmp_path):
    with pytest.raises(BookforgeError, match="no running job"):
        JobManager().cancel(tmp_path, "s")


def test_the_model_client_stops_before_asking_again():
    from bookforge.config import load_config
    from bookforge.llm import HttpLLMClient
    config = load_config()
    config.models.writer.model = "m"
    client = HttpLLMClient(config)
    stop = threading.Event()
    stop.set()
    cancel.bind(stop)
    try:
        with pytest.raises(cancel.Cancelled):
            client.complete("writer", [{"role": "user", "content": "hi"}])
    finally:
        cancel.bind(None)


# ── redo moves the research of the reset layers to the archive ──────────────

def _research(project):
    """Research made by two layers: a fact, a question and three needs (one decided by the author) for each."""
    from bookforge.research.notes import QuestionRecord, stores_for
    store = stores_for(project)["book"]
    for layer in ("synopsis", "acts"):
        f = store.add_fact(claim=f"A fact from {layer}.", url=f"https://x.example/{layer}", title="t", fetched="2026-11-06",
                           quote="a quote that is long enough", layer=layer, question=f"What about {layer}?")
        store.add_question(QuestionRecord(layer=layer, question=f"What about {layer}?", query="q", answered=True, fact_ids=[f.id]))
        store.add_need(layer=layer, question=f"Look up {layer}", stance="ground", fact_ids=[f.id], status="approved", decided_by="auto")
        store.add_need(layer=layer, question=f"Invent for {layer}", stance="invent", rule="A rule.", status="proposed")
        mine = store.add_need(layer=layer, question=f"My decision for {layer}", stance="invent", rule="My rule.", status="proposed")
        ops.decide_need(project, mine.id, approve=True)
        (store.dir / f"{layer}.md").parent.mkdir(parents=True, exist_ok=True)
        (store.dir / f"{layer}.md").write_text(f"# notes for {layer}\n")
    return store


def test_redo_archives_the_reset_layers_research_and_keeps_the_authors_decisions(project):
    store = _research(project)
    out = ops.redo_layer(project, "synopsis", "")
    assert out["reset"] == ["synopsis"] and out["archived"] == {"questions": 1, "facts": 1, "needs": 2}
    assert [f.layer for f in store.facts()] == ["acts"] and [q.layer for q in store.current_questions()] == ["acts"]  # other layers keep theirs
    kept = {n.question: n for n in store.needs()}
    assert "My decision for synopsis" in kept and kept["My decision for synopsis"].status == "approved"  # yours stays
    assert "Look up synopsis" not in kept and "Invent for synopsis" not in kept and "Look up acts" in kept
    assert not (store.dir / "synopsis.md").exists() and (store.dir / "acts.md").exists()


def test_what_was_archived_is_all_in_the_archive_and_nothing_is_deleted(project):
    store = _research(project)
    ops.redo_layer(project, "synopsis", "")
    files = sorted(p.name for p in store.archive_dir.iterdir())
    assert any(n.endswith("-synopsis.md") for n in files)
    [records] = [p for p in store.archive_dir.glob("*.jsonl")]
    kinds = [json.loads(l)["kind"] for l in records.read_text().splitlines()]
    assert sorted(kinds) == ["fact", "need", "need", "question"]
    assert "A fact from synopsis." in records.read_text()
    assert "before redoing synopsis" in git(project, "log", "--format=%s")  # everything as it was is committed first, too


def test_a_fact_id_that_was_archived_is_never_given_to_a_new_fact(project):
    store = _research(project)
    assert [f.id for f in store.facts()] == ["b1-0001", "b1-0002"]
    ops.redo_layer(project, "synopsis", "")  # b1-0001 moves to the archive
    new = store.add_fact(claim="New.", url="https://y.example", title="t", fetched="2026-11-06", quote="another long quote here", layer="synopsis", question="q")
    assert new.id == "b1-0003"


def test_a_kept_decision_does_not_point_at_a_fact_that_moved(project):
    from bookforge.research.notes import stores_for
    store = stores_for(project)["book"]
    f = store.add_fact(claim="Basis.", url="https://x.example/b", title="t", fetched="2026-11-06", quote="a quote that is long enough", layer="synopsis", question="q")
    n = store.add_need(layer="synopsis", question="Extend it", stance="extrapolate", rule="Assume this.", fact_ids=[f.id], status="proposed")
    ops.decide_need(project, n.id, approve=True)
    ops.redo_layer(project, "synopsis", "")
    [kept] = store.needs()
    assert kept.status == "approved" and kept.fact_ids == []
    assert "no facts found yet" in (store.dir / "needs.md").read_text()


def test_redo_without_any_research_creates_no_archive(project):
    from bookforge.research.notes import stores_for
    ops.redo_layer(project, "synopsis", "")
    assert not stores_for(project)["book"].archive_dir.exists()


def test_the_series_wide_research_is_only_archived_when_the_series_has_one_book(project):
    from bookforge.research.notes import stores_for
    series = stores_for(project)["series"]
    series.add_fact(claim="Series fact.", url="https://s.example", title="t", fetched="2026-11-06", quote="a quote that is long enough", layer="series_north_star", question="q")
    out = ops.redo_layer(project, "series_north_star", "")
    assert out["archived"]["facts"] == 1 and series.facts() == []  # the only book: its research moves
    series.add_fact(claim="Series fact 2.", url="https://s2.example", title="t", fetched="2026-11-06", quote="a quote that is long enough", layer="series_north_star", question="q2")
    books.add_book(project.root, "Two", "Brief two.")
    project.state.set_layer_status("series_north_star", "accepted")
    out = ops.redo_layer(project, "series_north_star", "")
    assert out["archived"]["facts"] == 0 and len(series.facts()) == 1  # another book may cite it: left alone
