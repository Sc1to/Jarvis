import pytest

from bookforge import prompts
from bookforge.errors import PromptError
from bookforge.layers.direction import NORTH_STAR_SECTIONS

NAMES = ["system", "series_north_star", "book_north_star", "synopsis", "correct",
         "research_system", "research_questions", "research_facts", "research_check"]


@pytest.mark.parametrize("name", NAMES)
def test_every_template_exists_and_has_only_known_slots(name):
    template = (prompts.PROMPT_DIR / f"{name}.md").read_text()
    known = {"language", "pov", "tense", "target_words", "book_id", "premise", "series_north_star",
             "book_north_star", "ledger", "problems", "research_notes", "layer_focus", "document",
             "max_questions", "question", "url", "page_text", "setting", "story", "facts"}
    assert prompts.slots_in(template) <= known


@pytest.mark.parametrize("name", ["series_north_star", "book_north_star"])
def test_north_star_templates_name_every_required_section(name):
    template = (prompts.PROMPT_DIR / f"{name}.md").read_text()
    for section in NORTH_STAR_SECTIONS:
        assert f"## {section}" in template


def test_render_fills_every_slot():
    out = prompts.render("correct", problems="- too short")
    assert "- too short" in out and "{problems}" not in out


def test_missing_slot_is_an_error():
    with pytest.raises(PromptError, match="problems"):
        prompts.render("correct")


def test_braces_inside_values_are_left_alone():
    # A premise that happens to contain "{pov}" must not be filled in a second time.
    out = prompts.render("correct", problems="the text says {pov} literally", pov="FIRST")
    assert "{pov} literally" in out and "FIRST" not in out


def test_extra_values_are_ignored():
    assert "x" in prompts.render("correct", problems="x", unused="y")


def test_unknown_or_unsafe_names_are_rejected():
    for bad in ("../etc/passwd", "Synopsis", "a/b", ""):
        with pytest.raises(PromptError, match="invalid prompt name"):
            prompts.render(bad)
    with pytest.raises(PromptError, match="cannot read"):
        prompts.render("does_not_exist")


def test_series_override_wins(tmp_path):
    (tmp_path / "workbench" / "prompts").mkdir(parents=True)
    (tmp_path / "workbench" / "prompts" / "correct.md").write_text("Custom: {problems}")
    assert prompts.render("correct", tmp_path, problems="p").startswith("Custom: p")
    assert "Custom" not in prompts.render("correct", None, problems="p")
