"""The regression suite: `python -m bookforge suite`.

Checks that the validators still catch every failure the known-bad fixtures contain, that the test synopses (a thin one, a
multi-viewpoint one, a mystery, a second book of a series) produce what they should, and writes a report. Re-run it after any
change to a prompt, a setting or a validator.

Scripted mode (the default) needs no model: it builds each case's ledger from the synopsis sentences (valid by construction, with
the setups, reveals and endings the case is about marked by hand) and a mechanical stand-in plan (acts and chapters sized from event
weight), and runs the validators on them. `--live` plans each synopsis with the real models (ledger, acts, chapters, scenes) in a
scratch series and reports what they made. Test data is labelled as such. Nothing here generates prose for a whole book.
"""

import copy
import logging
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .sizing import WORDS_PER_BEAT
from .validators import ledger as L, prose as P, repeats as R, research_leak as RL, state as S, tension as T
from .validators.text import sentences

log = logging.getLogger("platform_bookforge.suite")
HERE = Path(__file__).resolve().parent
DATA = HERE / "suite_data"
FIXTURES = HERE.parent / "tests" / "fixtures"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    name: str
    synopsis: str
    ledger: list[dict] = field(default_factory=list)
    capacity: dict = field(default_factory=dict)
    questions: list[dict] = field(default_factory=list)
    acts: list[dict] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    findings: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)


# ── the known-bad fixtures: every listed failure must be caught ──────────────

def _load(path: Path, key: str | None = None):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get(key, []) if key else data


def regression_checks(folder: Path, label: str) -> list[Check]:
    """Run the validators on a folder of fixtures (known_bad, or b1) and check each failure pattern is reported."""
    if not (folder / "chapters.yaml").exists():
        return []
    out: list[Check] = []
    chapters, scenes = _load(folder / "chapters.yaml", "chapters"), _load(folder / "scenes.yaml", "scenes")
    acts = _load(folder / "acts.yaml", "acts") if (folder / "acts.yaml").exists() else []
    synopsis = (folder / "synopsis.md").read_text(encoding="utf-8") if (folder / "synopsis.md").exists() else ""
    ledger = _load(folder / "ledger.yaml", "events") if (folder / "ledger.yaml").exists() else []
    names = {w.lower() for e in (_load(folder / "constants.yaml", "entities") if (folder / "constants.yaml").exists() else [])
             for w in str(e.get("name", "")).split()} | {"mara", "corso"} if label == "known_bad" else set()
    tracks = _load(folder / "tracks.yaml", "tracks") if (folder / "tracks.yaml").exists() else []
    timeline = _load(folder / "timeline.yaml", "scenes") if (folder / "timeline.yaml").exists() else []
    notes = [n["claim"] for n in _load(folder / "research_notes.yaml", "notes")] if (folder / "research_notes.yaml").exists() else []
    prose_files = sorted((folder / "prose").glob("*.md")) if (folder / "prose").is_dir() else []
    prose = [(p.stem, p.read_text(encoding="utf-8")) for p in prose_files]

    def expect(name: str, findings, code: str, severity: str | None = None) -> None:
        hit = [f for f in findings if f.code == code and (severity is None or f.severity == severity)]
        out.append(Check(f"{label}: {name}", bool(hit), f"{len(hit)} finding(s) of {code}" if hit else f"NOT CAUGHT: no {code} finding"))

    ev_rep = R.repeated_events(chapters, scenes, names, ledger or None)
    expect("an event planned in several chapters (loops)", ev_rep, "event_repeated")
    expect("a chapter that replans another", ev_rep, "chapter_replans_chapter")
    expect("the same obstacle met the same way again and again", R.action_patterns(scenes, chapters, names), "action_pattern_repeated")
    expect("flat tension", T.flat_stretches(chapters), "flat_tension")
    if tracks:
        expect("a state that flips back without a cause", S.track_regressions(tracks), "state_regression")
        expect("a character in two places", S.location_conflicts(scenes, timeline, tracks), "two_places_at_once")
    if notes:
        expect("research terms in the beats", RL.research_in_beats(scenes, notes, [synopsis]), "research_in_beats")
    if ledger and acts:
        acts_f = L.check_acts(acts, ledger)
        expect("a once-only event told twice", L.check_chapters(chapters, ledger, acts), "once_only_repeated")
        expect("an event with no chapter (a missing turning point)", L.check_chapters(chapters, ledger, acts), "event_not_covered")
        expect("the resolution in no act", acts_f, "event_in_no_act")
        expect("an act with no turning point event", acts_f, "turning_point_without_event")
    elif acts and synopsis:
        expect("the synopsis's resolution is in no act", L.acts_text_coverage(acts, synopsis), "synopsis_not_in_acts")
    if prose:
        expect("copied sentences between scenes", P.repeated_sentences(prose), "sentences_repeated")
        if len(prose) > 1:
            expect("a chapter opening with the previous ending", P.chapter_openings_copy(prose), "chapter_opens_with_previous_ending")
        expect("wrap-up endings", P.wrap_up_endings(prose), "wrap_up_ending", "soft")
    return out


