from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from bookforge import cli
from bookforge.layers import HANDLERS
from bookforge.layers.direction import (
    NORTH_STAR_MAX_WORDS, NORTH_STAR_SECTIONS, SYNOPSIS_MAX_WORDS, SYNOPSIS_MIN_WORDS,
    validate_north_star, validate_synopsis,
)
from bookforge.layers.document import clean_reply
from bookforge.layers.runner import run
from bookforge.llm import FakeLLMClient, LLMError
from bookforge.project import Project
from bookforge.state import load_state


def north_star(title="# The Ledger", drop=(), empty=(), words=30, marker=""):
    parts = [title, ""]
    for section in NORTH_STAR_SECTIONS:
        if section in drop:
            continue
        parts.append(f"## {section}")
        parts.append("" if section in empty else " ".join([f"{section.split()[0].lower()}{marker}"] * words))
        parts.append("")
    return "\n".join(parts)


def synopsis(words=500):
    return "# The Ledger\n\n" + " ".join(["story"] * words)


def good_script(ns1="SERIES-STAR", ns2="BOOK-STAR"):
    return {"critic": [north_star(marker=ns1), north_star(marker=ns2), synopsis()]}


def go(project, llm, until=None):
    return run(project, llm, HANDLERS, until=until)


def commits(project):
    out = subprocess.run(["git", "-C", str(project.root), "log", "--format=%s"], capture_output=True, text=True).stdout
    return [m for m in out.split("\n") if m]


# ── validators ──────────────────────────────────────────────────────────────

def test_valid_north_star_passes():
    assert validate_north_star(north_star()) == []


def test_missing_and_empty_sections_are_named():
    problems = validate_north_star(north_star(drop=("Tone",), empty=("Themes",)))
    assert any("'## Tone'" in p for p in problems)
    assert any("'themes' is empty" in p for p in problems)


def test_heading_case_does_not_matter():
    text = north_star().replace("## Emotional promise", "## EMOTIONAL PROMISE").replace("## What it is not", "## What It Is Not")
    assert validate_north_star(text) == []


def test_north_star_length_limits():
    assert any("too long" in p for p in validate_north_star(north_star(words=NORTH_STAR_MAX_WORDS)))
    assert any("too short" in p for p in validate_north_star(north_star(words=3)))


def test_synopsis_length_limits():
    assert validate_synopsis(synopsis()) == []
    assert any("too short" in p for p in validate_synopsis(synopsis(SYNOPSIS_MIN_WORDS - 50)))
    assert any("too long" in p for p in validate_synopsis(synopsis(SYNOPSIS_MAX_WORDS + 50)))


# ── reply cleaning ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("# T\n\n## A\nbody", "# T\n\n## A\nbody"),
    ("```markdown\n# T\n## A\nbody\n```", "# T\n## A\nbody"),
    ("Sure, here you go:\n\n```md\n# T\n## A\nbody\n```\nHope that helps!", "# T\n## A\nbody"),
    ("Here is the document:\n\n# T\n## A\nbody", "# T\n## A\nbody"),
    ("  \n# T\n## A\nbody\n\n", "# T\n## A\nbody"),
])
def test_clean_reply_with_preamble_stripping(raw, expected):
    assert clean_reply(raw, strip_preamble=True) == expected


def test_clean_reply_without_preamble_stripping_keeps_prose():
    assert clean_reply("The story begins.\nIt ends.", strip_preamble=False) == "The story begins.\nIt ends."
    assert clean_reply("```\nThe story.\n```", strip_preamble=False) == "The story."


def test_a_long_fenced_block_inside_a_big_reply_is_not_mistaken_for_chatter():
    raw = "x" * 500 + "\n```\ncode\n```"
    assert clean_reply(raw, strip_preamble=False) == raw


# ── the three handlers ──────────────────────────────────────────────────────

