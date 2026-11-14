"""The suggested style guide: genre and comparable titles, what the web says about their prose style, a guide in the model's own words."""

import json

import pytest
from conftest import RuleLLM
from structure_fakes import direction_rules, ready

from bookforge import style
from bookforge.layers import HANDLERS
from bookforge.layers.runner import StepContext, run
from bookforge.llm import FakeLLMClient
from bookforge.research.search import FakeWebClient

URL_A, URL_B = "https://reviews.example.org/orbit-review", "https://craft.example.org/sf-prose"
PAGE_A = ("Orbit Falls by Imani Cole is praised for its spare, present-feeling prose. " * 3 + "The sentences stay short in action and lengthen only when a character stops to think about what she has lost. " + "Reviewers return to its restrained dialogue. " * 5)
PAGE_B = ("Hard science fiction usually keeps description functional, naming what a viewpoint character would notice and nothing more. " * 4 + "Pacing leans on chapter endings that hold a question open. " * 4)
QUERIES = ["Orbit Falls Imani Cole prose style review", "hard science fiction prose style conventions"]


def web():
    link = lambda u: [{"href": u, "text": "result"}]  # noqa: E731
    return FakeWebClient(searches={q: "results" for q in QUERIES}, links={QUERIES[0]: link(URL_A), QUERIES[1]: link(URL_B)}, pages={URL_A: PAGE_A, URL_B: PAGE_B})


IDENTIFY = json.dumps({"genre": "hard science fiction", "subgenres": ["corporate dystopia"], "intended_style": "spare and tense, with a cold industrial setting",
                       "comparables": [{"title": "Orbit Falls", "author": "Imani Cole", "why": "spare present-feeling prose"},
                                       {"title": "Invented Title", "author": "Nobody Real", "why": "never found on any page"}], "queries": QUERIES})
NOTES_A = json.dumps({"observations": [{"observation": "Sentences stay short in action and lengthen in reflection.", "about": "Orbit Falls",
                                         "quote": "The sentences stay short in action and lengthen only when a character stops to think about what she has lost"},
                                        {"observation": "An invented claim the page never makes.", "about": "Orbit Falls", "quote": "this sentence is not on the page"}],
                      "titles_mentioned": ["Orbit Falls"]})
NOTES_B = json.dumps({"observations": [{"observation": "Description stays functional.", "about": "the genre", "quote": "keeps description functional, naming what a viewpoint character would notice and nothing more"}], "titles_mentioned": []})


def guide(touchstones=True, extra="", n=45):
    body = " ".join(["plain"] * n)
    out = "\n\n".join(f"## {s}\n{body} {s.lower()} advice for the writer in this book." for s in style.SECTIONS)
    if touchstones:
        out += "\n\n## Touchstones\nOrbit Falls: take its restraint and the way it lets action stay short.\n"
    return out + extra + "\n"


def ctx_for(project, llm, web_client=None):
    return StepContext(project=project, layer="synopsis", llm=llm, web=web_client)


def prepared(project):
    p = ready(project)
    p.config.research.model_pick = False
    return p


def test_a_guide_is_suggested_from_checked_titles_and_quoted_observations(project):
    p = prepared(project)
    llm = FakeLLMClient({"critic": [IDENTIFY, guide()], "research": [NOTES_A, NOTES_B]})
    s = style.suggest_style_guide(ctx_for(p, llm, web()), web())
    assert s.path == "style/guide.md" and s.verified == ["Orbit Falls"] and s.web
    assert "## Touchstones" in (p.root / "style/guide.md").read_text() and not style.guide_is_empty(p)
    meta = style.load_suggestion(p)
    assert [v["title"] for v in meta["verified_titles"]] == ["Orbit Falls"] and meta["verified_titles"][0]["sources"] == [URL_A]
    assert meta["unchecked_titles"] == ["Invented Title"]  # a title no page names is not a touchstone
    quotes = [o["quote"] for o in meta["observations"]]
    assert len(quotes) == 2 and not any("not on the page" in q for q in quotes)  # an observation whose quote is not on the page is dropped
    prompt = next(c for c in llm.calls if "Write the STYLE GUIDE" in c["messages"][-1]["content"])["messages"][-1]["content"]
    assert "Orbit Falls by Imani Cole" in prompt and "Invented Title" not in prompt and "short in action" in prompt