# ── the test synopses ────────────────────────────────────────────────────────

# per case: substring of a synopsis sentence -> overrides of the event made from it; weights 1 minor, 2 ordinary, 3 major
CASES = {
    "thin": dict(file="thin.md", expect_thin=True, marks={}, weights={}),
    "multi_pov": dict(file="multi_pov.md", expect_thin=False, min_chapters=4, weights={"closes its gates": 3, "reach the foreign house": 3, "strip the guildmaster": 3},
                      marks={"Dara Venn": dict(pov="dara"), "Tomas Oakby": dict(pov="tomas"), "Dara steals": dict(pov="dara"),
                             "Tomas escapes": dict(pov="tomas"), "grants the apprentices": dict(ending=True), "strip the guildmaster": dict(ending=True)}),
    "mystery": dict(file="mystery.md", expect_thin=False, min_chapters=4, weights={"Hale proves": 3, "Pryce confesses": 3},
                    marks={"clock stopped at ten past nine": dict(kind="setup"), "locked drawer": dict(kind="setup"),
                           "stopped on purpose": dict(kind="reveal", pays_off="@clock stopped at ten past nine"),
                           "opens the locked drawer": dict(kind="payoff", pays_off="@clock stopped at ten past nine"),
                           "Hale proves": dict(ending=True)}),
    "series_book2": dict(file="series_book2.md", expect_thin=False, min_chapters=4, carried="series_book2_carried.md", weights={"voids the debt": 3, "opens it": 3},
                         marks={"voids the debt": dict(ending=True), "Rhee returns": dict(carried_in=False)}),
}


def _event_sentences(text: str) -> list[str]:
    body = "\n\n".join(b for b in text.split("\n\n") if not b.lstrip().startswith("#"))
    return sentences(body)


def ledger_from_synopsis(text: str, weights: dict, marks: dict, default_weight: int = 2) -> list[dict]:
    """Test fixture: one event per sentence of the synopsis (so every excerpt is verbatim by construction), with the marks given."""
    events: list[dict] = []
    sents = _event_sentences(text)
    for i, s in enumerate(sents, 1):
        e = dict(id=f"e{i}", text=s.rstrip(".")[:120], excerpt=s, once_only=True, after=[f"e{i - 1}"] if i > 1 else [], kind="event",
                 weight=next((w for k, w in weights.items() if k in s), default_weight), pov="", ending=False, pays_off="", source="synopsis", parent="", carried_in=False)
        for key, over in marks.items():
            if key in s:
                e.update({k: v for k, v in over.items() if not (isinstance(v, str) and v.startswith("@"))})
        events.append(e)
    for key, over in marks.items():  # `pays_off: "@words"` names the event whose sentence contains the words
        for e in events:
            v = over.get("pays_off", "")
            if key in e["excerpt"] and isinstance(v, str) and v.startswith("@"):
                e["pays_off"] = next(x["id"] for x in events if v[1:] in x["excerpt"])
    if events and not any(e["ending"] for e in events):
        events[-1]["ending"] = True
    return events


def mechanical_plan(events: list[dict], book: str = "t", weight_per_chapter: float = 2.0) -> tuple[list[dict], list[dict]]:
    """A stand-in for the model: three acts (two for a short ledger), chapters sized from event weight. TEST DATA, not a plan."""
    n_acts = 3 if len(events) >= 6 else 2
    size = math.ceil(len(events) / n_acts)
    groups = [events[i:i + size] for i in range(0, len(events), size)]
    acts, chapters, num = [], [], 1
    for ai, g in enumerate(groups, 1):
        weight = sum(e["weight"] for e in g)
        count = max(1, round(weight / weight_per_chapter))
        count = min(count, len(g))  # a chapter per event at most: never pad with empty chapters
        acts.append(dict(id=f"{book}.act{ai}", title=f"Act {ai}", summary=" ".join(e["text"] for e in g), purpose="its movement of the story",
                         turning_point=g[-1]["text"], turning_point_event=g[-1]["id"], events=[e["id"] for e in g], chapter_count=count,
                         sizing_reason=f"weight {weight} over {len(g)} events: about {weight_per_chapter:g} weight per chapter gives {count}"))
        per = math.ceil(len(g) / count)
        for ci in range(count):
            part = g[ci * per:(ci + 1) * per]
            if not part:
                continue
            chapters.append(dict(id=f"{book}.ch{num:02d}", act=f"{book}.act{ai}", title=f"Chapter {num}", summary=" ".join(e["text"] for e in part),
                                 events_covered=[e["id"] for e in part], end_state=f"after: {part[-1]['text']}", tension=min(10, 3 + num)))
            num += 1
        acts[-1]["chapter_count"] = sum(1 for c in chapters if c["act"] == f"{book}.act{ai}")
    return acts, chapters