def test_direction_layers_run_in_order_and_stop_at_the_checkpoint(project):
    llm = FakeLLMClient(good_script())
    summary = go(project, llm)
    assert summary.ran == ["series_north_star", "book_north_star", "synopsis"]
    assert summary.stopped == "checkpoint" and "direction" in summary.detail
    for rel in ("north-star.md", "books/b1/north-star.md", "books/b1/synopsis.md"):
        assert (project.root / rel).read_text().endswith("\n")
    assert project.state.checkpoints["direction"].status == "waiting"
    assert commits(project)[:3] == ["b1.synopsis: accepted", "b1.book_north_star: accepted", "b1.series_north_star: accepted"]


def test_context_chain_uses_the_actual_generated_text(project):
    llm = FakeLLMClient({"critic": [north_star(marker="aaa"), north_star(marker="bbb"), synopsis()]})
    go(project, llm)
    series_in_book_prompt = llm.calls[1]["messages"][1]["content"]
    syn_prompt = llm.calls[2]["messages"][1]["content"]
    assert "premiseaaa" in series_in_book_prompt and "premisebbb" not in series_in_book_prompt
    assert "premiseaaa" in syn_prompt and "premisebbb" in syn_prompt


def test_calls_use_the_configured_roles_and_options(project):
    llm = FakeLLMClient(good_script())
    go(project, llm)
    assert [c["role"] for c in llm.calls] == ["critic", "critic", "critic"]
    assert all(c["options"] == {"max_tokens": mt} for c, mt in zip(llm.calls, (1500, 1500, 4000)))
    system = llm.calls[0]["messages"][0]
    assert system["role"] == "system" and "English" in system["content"]


def test_per_layer_model_and_temperature_come_from_config(project):
    (project.root / "config.yaml").write_text(
        "layers:\n  synopsis:\n    model: writer\n  series_north_star:\n    temperature: 0.9\n", encoding="utf-8")
    reopened = Project.open(project.root)
    llm = FakeLLMClient({"critic": [north_star(), north_star()], "writer": [synopsis()]})
    go(reopened, llm)
    assert [c["role"] for c in llm.calls] == ["critic", "critic", "writer"]
    assert llm.calls[0]["options"]["temperature"] == 0.9
    assert "temperature" not in llm.calls[1]["options"]


def test_book_settings_reach_the_prompts(project):
    (project.root / "config.yaml").write_text("book:\n  language: German\n  pov: first\n  target_words: 60000\n", encoding="utf-8")
    llm = FakeLLMClient(good_script())
    go(Project.open(project.root), llm, until="series_north_star")
    assert "German" in llm.calls[0]["messages"][0]["content"]
    user = llm.calls[0]["messages"][1]["content"]
    assert "60000" in user and "Point of view: first" in user


def test_ledger_is_empty_for_a_first_book_and_included_later(project):
    llm = FakeLLMClient(good_script())
    go(project, llm, until="book_north_star")
    assert "none (this is the first book)" in llm.calls[1]["messages"][1]["content"]

    other = Project.create(project.root.parent / "second", "Another premise.")
    (other.root / "ledger.yaml").write_text("open_threads:\n  - who sent the ledger?\nend_of_book_states: {}\n")
    llm2 = FakeLLMClient(good_script())
    go(other, llm2, until="book_north_star")
    assert "who sent the ledger?" in llm2.calls[1]["messages"][1]["content"]


def test_series_prompt_override_is_used(project):
    override = project.root / "workbench" / "prompts"
    override.mkdir(parents=True)
    (override / "series_north_star.md").write_text("MY OWN TASK: {premise}")
    llm = FakeLLMClient(good_script())
    go(project, llm, until="series_north_star")
    assert llm.calls[0]["messages"][1]["content"].startswith("MY OWN TASK: A clerk finds a ledger")


# ── correction loop ─────────────────────────────────────────────────────────

