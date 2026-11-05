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
    return CliRunner(), llm


def git(project, *args):
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


def test_run_review_edit_approve_continue(project, cli_runner):
    runner, llm = cli_runner
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