def scripted_case(name: str, spec: dict, cfg_weight: float = 2.0) -> CaseResult:
    min_chapters = spec.get("min_chapters", 12)  # the short test synopses are judged against a smaller minimum than a novel's 12
    synopsis = (DATA / spec["file"]).read_text(encoding="utf-8")
    res = CaseResult(name=name, synopsis=synopsis)
    res.ledger = ledger_from_synopsis(synopsis, spec.get("weights", {}), spec.get("marks", {}), default_weight=spec.get("default_weight", 2))
    from .layers.ledger import capacity
    res.capacity = capacity(res.ledger, cfg_weight, min_chapters)
    res.findings += L.check_ledger(res.ledger, synopsis)
    if res.capacity["thin"]:
        res.questions = [dict(id="q1", question="What complication stands in the way between the opening and the decision?",
                              why=f"The synopsis carries about {res.capacity['estimated_chapters']} chapters of story; a novel needs at least {min_chapters}",
                              options=["a rival wants the same thing", "an earlier choice comes back to cost them"])]
        res.notes.append("thin: the stand-in plan is not made; the ledger stage would ask the author these questions instead of padding")
    else:
        res.acts, res.chapters = mechanical_plan(res.ledger)
        res.findings += L.check_acts(res.acts, res.ledger) + L.check_chapters(res.chapters, res.ledger, res.acts) + R.repeated_events(res.chapters, [], ledger_events=res.ledger)
    hard = [f for f in res.findings if f.severity == "hard"]
    res.checks.append(Check(f"{name}: thin synopsis detected" if spec["expect_thin"] else f"{name}: enough story, not thin",
                            res.capacity["thin"] == spec["expect_thin"], f"estimated {res.capacity['estimated_chapters']} chapters (minimum {min_chapters})"))
    res.checks.append(Check(f"{name}: no hard findings on a correct ledger and plan", not hard, "; ".join(f.line() for f in hard[:3]) or "clean"))
    if not spec["expect_thin"]:
        res.checks += _break_it(res, name)
    return res


def _break_it(res: CaseResult, name: str) -> list[Check]:
    """The same case with one defect each: the validators must say so."""
    out = []
    ev, acts, chapters = res.ledger, res.acts, res.chapters
    no_end = [e for e in copy.deepcopy(ev) if not e["ending"]]
    out.append(Check(f"{name}: dropping the resolution is caught", any(f.code in ("no_resolution", "synopsis_not_covered") for f in L.check_ledger(no_end, res.synopsis))))
    twice = copy.deepcopy(chapters)
    if len(twice) > 2:
        twice[-1]["events_covered"] = twice[1]["events_covered"][:1] + twice[-1]["events_covered"]
        out.append(Check(f"{name}: telling a once-only event twice is caught", any(f.code == "once_only_repeated" for f in L.check_chapters(twice, ev, acts))))
    reserved = copy.deepcopy(chapters)
    if len(reserved) > 2:
        reserved[0]["events_covered"] = reserved[0]["events_covered"] + [chapters[-1]["events_covered"][-1]]
        out.append(Check(f"{name}: using an event reserved for a later act is caught", any(f.code == "event_from_other_act" for f in L.check_chapters(reserved, ev, acts))))
    pays = [e for e in ev if e["pays_off"]]
    if pays:
        swapped = copy.deepcopy(ev)
        i = next(n for n, e in enumerate(swapped) if e["id"] == pays[0]["pays_off"])
        j = next(n for n, e in enumerate(swapped) if e["id"] == pays[0]["id"])
        swapped[i], swapped[j] = swapped[j], swapped[i]
        out.append(Check(f"{name}: a reveal before its setup is caught", any(f.code in ("reveal_before_setup", "event_order") for f in L.check_ledger(swapped, res.synopsis))))
    return out