def test_a_structural_problem_is_corrected_once(project):
    llm = FakeLLMClient({"critic": [north_star(drop=("Tone",)), north_star()]})
    summary = go(project, llm, until="series_north_star")
    assert summary.ran == ["series_north_star"]
    assert len(llm.calls) == 2
    roles = [m["role"] for m in llm.calls[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert "missing the section '## Tone'" in llm.calls[1]["messages"][3]["content"]
    assert "## Tone" in (project.root / "north-star.md").read_text()


def test_unresolved_problems_flag_the_layer_after_the_configured_rounds(project):
    llm = FakeLLMClient({"critic": [north_star(drop=("Tone",))] * 5})
    summary = go(project, llm, until="series_north_star")
    assert summary.stopped == "failed" and "2 correction round" in summary.detail
    assert len(llm.calls) == 3  # first draft + 2 corrections
    assert load_state(project.state_path).layers["series_north_star"].status == "flagged"
    assert not (project.root / "north-star.md").exists()
    assert "b1.series_north_star: accepted" not in commits(project)


def test_zero_rounds_means_no_correction(project):
    (project.root / "config.yaml").write_text("qc:\n  max_revision_rounds: 0\n")
    llm = FakeLLMClient({"critic": [north_star(drop=("Tone",))] * 3})
    assert go(Project.open(project.root), llm, until="series_north_star").stopped == "failed"
    assert len(llm.calls) == 1


def test_chatter_around_the_document_is_removed_before_saving(project):
    reply = "Here is the north star:\n\n```markdown\n" + north_star() + "\n```\n"
    go(project, FakeLLMClient({"critic": [reply]}), until="series_north_star")
    saved = (project.root / "north-star.md").read_text()
    assert saved.startswith("# The Ledger") and "```" not in saved and "Here is" not in saved


# ── resume and failure ──────────────────────────────────────────────────────

def test_an_existing_valid_file_is_adopted_without_calling_the_model(project):
    (project.root / "north-star.md").write_text(north_star(marker="mine"))
    llm = FakeLLMClient({})
    summary = go(project, llm, until="series_north_star")
    assert summary.ran == ["series_north_star"] and llm.calls == []
    assert project.state.layers["series_north_star"].note == "adopted existing file"
    tracked = subprocess.run(["git", "-C", str(project.root), "ls-files"], capture_output=True, text=True).stdout.split()
    assert "north-star.md" in tracked


def test_an_existing_invalid_file_is_never_overwritten(project):
    (project.root / "north-star.md").write_text("# My half-written idea\n")
    llm = FakeLLMClient(good_script())
    summary = go(project, llm, until="series_north_star")
    assert summary.stopped == "failed" and "delete it" in summary.detail
    assert llm.calls == []
    assert (project.root / "north-star.md").read_text() == "# My half-written idea\n"


def test_model_errors_flag_the_layer_and_a_rerun_recovers(project):
    def offline(_messages):
        raise LLMError("colibri is not reachable")

    summary = go(project, FakeLLMClient({"critic": [offline]}), until="series_north_star")
    assert summary.stopped == "failed" and "not reachable" in summary.detail
    state = load_state(project.state_path)
    assert state.layers["series_north_star"].status == "flagged"

    again = go(Project.open(project.root), FakeLLMClient(good_script()), until="series_north_star")
    assert again.ran == ["series_north_star"]


def test_missing_model_client_is_a_clear_failure(project):
    summary = go(project, None, until="series_north_star")
    assert summary.stopped == "failed" and "no model client" in summary.detail


# ── end to end through the CLI ──────────────────────────────────────────────

@pytest.fixture
def cli_runner(monkeypatch):
    llm = FakeLLMClient(good_script())
    monkeypatch.setattr(cli, "build_client", lambda project: llm)
    monkeypatch.setattr(cli, "build_web_client", lambda project: None)  # no research in these tests
    return CliRunner(), llm


def git(project, *args):
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


def test_run_review_edit_approve_continue(project, cli_runner, monkeypatch):
    runner, llm = cli_runner
    monkeypatch.setattr(cli, "HANDLERS", {n: HANDLERS[n] for n in ("series_north_star", "book_north_star", "synopsis")})
    result = runner.invoke(cli.app, ["run", str(project.root)])
    assert result.exit_code == 0, result.output
    assert "accepted: synopsis" in result.output and "approve direction" in result.output
    for rel in ("north-star.md", "books/b1/north-star.md", "books/b1/synopsis.md"):
        assert rel in result.output

    # The author edits the synopsis while reviewing.
    synopsis_path = project.root / "books/b1/synopsis.md"
    synopsis_path.write_text(synopsis_path.read_text() + "\nAUTHOR EDIT: the ledger is cursed.\n")

    result = runner.invoke(cli.app, ["approve", str(project.root), "direction"])
    assert result.exit_code == 0, result.output
    assert "AUTHOR EDIT" in git(project, "show", "b1-direction-approved:books/b1/synopsis.md")
    assert git(project, "status", "--porcelain").strip() == ""

    nxt = runner.invoke(cli.app, ["run", str(project.root)])
    assert nxt.exit_code == 2 and "layer 'acts' has no implementation yet" in nxt.output
    assert len(llm.calls) == 3  # nothing was regenerated


def test_approving_without_step_commits_still_snapshots_and_tags(project, cli_runner):
    runner, _ = cli_runner
    (project.root / "config.yaml").write_text("git:\n  commit_each_step: false\n")
    runner.invoke(cli.app, ["run", str(project.root)])
    assert commits(project) == ["series: initialized with book b1"]  # no per-step commits

    assert runner.invoke(cli.app, ["approve", str(project.root), "direction"]).exit_code == 0
    assert commits(project)[0] == "b1: direction approved"
    assert git(project, "rev-parse", "b1-direction-approved^{commit}") == git(project, "rev-parse", "HEAD")
    tracked = git(project, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert {"north-star.md", "books/b1/north-star.md", "books/b1/synopsis.md"} <= set(tracked)
    assert git(project, "status", "--porcelain").strip() == ""


# ── research inside the layers ──────────────────────────────────────────────

class LayerLLM:
    """Documents for the three layers plus research answers, chosen by what is asked."""

    def __new__(cls):
        from conftest import RuleLLM
        return RuleLLM([
            ("Write the SERIES NORTH STAR", north_star(marker="aaa")),
            ("Write the NORTH STAR FOR BOOK", north_star(marker="bbb")),
            ("Write the SYNOPSIS", synopsis()),
            ("Decide what the author needs", question_for_layer),
            ("Source page: https://a.example/p", RESEARCH_FACTS),
            ("Source page: https://a.example/q", RESEARCH_FACTS_2),
            ("Which of these facts directly answer", '{"keep": [1, 2, 3]}'),
        ])


PAGE = "Cities in the 1890s kept death records in handwritten ledgers by the parish clerk."
PAGE_2 = "A parish clerk in the 1890s was paid by the entry and worked from a desk in the vestry."
RESEARCH_QUESTIONS_2 = ('{"questions": [{"question": "What did a parish clerk do all day?", "query": "parish clerk duties", '
                        '"sensitive": false}]}')
RESEARCH_FACTS_2 = ('{"facts": [{"claim": "Clerks were paid per entry.", '
                    '"quote": "was paid by the entry and worked from a desk in the vestry"}]}')


def question_for_layer(messages):
    """The series layer asks one question, the book north star another, the synopsis none."""
    text = messages[-1]["content"]
    if "Broad background" in text:
        return RESEARCH_QUESTIONS
    if "specific to this book" in text:
        return RESEARCH_QUESTIONS_2
    return '{"questions": []}'


RESEARCH_QUESTIONS = ('{"questions": [{"question": "Who kept death records in the 1890s?", "query": "death records 1890s", '
                      '"sensitive": true}]}')
RESEARCH_FACTS = ('{"facts": [{"claim": "Parish clerks kept death records by hand.", '
                  '"quote": "kept death records in handwritten ledgers by the parish clerk"}]}')


def research_web():
    from urllib.parse import quote
    from bookforge.research.search import FakeWebClient
    def result(url):
        return [{"text": "p", "href": "https://duckduckgo.com/l/?uddg=" + quote(url, safe="")}]

    return FakeWebClient(
        searches={"death records 1890s": "results", "parish clerk duties": "results"},
        links={"death records 1890s": result("https://a.example/p"), "parish clerk duties": result("https://a.example/q")},
        pages={"https://a.example/p": PAGE, "https://a.example/q": PAGE_2},
    )


def test_each_layer_researches_and_the_notes_reach_the_next_layers_prompt(project):
    llm, web = LayerLLM(), research_web()
    summary = run(project, llm, HANDLERS, web=web)
    assert summary.ran == ["series_north_star", "book_north_star", "synopsis"]
    assert "research: 1/1 questions answered, 1 facts" in summary.notes["series_north_star"]
    book_prompt = llm.calls_matching("Write the NORTH STAR FOR BOOK")[0]["messages"][-1]["content"]
    assert "[s-0001] Parish clerks kept death records by hand." in book_prompt
    series_prompt = llm.calls_matching("Write the SERIES NORTH STAR")[0]["messages"][-1]["content"]
    assert "[s-" not in series_prompt  # nothing was known when the first layer was written


def test_research_files_are_committed_with_their_layer(project):
    run(project, LayerLLM(), HANDLERS, web=research_web(), until="series_north_star")
    tracked = subprocess.run(["git", "-C", str(project.root), "ls-tree", "-r", "--name-only", "HEAD"],
                             capture_output=True, text=True).stdout.split()
    assert {"research/sources.jsonl", "research/questions.jsonl", "research/series_north_star.md", "north-star.md"} <= set(tracked)
    assert subprocess.run(["git", "-C", str(project.root), "status", "--porcelain"], capture_output=True, text=True).stdout.strip() == ""


def test_book_layers_keep_their_notes_in_the_book(project):
    run(project, LayerLLM(), HANDLERS, web=research_web())
    book_facts = (project.root / "books/b1/research/sources.jsonl").read_text()
    assert '"id": "b1-0001"' in book_facts and "Clerks were paid per entry." in book_facts
    assert "Parish clerks kept death records" not in book_facts  # that one belongs to the series
    assert (project.root / "books/b1/research/book_north_star.md").exists()
    assert "Parish clerks kept death records" in (project.root / "research/sources.jsonl").read_text()


def test_research_can_be_switched_off(project):
    (project.root / "config.yaml").write_text("research:\n  enabled: false\n")
    web = research_web()
    run(Project.open(project.root), LayerLLM(), HANDLERS, web=web, until="series_north_star")
    assert web.calls == [] and not (project.root / "research/sources.jsonl").exists()


def test_a_blocked_search_does_not_stop_the_pipeline(project):
    from bookforge.research.search import FakeWebClient
    summary = run(project, LayerLLM(), HANDLERS, web=FakeWebClient(searches={"death records 1890s": "blocked"}))
    assert summary.ran == ["series_north_star", "book_north_star", "synopsis"]
    assert "0/1 questions answered" in summary.notes["series_north_star"] and "blocked or empty" in summary.notes["series_north_star"]


def test_required_research_fails_the_layer_but_keeps_the_document(project):
    from bookforge.research.search import FakeWebClient
    (project.root / "config.yaml").write_text("research:\n  required: true\n")
    p = Project.open(project.root)
    summary = run(p, LayerLLM(), HANDLERS, web=FakeWebClient(), until="series_north_star")
    assert summary.stopped == "failed" and "research is required" in summary.detail
    assert (project.root / "north-star.md").exists()  # the document is not thrown away

    again = run(Project.open(project.root), LayerLLM(), HANDLERS, web=research_web(), until="series_north_star")
    assert again.ran == ["series_north_star"] and again.notes["series_north_star"].startswith("adopted existing file")


def test_an_adopted_document_is_researched_too(project):
    (project.root / "north-star.md").write_text(north_star(marker="mine"))
    llm = LayerLLM()
    summary = run(project, llm, HANDLERS, web=research_web(), until="series_north_star")
    assert "adopted existing file" in summary.notes["series_north_star"] and "1/1 questions answered" in summary.notes["series_north_star"]
    assert llm.calls_matching("Write the SERIES NORTH STAR") == []


def test_cli_run_reports_research(project, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "build_client", lambda p: LayerLLM())
    monkeypatch.setattr(cli, "build_web_client", lambda p: research_web())
    result = runner.invoke(cli.app, ["run", str(project.root), "--until", "series_north_star"])
    assert result.exit_code == 0, result.output
    assert "accepted: series_north_star (" in result.output and "research: 1/1 questions answered, 1 facts" in result.output


def test_a_question_answered_in_the_series_is_not_asked_again_for_the_book(project):
    llm = LayerLLM()  # this one proposes the same question whatever the layer
    llm.rules[3] = ("Decide what the author needs", RESEARCH_QUESTIONS)
    web = research_web()
    summary = run(project, llm, HANDLERS, web=web, until="book_north_star")
    assert "1/1 questions answered" in summary.notes["series_north_star"]
    assert "no new questions" in summary.notes["book_north_star"]
    assert [c for c in web.calls if c[0] == "search"] == [("search", "death records 1890s")]


def test_unanswered_questions_are_retried_and_listed_once(project):
    from bookforge.research.search import FakeWebClient
    run(project, LayerLLM(), HANDLERS, web=FakeWebClient(), until="series_north_star")  # search fails
    notes = (project.root / "research/series_north_star.md").read_text()
    assert notes.count("## Who kept death records") == 1 and "No answer found" in notes

    (project.root / "north-star.md").unlink()  # regenerate the layer; the question is tried again
    p = Project.open(project.root)
    p.state.set_layer_status("series_north_star", "pending")
    run(p, LayerLLM(), HANDLERS, web=research_web(), until="series_north_star")
    notes = (project.root / "research/series_north_star.md").read_text()
    assert notes.count("## Who kept death records") == 1 and "[s-0001]" in notes and "No answer found" not in notes


# ── the realism setting ─────────────────────────────────────────────────────

def _realism_project(project, series, book):
    from bookforge.realism import realism_setting
    (project.root / "north-star.md").write_text(series, encoding="utf-8")
    (project.resolve(f"books/{project.book}/north-star.md")).parent.mkdir(parents=True, exist_ok=True)
    project.resolve(f"books/{project.book}/north-star.md").write_text(book, encoding="utf-8")
    return realism_setting(project)


def test_a_north_star_needs_a_realism_section():
    assert "Realism" in NORTH_STAR_SECTIONS
    assert any("Realism" in p for p in validate_north_star(north_star(drop=("Realism",))))
    assert validate_north_star(north_star()) == []


def test_the_prompts_ask_for_the_realism_section():
    from bookforge.prompts import render
    series = render("series_north_star", Path("."), premise="p", target_words="1", pov="p", tense="t")
    book = render("book_north_star", Path("."), book_id="b1", premise="p", series_north_star="s", ledger="l",
                  research_notes="r", target_words="1", pov="p", tense="t")
    assert "## Realism" in series and "Hard SF" in series
    assert "## Realism" in book and "As the series." in book


def test_the_books_realism_wins_over_the_series(project):
    got = _realism_project(project, "# S\n\n## Realism\nHard SF: physics must hold.\n\n## Tone\nx\n",
                           "# B\n\n## Realism\nSpace opera: plausible is enough.\n\n## Tone\nx\n")
    assert got == "Space opera: plausible is enough."


def test_as_the_series_uses_the_series_and_keeps_the_exception(project):
    series = "# S\n\n## Realism\nHard SF: physics must hold.\n\n## Tone\nx\n"
    assert _realism_project(project, series, "# B\n\n## Realism\nAs the series.\n\n## Tone\nx\n") == "Hard SF: physics must hold."
    got = _realism_project(project, series, "# B\n\n## Realism\nAs the series, except the drive.\n\n## Tone\nx\n")
    assert got == "Hard SF: physics must hold. except the drive."


def test_an_older_north_star_without_a_realism_section_gives_nothing_or_the_series(project):
    assert _realism_project(project, "# S\n\n## Tone\nx\n", "# B\n\n## Tone\nx\n") == ""
    got = _realism_project(project, "# S\n\n## Realism\nHistorical: accurate to the decade.\n", "# B\n\n## Tone\nx\n")
    assert got == "Historical: accurate to the decade."
