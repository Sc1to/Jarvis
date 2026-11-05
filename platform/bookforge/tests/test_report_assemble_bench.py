"""Milestone 14.9: the morning report, assembly into one manuscript, and the regression benchmarks."""

import json
import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from bookforge import assemble, bench, changes, cli, report, scenefiles, stale
from bookforge.bible import store
from bookforge.layers.runner import StepContext
from bookforge.project import Project
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import JUDGE, judge
from test_prose_qc import SID, book, go, qc_rules  # noqa: F401  (book is a fixture)

ALL = [f"b1.ch0{c}.s{s}" for c in range(1, 5) for s in (1, 2)]


@pytest.fixture
def full(book):
    """The whole small book written and accepted."""
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    go(Project.open(book.root), RuleLLM(qc_rules()))
    p = Project.open(book.root)
    assert all(p.state.items[s].status == "accepted" for s in ALL)
    return p


def git(p, *args):
    return subprocess.run(["git", "-C", str(p.root), *args], capture_output=True, text=True).stdout


def write_calls(p, records):
    path = p.book_dir / "logs" / "calls.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def set_review(p, sid, **fields):
    path = scenefiles.review_path(p, sid)
    data = json.loads(path.read_text())
    data.update(fields)
    path.write_text(json.dumps(data))


# ── the morning report ──────────────────────────────────────────────────────

def test_progress_counts_scenes_words_and_model_use(full):
    write_calls(full, [
        {"ts": "2026-01-01T00:00:00.000+00:00", "kind": "llm", "ok": True, "duration_seconds": 100, "usage": {"prompt_tokens": 1000, "completion_tokens": 200}},
        {"ts": "2026-01-02T00:00:00.000+00:00", "kind": "llm", "ok": False, "duration_seconds": 20, "usage": None},
        {"ts": "2026-01-02T00:00:01.000+00:00", "kind": "web", "ok": True},
    ])
    text = report.build_report(full)
    assert "- Scenes: 8 planned: 8 accepted" in text and "Words in accepted scenes:" in text
    assert "So far: 2 model calls (1 failed), 2m 0s of model time, 1200 tokens (1000 in, 200 out), 1 web calls" in text
    since = report.build_report(full, since="2026-01-02T00:00:00.000+00:00")
    assert "This run: 1 model calls (1 failed), 0m 20s of model time, 0 tokens" in since and "did not report usage" in since


def test_needs_you_lists_flagged_scenes_waiting_checkpoints_and_change_requests(full):
    item = full.state.items["b1.ch02.s1"]
    item.status, item.note = "flagged", "the critic scored pacing 2 (minimum 3)"
    set_review(full, "b1.ch02.s1", blocking=["the critic scored pacing 2 (minimum 3)"])
    full.state.items["b1.ch03.s1"].status = "stale"
    full.state.checkpoints["final"].status = "waiting"
    full.save_state()
    scene = store.load_scenes(full)[0]
    changes.file_gaps(full, scene, store.load_scenes(full), [{"track": "jonas-knows", "planned": "knows nothing", "observed": "suspects", "evidence": "x"}])
    text = report.build_report(full)
    needs = text.split("## Needs you")[1].split("## Unsure")[0]
    assert "Scene **b1.ch02.s1** is flagged: the critic scored pacing 2" in needs
    assert "Scene **b1.ch03.s1** is stale" in needs and "`stale --fix`" in needs
    assert "The **final** checkpoint is waiting" in needs
    assert "Change request **cr-0001**" in needs and "`changes --approve cr-0001`" in needs


def test_nothing_to_report_says_so(full):
    needs = report.build_report(full).split("## Needs you")[1].split("## Unsure")[0]
    assert "- Nothing." in needs


def test_unsure_collects_continuity_doubts_critic_minimums_and_gaps(full):
    set_review(full, "b1.ch01.s1",
               continuity={"unsure": [{"question": "Anna Voss: left-handed", "answer": "no", "confidence": 0.6, "evidence": ""}]},
               critic={"scores": {"stakes": 4, "pacing": 3}},
               extraction={"gaps": [{"track": "jonas-knows", "planned": "nothing", "observed": "suspects"}]})
    unsure = report.build_report(full).split("## Unsure")[1].split("## Suggestions")[0]
    assert "b1.ch01.s1: continuity, 'Anna Voss: left-handed' (answered no, confidence 0.6)" in unsure
    assert "critic scores at the minimum (pacing 3)" in unsure
    assert "the prose shows 'suspects' where the plan says 'nothing'" in unsure


