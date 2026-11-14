"""The regression suite itself: scripted mode passes on the shipped data, and fails loudly when a validator stops catching a failure."""

from bookforge import suite
from bookforge.validators import repeats


def test_the_scripted_suite_passes_and_writes_a_report(tmp_path):
    path, ok = suite.run_suite(tmp_path)
    text = open(path, encoding="utf-8").read()
    assert ok, text
    for needle in ("## Known-bad fixtures", "## Case: thin", "## Case: mystery", "Author questions", "Sizing:", "Formula:", "pays e"):
        assert needle in text


def test_the_thin_synopsis_asks_questions_and_makes_no_plan():
    res = suite.scripted_case("thin", suite.CASES["thin"])
    assert res.capacity["thin"] and res.questions and not res.chapters


def test_a_validator_that_stops_catching_something_fails_the_suite(monkeypatch):
    monkeypatch.setattr(repeats, "action_patterns", lambda *a, **k: [])
    checks = suite.regression_checks(suite.FIXTURES / "known_bad", "known_bad")
    assert any(not c.passed and "obstacle" in c.name for c in checks)


def test_cli_suite_exit_code(tmp_path):
    from typer.testing import CliRunner
    from bookforge import cli
    r = CliRunner().invoke(cli.app, ["suite", "--out", str(tmp_path)])
    assert r.exit_code == 0 and "all checks passed" in r.output
