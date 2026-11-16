"""Hard whole-book prose findings are resolved in the scene they point to, once, and only when the check then passes."""

import json

from bookforge import healing, inbox, prose_repair, scenefiles
from bookforge.validators import prose as prose_checks
from bookforge.validators.book import prose_findings
from bookforge.validators.findings import hard
from bookforge.validators.text import sentences
from qc_fakes import REVISE, reviser
from test_prose_qc import SID, book, calls, qc_rules, review  # noqa: F401  (book is a fixture)
from test_stale import S2, ctx, written
from conftest import RuleLLM


def copied_sentences(p, n=4):
    """Append n sentences of the first scene to the second one (a scene made partly of what was already written)."""
    first = scenefiles.final_path(p, SID).read_text()
    pick = [s for s in sentences(first) if len(s.split()) >= 7][:n]
    assert len(pick) == n
    final = scenefiles.final_path(p, S2)
    final.write_text(final.read_text().rstrip() + "\n\n" + " ".join(pick) + "\n", encoding="utf-8")
    return pick


WORDS = ("copper lantern harbour fog gull ribbon candle ladder anchor barrel chimney window thistle marble saddle pepper velvet engine "
         "orchard mirror pigeon violin cellar bucket compass lemon quarry shutter button garden mantle pocket thimble kettle meadow ferry "
         "locket bridle spindle cobble drizzle tinder wicker lantern2 harvest ember hollow juniper kindle larder mallow nettle").split()


def REPLACEMENTS(p, pick):
    """A fresh, different sentence for every sentence of the second scene that was already written in the first (all of them, not only what was added)."""
    from bookforge.validators import prose as prose_checks
    texts = [(sid, scenefiles.read(scenefiles.final_path(p, sid))) for sid in (SID, S2)]
    dups = prose_checks.duplicate_sentences(texts).get(S2, (0, []))[1]
    return {d: " ".join(WORDS[(i * 5 + k) % len(WORDS)] for k in range(max(5, len(d.split()) - 2))) + " arrived late." for i, d in enumerate(dups)}  # about as long as the sentence it replaces


def hard_repeat(p):
    found, _ = prose_findings(p)
    return [f for f in found if f.code == prose_repeat_code() and f.severity == "hard"]


def prose_repeat_code():
    return prose_repair.REPEATED


def test_repeated_sentences_are_rewritten_in_their_paragraph_and_the_scene_is_summarised_again(book):
    p = written(book)
    pick = copied_sentences(p)
    found = hard_repeat(p)
    assert [f.items for f in found] == [[S2]]
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser(REPLACEMENTS(p, pick)))))
    notes = prose_repair.fix(ctx(p, llm), found)
    assert len(notes) == 1 and S2 in notes[0] and "repeated sentences" in notes[0]
    new = scenefiles.final_path(p, S2).read_text()
    assert not any(s in new for s in pick) and hard_repeat(p) == []
    assert calls(llm, "Summarise the scene below")  # a patched scene gets its summary again
    assert review(p, S2)["stale_fixes"][0]["why"] == "a whole-book prose check"


def test_a_revision_that_does_not_make_the_finding_go_away_leaves_the_saved_text_alone(book):
    p = written(book)
    copied_sentences(p)
    before = scenefiles.final_path(p, S2).read_text()
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser({}))))  # the reviser returns the paragraph unchanged
    assert prose_repair.fix(ctx(p, llm), hard_repeat(p)) == []
    assert scenefiles.final_path(p, S2).read_text() == before and len(hard_repeat(p)) == 1


def test_text_the_author_wrote_is_never_touched_by_a_prose_fix(book):
    p = written(book)
    pick = copied_sentences(p)
    r = review(p, S2)
    r["source"] = "adopted"
    scenefiles.review_path(p, S2).write_text(json.dumps(r), encoding="utf-8")
    before = scenefiles.final_path(p, S2).read_text()
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser({s: "x y z a b c d" for s in pick}))))
    assert prose_repair.fix(ctx(p, llm), hard_repeat(p)) == [] and not calls(llm, REVISE)
    assert scenefiles.final_path(p, S2).read_text() == before


def test_a_copied_chapter_opening_is_fixed_in_the_first_scene_of_the_chapter(book):
    p = written(book)
    first = scenefiles.final_path(p, SID).read_text()
    phrase = " ".join(first.split()[:6])
    finding = hard("prose", prose_repair.OPENING, "b1.ch01 opens with words copied from the end of b1.ch00", ["b1.ch00", "b1.ch01"], [phrase])
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser({phrase: "A different first line entirely, then"}))))
    notes = prose_repair.fix(ctx(p, llm), [finding])
    assert len(notes) == 1 and SID in notes[0] and "copied the end of the chapter before" in notes[0]
    assert "A different first line entirely" in scenefiles.final_path(p, SID).read_text()


def test_the_switch_turns_it_off_and_a_fix_shows_in_the_inbox_as_fixed_automatically(book):
    p = written(book)
    pick = copied_sentences(p)
    llm = RuleLLM(qc_rules(revise=(REVISE, reviser(REPLACEMENTS(p, pick)))))
    c = ctx(p, llm)
    c.project.config.qc.fix_prose_findings = False
    assert prose_repair.fix(c, hard_repeat(p)) == []
    c.project.config.qc.fix_prose_findings = True
    healing.begin(p, "prose")
    healing.commit(p, "prose", prose_repair.fix(c, hard_repeat(p)))
    item = next(i for i in inbox.collect(p) if i["kind"] == "healed")
    assert item["stage"] == "prose" and item["status"] == "healed" and not item["blocking"] and S2 in item["title"]