# ── the report ───────────────────────────────────────────────────────────────

def _mapping(res: CaseResult) -> list[str]:
    lines = []
    by_act: dict[str, list[dict]] = {}
    for c in res.chapters:
        by_act.setdefault(c["act"], []).append(c)
    for a in res.acts:
        lines.append(f"- **{a['id']} {a.get('title', '')}**: events {', '.join(a['events'])}; {a['chapter_count']} chapter(s). _Sizing: {a.get('sizing_reason', '(none given)')}_")
        for c in by_act.get(a["id"], []):
            lines.append(f"  - {c['id']}: covers {', '.join(c['events_covered'])}; ends with: {c.get('end_state', '')}")
    return lines


def render_report(results: list[CaseResult], regression: list[Check], mode: str, before_after: list[str] | None = None) -> str:
    out = [f"# Bookforge regression suite ({mode})", "", "Test data: the synopses below are short synthetic cases, not real books.", ""]
    failed = [c for c in regression + [c for r in results for c in r.checks] if not c.passed]
    out += [f"**{'FAILED: ' + str(len(failed)) + ' check(s)' if failed else 'All checks passed.'}**", ""]
    out += ["## Known-bad fixtures: every failure must be caught", ""] + [f"- {'PASS' if c.passed else 'FAIL'}  {c.name}: {c.detail}" for c in regression] + [""]
    if before_after:
        out += ["## b1: before and after", ""] + before_after + [""]
    for r in results:
        out += [f"## Case: {r.name}", ""]
        cap = r.capacity
        if cap:
            out += [f"Capacity: total weight {cap['total_weight']} / {cap['weight_per_chapter']:g} per chapter = {cap['estimated_chapters']} chapters (minimum {cap['minimum_chapters']}): "
                    f"{'THIN, the author is asked' if cap['thin'] else 'enough'}. Formula: `{cap['formula']}`", ""]
        out += ["### Ledger", ""] + [f"- {e['id']} ({'once' if e['once_only'] else 'repeatable'}, {e['kind']}, w{e['weight']}{', ENDING' if e['ending'] else ''}{', pays ' + e['pays_off'] if e['pays_off'] else ''}{', pov ' + e['pov'] if e['pov'] else ''}): {e['text']}" for e in r.ledger] + [""]
        if r.questions:
            out += ["### Author questions", ""] + [f"- {q['id']}: {q['question']} ({q['why']}). Options: {'; '.join(q['options'])}" for q in r.questions] + [""]
        if r.acts:
            out += ["### Acts and chapters", ""] + _mapping(r) + [""]
            total_ch = len(r.chapters)
            out += [f"Planned: {len(r.acts)} acts, {total_ch} chapters. Words come out of the plan (about {WORDS_PER_BEAT[0]} to {WORDS_PER_BEAT[1]} a beat), they are not aimed at.", ""]
        out += ["### Validator results", ""] + ([f"- [{f.severity}] {f.line()}" for f in r.findings] or ["- none"]) + [""]
        out += ["### Checks", ""] + [f"- {'PASS' if c.passed else 'FAIL'}  {c.name}: {c.detail}" for c in r.checks] + [""]
        out += [f"_{n}_" for n in r.notes] + ([""] if r.notes else [])
    return "\n".join(out) + "\n"


def b1_before(folder: Path) -> list[str]:
    """The failures on b1's existing plan, counted with the same validators (the 'before' half of the comparison)."""
    if not (folder / "chapters.yaml").exists():
        return ["No real b1 files yet: copy them into `tests/fixtures/b1/` (see the README there)."]
    chapters, scenes = _load(folder / "chapters.yaml", "chapters"), _load(folder / "scenes.yaml", "scenes")
    acts = _load(folder / "acts.yaml", "acts") if (folder / "acts.yaml").exists() else []
    synopsis = (folder / "synopsis.md").read_text(encoding="utf-8") if (folder / "synopsis.md").exists() else ""
    rep = R.repeated_events(chapters, scenes)
    cover = L.acts_text_coverage(acts, synopsis) if synopsis else []
    return [f"- event repeats found: {sum(f.code == 'event_repeated' for f in rep)}; chapters replanning another: {sum(f.code == 'chapter_replans_chapter' for f in rep)}",
            f"- action patterns repeated: {len(R.action_patterns(scenes, chapters))}; flat tension stretches: {len(T.flat_stretches(chapters))}",
            f"- synopsis paragraphs taken up by no act: {len(cover)}" + "".join(f"\n  - {f.message}" for f in cover),
            "- After (live): run `suite --live --case b1` once the ledger stage is approved for b1; the ending and each act's turning point must each be told in exactly one chapter."]