def test_suggestions_are_repeated_phrases_that_are_not_banned_yet(full):
    suggested = report.build_report(full).split("## Suggestions for banned.txt")[1].split("## Facts")[0]
    phrases = [line.split("`")[1] for line in suggested.splitlines() if line.startswith("- `")]
    assert phrases and len(phrases) <= report.SUGGEST_MAX
    assert not any(t in ("anna", "jonas") for p in phrases for t in p.split())
    banned = full.root / "style" / "banned.txt"
    banned.write_text(banned.read_text() + f"\n{phrases[0]}\n")
    again = report.build_report(full).split("## Suggestions for banned.txt")[1].split("## Facts")[0]
    assert phrases[0] not in again


def test_too_few_scenes_give_no_suggestions():
    assert report.suggest_banned(["one two three four five"] * 2, [], set()) == []


def test_sensitive_research_facts_are_listed_with_the_scenes_that_cite_them(full):
    store_ = next(iter(__import__("bookforge.research.notes", fromlist=["x"]).stores_for(full).values()))
    f = store_.add_fact(claim="Gas lamps were lit by hand.", url="https://example.org/lamps", title="Lamps", fetched="2026-01-01",
                        quote="lit by hand", layer="chapters", question="q", sensitive=True)
    store_.add_fact(claim="A harmless fact.", url="https://example.org/h", title="H", fetched="2026-01-01", quote="harmless",
                    layer="chapters", question="q2", sensitive=False)
    scenes = store.load_scenes(full)
    scenes[2].research = [f.id]
    store.save_scenes(full, scenes)
    facts = report.build_report(full).split("## Facts to verify")[1].split("## Revision samples")[0]
    assert f"[{f.id}] Gas lamps were lit by hand. (https://example.org/lamps; used in {scenes[2].id})" in facts
    assert "harmless" not in facts.lower()


def test_samples_show_before_and_after_pairs_and_are_stable_for_a_day(full):
    rewrite = lambda i: {"paragraph": 0, "mode": "rewrite", "flags": ["banned_phrase"], "before": f"old {i}", "after": f"new {i}"}
    for i, sid in enumerate(ALL[:5]):
        set_review(full, sid, rounds=[{"revisions": [rewrite(i)]}])
    set_review(full, ALL[5], rounds=[{"revisions": [{"paragraph": 0, "mode": "delete", "before": "gone"}]}])
    text = report.build_report(full, today="2026-02-02")
    samples = text.split("## Revision samples")[1]
    assert samples.count("> Before:") == 3 and "gone" not in samples
    assert report.build_report(full, today="2026-02-02") == text


def test_no_revisions_means_no_samples(full):
    assert "No passage was revised." in report.build_report(full)


def test_write_report_names_it_by_date_and_does_not_overwrite_the_same_day(full):
    first = report.write_report(full)
    second = report.write_report(full)
    assert first != second and first.startswith("books/b1/reports/20") and (full.root / first).exists() and (full.root / second).exists()


def test_the_report_command_prints_and_can_save(full):
    out = CliRunner().invoke(cli.app, ["report", str(full.root), "--write"])
    assert out.exit_code == 0 and "# Morning report: b1" in out.output and "saved books/b1/reports/" in out.output
    assert "morning report" in git(full, "log", "--format=%s", "-3")


def test_run_writes_a_report_at_the_end(book, monkeypatch):
    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM(qc_rules()))
    monkeypatch.setattr(cli, "build_web_client", lambda p: None)
    out = CliRunner().invoke(cli.app, ["run", str(book.root)])
    assert out.exit_code == 0 and "morning report: books/b1/reports/" in out.output
    assert list((book.book_dir / "reports").glob("20*.md"))


# ── assembly ────────────────────────────────────────────────────────────────

def test_an_unfinished_book_is_not_assembled_but_can_be_read_in_part(book):
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    with pytest.raises(assemble.AssembleError) as e:
        assemble.assemble(p)
    assert "b1.ch02.s1 is pending" in str(e.value) and "--partial" in str(e.value)
    result = assemble.assemble(p, partial=True)
    assert result.path.endswith("manuscript-partial.md") and result.scenes == 2 and "b1.ch02.s1" in result.missing
    assert not assemble.manuscript_path(p).exists() and p.state.checkpoints["final"].status == "pending"


