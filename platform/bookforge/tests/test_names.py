"""Whose chapter it is, and whether every name is in the cast."""

from bookforge.bible.models import Constants, Entity
from bookforge.validators import HARD, names as N


def cast():
    return Constants(entities=[Entity(id=i, kind="character", name=n, facts=["x"]) for i, n in [("eli", "Eli Voss"), ("mara", "Mara Reil"), ("silas-thorne", "Silas Thorne")]])


def unit(i, pov, summary, **kw):
    return dict(id=f"b2.ch{i:02d}", pov=pov, summary=summary, purpose="", **kw)


def test_a_chapter_whose_text_follows_two_other_people_is_not_the_povs_chapter():
    c = unit(6, "silas-thorne", "Mara argues with Eli about the data while Eli refuses to leave and Mara pleads.")
    found = N.pov_findings([c], cast(), "chapters")
    assert [(f.code, f.severity) for f in found] == [("pov_not_in_text", HARD)] and "silas-thorne" in found[0].message
    one = unit(7, "eli", "Mara confronts him in the corridor.")
    assert [f.severity for f in N.pov_findings([one], cast(), "chapters")] == ["soft"]  # one other person: may be told from the one they act on


def test_a_pov_told_by_pronoun_or_by_name_passes():
    assert N.pov_findings([unit(1, "eli", "He crosses out a name and pays for it.")], cast(), "chapters") == []
    assert N.pov_findings([unit(2, "eli", "Eli finds the drive while Mara watches.")], cast(), "chapters") == []


def test_a_pov_that_is_present_but_not_the_main_person_is_a_soft_finding():
    c = unit(3, "eli", "Mara argues. Mara pleads. Mara finally leaves while Eli watches.")
    assert [f.code for f in N.pov_findings([c], cast(), "chapters")] == ["pov_not_main"]


def test_a_name_that_is_not_in_the_cast_is_flagged_once_per_unit_and_nothing_while_there_is_no_cast():
    c = unit(5, "eli", "Eli meets Foreman Halloway at the gate.", end_state="Halloway seals the sector.")
    found = N.unknown_names([c], cast(), "chapters")
    assert len(found) == 1 and "halloway" in found[0].message and found[0].severity == "soft"
    assert N.unknown_names([c], Constants(), "chapters") == []