def run_scripted() -> tuple[list[CaseResult], list[Check], list[str]]:
    regression = regression_checks(FIXTURES / "known_bad", "known_bad") + regression_checks(FIXTURES / "b1", "b1")
    results = [scripted_case(name, spec) for name, spec in CASES.items()]
    return results, regression, b1_before(FIXTURES / "b1")


def run_live(out_dir: Path, only: str | None = None) -> list[CaseResult]:
    """Plan each synopsis with the real models in a scratch series (ledger -> acts -> chapters -> scenes). Needs the model endpoints."""
    from .bible import store
    from .layers import HANDLERS
    from .layers.runner import run
    from .llm import build_client
    from .project import Project
    from .sizing import planned_words
    results: list[CaseResult] = []
    for name, spec in CASES.items():
        if only and name != only:
            continue
        synopsis = (DATA / spec["file"]).read_text(encoding="utf-8")
        root = out_dir / "live" / name
        if root.exists():
            shutil.rmtree(root)
        carried = (DATA / spec["carried"]).read_text(encoding="utf-8") if spec.get("carried") else ""
        project = Project.create(root, "Test data for the Bookforge suite.\n" + carried)
        stars = "# Test north star\n\n" + "\n\n".join(f"## {s}\nTest data for the regression suite, {s.lower()}." for s in
                ("Premise", "Themes", "Emotional promise", "Tone", "Realism", "Ending direction", "What it is not"))
        (project.root / "north-star.md").write_text(stars)
        (project.book_dir / "north-star.md").write_text(stars)
        (project.book_dir / "synopsis.md").write_text(synopsis)
        if carried:
            (project.root / "ledger.yaml").write_text("open_threads: []\nend_of_book_states:\n  book1: |\n" + "".join(f"    {l}\n" for l in carried.splitlines()))
        for layer in ("series_north_star", "book_north_star", "synopsis"):
            project.state.set_layer_status(layer, "accepted")
        project.state.reach_checkpoint("direction")
        project.state.approve_checkpoint("direction")
        project.save_state()
        llm = build_client(project)
        res = CaseResult(name=name, synopsis=synopsis)
        for _ in range(4):
            summary = run(project, llm, HANDLERS, until="scenes")
            res.notes.append(summary.detail or summary.stopped)
            led = store.load_ledger(project) if store.ledger_path(project).exists() else None
            if summary.stopped == "checkpoint" and project.state.checkpoints["ledger"].status == "waiting" and led and not any(q.status == "open" for q in led.questions):
                project.state.approve_checkpoint("ledger")
                project.save_state()
                continue
            if summary.stopped == "checkpoint" and project.state.checkpoints["structure"].status == "waiting":
                break
            break
        led = store.load_ledger(project) if store.ledger_path(project).exists() else None
        if led:
            res.ledger = [e.model_dump() for e in led.events]
            res.capacity = led.capacity
            res.questions = [q.model_dump() for q in led.questions if q.status == "open"]
        if store.acts_path(project).exists():
            res.acts = [a.model_dump() for a in store.load_acts(project)]
        if store.chapters_path(project).exists():
            res.chapters = [c.model_dump() for c in store.load_chapters(project)]
        if store.scenes_path(project).exists():
            sc = store.load_scenes(project)
            lo, hi = planned_words(project, sc)
            res.notes.append(f"{len(sc)} scenes planned; the plan comes to about {lo} to {hi} words")
        from .validators import store as findings_store
        for stage in ("ledger", "acts", "chapters", "scenes"):
            for f in findings_store.load(project, stage)["findings"]:
                from .validators.findings import Finding
                res.findings.append(Finding(**f))
        res.checks.append(Check(f"{name}: planned without a failed stage", project.state.layers["scenes"].status == "accepted" or bool(res.questions),
                                "; ".join(res.notes[-2:])))
        results.append(res)
    return results


def run_suite(out_dir: Path, live: bool = False, only: str | None = None) -> tuple[str, bool]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scripted, regression, before = run_scripted()
    if only:
        scripted = [r for r in scripted if r.name == only]
    results = run_live(out_dir, only) if live else scripted
    report = render_report(results, regression, "live: real models" if live else "scripted: no model", before)
    path = out_dir / "suite-report.md"
    path.write_text(report, encoding="utf-8")
    all_checks = regression + [c for r in results for c in r.checks]
    return str(path), all(c.passed for c in all_checks)