def test_the_manuscript_has_acts_chapters_and_scene_breaks(full):
    result = assemble.assemble(full)
    text = (full.root / result.path).read_text()
    assert result.scenes == 8 and result.words > 1000
    assert text.index("# Act 1") < text.index("## Chapter 1") < text.index("## Chapter 3") and text.count("# Act ") == 2
    assert text.count("\n\n* * *\n\n") == 4  # one break inside each of the four chapters
    assert scenefiles.final_path(full, "b1.ch02.s2").read_text().strip() in text
    assert "Scene" not in text.split("## Chapter 1")[0]  # nothing but the headings before the first scene


def test_assembly_reaches_the_final_checkpoint_and_tags_each_changed_draft(full):
    first = assemble.assemble(full)
    assert first.tag == "b1-draft-1" and Project.open(full.root).state.checkpoints["final"].status == "waiting"
    assert "b1-draft-1" in git(full, "tag", "--list") and "manuscript assembled" in git(full, "log", "--format=%s", "-3")
    assert assemble.assemble(Project.open(full.root)).tag is None  # same text: no new tag
    path = scenefiles.final_path(full, "b1.ch04.s2")
    path.write_text(path.read_text().rstrip() + " One more line.\n")
    assert assemble.assemble(Project.open(full.root)).tag == "b1-draft-2"


def test_a_stale_scene_blocks_assembly(full):
    constants = store.load_constants(full)
    constants.entities[0].facts = ["a different fact"]
    store.save_constants(full, constants)
    with pytest.raises(assemble.AssembleError) as e:
        assemble.assemble(full)
    assert "is stale" in str(e.value)


def test_run_assembles_when_every_layer_is_accepted(book, monkeypatch):
    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM(qc_rules()))
    monkeypatch.setattr(cli, "build_web_client", lambda p: None)
    runner = CliRunner()
    runner.invoke(cli.app, ["run", str(book.root)])
    runner.invoke(cli.app, ["approve", str(book.root), "voice"])
    out = runner.invoke(cli.app, ["run", str(book.root)])
    assert out.exit_code == 0 and "assembled books/b1/manuscript.md: " in out.output and "tagged b1-draft-1" in out.output and "approve final" in out.output
    assert runner.invoke(cli.app, ["approve", str(book.root), "final"]).exit_code == 0


def test_the_assemble_command(book):
    go(book, RuleLLM(qc_rules()))
    runner = CliRunner()
    bad = runner.invoke(cli.app, ["assemble", str(book.root)])
    assert bad.exit_code == 1 and "not finished" in bad.output
    ok = runner.invoke(cli.app, ["assemble", str(book.root), "--partial"])
    assert ok.exit_code == 0 and "2 scenes" in ok.output and "left out (not accepted yet): b1.ch02.s1" in ok.output


# ── benchmarks ──────────────────────────────────────────────────────────────

SMALL = {"id": "tiny", "purpose": "A test.", "pov": "Mara", "setting": "a room", "characters": [{"name": "Mara", "facts": ["quiet"]}],
         "beats": ["One thing.", "Another thing."], "words": [100, 900]}


def writer(text_for):
    """A writer rule: the n-th draft request gets text_for(n)."""
    n = {"i": 0}

    def reply(messages):
        n["i"] += 1
        return text_for(n["i"])

    return reply


def bench_llm(text_for, prefer="Zebra"):
    return RuleLLM([("Write the scene described below", writer(text_for)), (JUDGE, judge(prefer))])


def run_cli(book, monkeypatch, llm, *args):
    monkeypatch.setattr(cli, "build_client", lambda p: llm)
    return CliRunner().invoke(cli.app, ["bench", str(book.root), "--only", "quarrel", *args])