def test_a_guide_that_copies_a_source_or_names_an_unchecked_title_is_corrected(project):
    p = prepared(project)
    copied = guide(extra="\nOrbit Falls works because " + "Hard science fiction usually keeps description functional, naming what a viewpoint character would notice and nothing more.")
    unchecked = guide(extra="\nAlso in the manner of Invented Title.")
    llm = FakeLLMClient({"critic": [IDENTIFY, copied, unchecked, guide()], "research": [NOTES_A, NOTES_B]})
    style.suggest_style_guide(ctx_for(p, llm, web()), web())
    asked = [c["messages"][-1]["content"] for c in llm.calls if c["role"] == "critic"]
    assert any("copies a run of 12" in t for t in asked) and any("was not checked on the web" in t for t in asked)
    assert "Invented Title" not in (p.root / "style/guide.md").read_text()


def test_without_the_web_no_title_is_named(project):
    p = prepared(project)
    llm = FakeLLMClient({"critic": [IDENTIFY, guide(touchstones=True), guide(touchstones=False)]})
    s = style.suggest_style_guide(ctx_for(p, llm), None)
    assert not s.web and s.verified == []
    assert any("remove '## Touchstones'" in c["messages"][-1]["content"] for c in llm.calls)
    assert "Touchstones" not in (p.root / "style/guide.md").read_text()


def test_a_guide_you_have_is_never_overwritten(project):
    p = prepared(project)
    (p.root / "style/guide.md").write_text("# Style guide\n\nMy own rules: short sentences, no adverbs.\n")
    llm = FakeLLMClient({"critic": [IDENTIFY, guide()], "research": [NOTES_A, NOTES_B]})
    s = style.suggest_style_guide(ctx_for(p, llm, web()), web())
    assert s.path == "style/guide.suggested.md"
    assert "My own rules" in (p.root / "style/guide.md").read_text() and (p.root / "style/guide.suggested.md").exists()
    llm2 = FakeLLMClient({"critic": [IDENTIFY, guide()], "research": [NOTES_A, NOTES_B]})
    s2 = style.suggest_style_guide(ctx_for(p, llm2, web()), web(), replace=True)
    assert s2.path == "style/guide.md" and s2.replaced_existing and "My own rules" not in (p.root / "style/guide.md").read_text()
    import subprocess
    log = subprocess.run(["git", "-C", str(p.root), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "style guide as it was, before a suggestion replaces it" in log


def test_failed_searches_and_pages_are_told_not_fatal(project):
    p = prepared(project)
    broken = FakeWebClient(searches={QUERIES[0]: "x", QUERIES[1]: "y"}, links={QUERIES[0]: [{"href": "https://gone.example.org/p", "text": "t"}], QUERIES[1]: []}, pages={})
    llm = FakeLLMClient({"critic": [IDENTIFY, guide(touchstones=False)]})
    s = style.suggest_style_guide(ctx_for(p, llm, broken), broken)
    assert s.verified == [] and s.problems and any("gone.example.org" in x or "returned no result" in x for x in s.problems)


@pytest.mark.real_style
def test_the_synopsis_step_suggests_a_guide_automatically_once_and_never_fails_the_layer(project):
    p = prepared(project)
    p.state.set_layer_status("synopsis", "pending")
    p.save_state()
    (p.root / "books/b1/synopsis.md").unlink()
    llm = RuleLLM(direction_rules() + [("Work out the genre of this book", IDENTIFY), ("Read the web page below", NOTES_A), ("Write the STYLE GUIDE for this book", guide(touchstones=False))])
    summary = run(p, llm, HANDLERS, until="synopsis")
    assert summary.ran == ["synopsis"] and "style guide suggested" in summary.notes["synopsis"] and not style.guide_is_empty(p)
    # a guide that exists is not asked for again
    calls = len(llm.calls)
    files, note = style.maybe_suggest(ctx_for(p, llm, web()))
    assert files == [] and note == "" and len(llm.calls) == calls
    # and a failure becomes a note
    (p.root / "style/guide.md").write_text("# Style guide\n\n")
    files, note = style.maybe_suggest(ctx_for(p, FakeLLMClient({}), None))
    assert files == [] and "no style guide could be suggested" in note
    p.config.style.auto_suggest = False
    assert style.maybe_suggest(ctx_for(p, llm, None)) == ([], "")


def test_the_style_settings_documents_and_review_files(project):
    from bookforge import documents
    from bookforge.constants import CHECKPOINT_REVIEW_FILES
    assert "style/guide.md" in CHECKPOINT_REVIEW_FILES["direction"]
    assert documents.find(project, "style_suggested").group == "Voice"
    assert project.config.style.auto_suggest and project.config.style.comparables == 4