def test_the_shipped_benchmarks_load_and_a_series_can_add_or_replace_one(book):
    ids = [b.id for b in bench.load_benchmarks(book)]
    assert ids == ["discovery", "farewell", "pursuit", "quarrel", "reunion"]
    d = book.root / "workbench" / "benchmarks"
    d.mkdir(parents=True)
    (d / "tiny.yaml").write_text(yaml.safe_dump(SMALL))
    (d / "quarrel.yaml").write_text(yaml.safe_dump({**SMALL, "id": "quarrel", "purpose": "Replaced."}))
    loaded = {b.id: b for b in bench.load_benchmarks(book)}
    assert "tiny" in loaded and loaded["quarrel"].purpose == "Replaced."
    with pytest.raises(bench.BenchError):
        bench.load_benchmarks(book, ["nope"])


def test_a_bad_benchmark_file_is_named(book):
    d = book.root / "workbench" / "benchmarks"
    d.mkdir(parents=True)
    (d / "bad.yaml").write_text("id: bad\n")
    with pytest.raises(bench.BenchError) as e:
        bench.load_benchmarks(book)
    assert "bad.yaml" in str(e.value)


def test_the_first_run_has_no_baseline_and_can_be_accepted(book, monkeypatch):
    llm = bench_llm(lambda n: prose(0, 22))
    out = run_cli(book, monkeypatch, llm)
    assert out.exit_code == 0 and "no accepted baseline yet; run with --accept" in out.output and "quarrel:" in out.output
    assert bench.accepted_run(Project.open(book.root)) is None
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "Eli admits he sold their father's boat." in prompt and "Anna" not in prompt  # self-contained: nothing from the bible
    out = run_cli(book, monkeypatch, llm, "--accept")
    assert "accepted bench-" in out.output and bench.accepted_run(Project.open(book.root)) is not None
    assert "bench: bench-" in git(book, "log", "--format=%s", "-3")


def test_a_change_that_wins_ships(book, monkeypatch):
    run_cli(book, monkeypatch, bench_llm(lambda n: prose(0, 22)), "--accept")
    out = run_cli(book, monkeypatch, bench_llm(lambda n: prose(3, 22) + " Zebra."), "--accept")
    assert out.exit_code == 0 and "quarrel: win" in out.output and "1 won, 0 lost, 0 tied: it does not lose." in out.output
    run = bench.accepted_run(Project.open(book.root))
    assert "Zebra" in run.texts["quarrel"]


def test_a_change_that_loses_is_refused_unless_forced(book, monkeypatch):
    run_cli(book, monkeypatch, bench_llm(lambda n: prose(0, 22) + " Zebra."), "--accept")
    base = bench.accepted_run(Project.open(book.root)).name
    out = run_cli(book, monkeypatch, bench_llm(lambda n: prose(3, 22)), "--accept")
    assert out.exit_code == 1 and "quarrel: loss" in out.output and "do not ship" in out.output and "not accepted: it loses" in out.output
    assert bench.accepted_run(Project.open(book.root)).name == base
    out = run_cli(book, monkeypatch, bench_llm(lambda n: prose(3, 22)), "--accept", "--force")
    assert out.exit_code == 1 and bench.accepted_run(Project.open(book.root)).name != base


def test_a_new_blocking_problem_is_a_regression_even_if_the_judge_likes_it(book, monkeypatch):
    run_cli(book, monkeypatch, bench_llm(lambda n: prose(0, 22)), "--accept")
    banned = book.root / "style" / "banned.txt"
    banned.write_text(banned.read_text() + "\nZebra\n")
    out = run_cli(book, monkeypatch, bench_llm(lambda n: prose(3, 22) + " Zebra."))
    assert out.exit_code == 1 and "REGRESSION quarrel: 1 blocking problem(s), was 0" in out.output and "changed since the baseline: banned" in out.output


def test_no_judge_compares_only_the_mechanical_results(book, monkeypatch):
    run_cli(book, monkeypatch, bench_llm(lambda n: prose(0, 22)), "--accept")
    llm = bench_llm(lambda n: prose(3, 22))
    out = run_cli(book, monkeypatch, llm, "--no-judge")
    assert out.exit_code == 0 and "quarrel: not judged" in out.output and not llm.calls_matching("Two drafts of the same scene")


def test_a_judge_that_fails_is_unknown_not_a_loss(book, monkeypatch):
    run_cli(book, monkeypatch, bench_llm(lambda n: prose(0, 22)), "--accept")
    llm = RuleLLM([("Write the scene described below", prose(3, 22)), (JUDGE, "not json")])
    out = run_cli(book, monkeypatch, llm)
    assert "quarrel: unknown" in out.output and out.exit_code == 0
