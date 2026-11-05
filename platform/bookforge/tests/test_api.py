"""Milestone 14.10: the HTTP API over the pipeline library."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

import main
from bookforge import api, changes
from bookforge.bible import store
from bookforge.project import Project
from conftest import RuleLLM
from qc_fakes import EXTRACT, JUDGE, between, extractor, judge, user
from test_prose_qc import book, qc_rules  # noqa: F401  (book is a fixture)
from test_report_assemble_bench import ALL, bench_llm, full  # noqa: F401  (full is a fixture)
from prose_fakes import prose

client = TestClient(main.app, raise_server_exceptions=False)
B = "/api/series/series/books/b1"


@pytest.fixture(autouse=True)
def data_dir(book, monkeypatch):
    """The `series` folder of the book fixture is the only series in the data directory."""
    monkeypatch.setattr(main, "DATA_DIR", str(book.root.parent))
    monkeypatch.setattr(api, "make_web", lambda project: None)
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM(qc_rules()))


def data(r, code=200):
    assert r.status_code == code, r.text
    body = r.json()
    assert body["status"] == "ok"
    return body["data"]


def error(r, code):
    assert r.status_code == code, r.text
    body = r.json()
    assert body["status"] == "error" and body["detail"]
    return body


def finish(job):
    api.jobs.wait(job["id"], 60)
    return data(client.get(f"{B}/jobs/{job['id']}"))


# ── series and books ────────────────────────────────────────────────────────

def test_series_are_listed_with_their_books():
    assert data(client.get("/api/series")) == [{"name": "series", "books": ["b1"], "busy": None}]


def test_a_series_can_be_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path / "fresh"))
    made = data(client.post("/api/series", json={"name": "my-series", "premise": "A clerk finds a ledger."}), 201)
    assert made == {"name": "my-series", "book": "b1"}
    assert [s["name"] for s in data(client.get("/api/series"))] == ["my-series"]
    error(client.post("/api/series", json={"name": "my-series", "premise": "x"}), 409)
    error(client.post("/api/series", json={"name": "Bad Name", "premise": "x"}), 422)
    error(client.post("/api/series", json={"name": "ok-name", "premise": "  "}), 400)


def test_unknown_series_books_and_odd_names_are_404():
    for url in ("/api/series/nope/books/b1/status", f"{B.replace('b1', 'b9')}/status", "/api/series/..%2fx/books/b1/status",
                "/api/series/series/books/B1/status"):
        error(client.get(url), 404)


def test_status_shows_layers_checkpoints_and_scene_counts(book):
    s = data(client.get(f"{B}/status"))
    assert [l["name"] for l in s["layers"]][:3] == ["series_north_star", "book_north_star", "synopsis"]
    assert s["checkpoints"]["structure"] == "approved" and s["checkpoints"]["voice"] == "pending"
    assert s["scenes"] == {"total": 8, "pending": 8} and s["job"] is None and s["manuscript"] is False


def test_scenes_and_one_scene(full):
    listing = data(client.get(f"{B}/scenes"))
    assert [x["id"] for x in listing] == ALL and all(x["status"] == "accepted" and x["words"] > 100 for x in listing)
    one = data(client.get(f"{B}/scenes/b1.ch01.s1"))
    assert one["plan"]["id"] == "b1.ch01.s1" and one["text"] and one["summary"] and one["review"]["chosen"].startswith("draft-")
    error(client.get(f"{B}/scenes/b1.ch09.s1"), 404)


def test_reports(full):
    assert "# Morning report: b1" in data(client.get(f"{B}/report"))["markdown"]
    assert data(client.get(f"{B}/reports")) == []
    from bookforge import report
    name = report.write_report(full).split("/")[-1]
    assert data(client.get(f"{B}/reports")) == [name]
    assert "Morning report" in data(client.get(f"{B}/reports/{name}"))["markdown"]
    error(client.get(f"{B}/reports/notes.txt"), 404)
    error(client.get(f"{B}/reports/..md"), 404)


def test_stale_lists_reasons_without_changing_anything(full):
    constants = store.load_constants(full)
    constants.entities[0].facts = ["a different fact"]
    store.save_constants(full, constants)
    s = data(client.get(f"{B}/stale"))
    assert s["scenes"][0]["scene"] == "b1.ch01.s1" and s["scenes"][0]["level"] == "recheck"
    assert any("entity:anna changed" in r for r in s["scenes"][0]["reasons"])
    assert data(client.get(f"{B}/scenes"))[0]["status"] == "accepted"  # a read does not mark anything


# ── decisions ───────────────────────────────────────────────────────────────

def test_approving_a_waiting_checkpoint(book):
    error(client.post(f"{B}/approve/voice"), 400)  # not waiting
    p = Project.open(book.root)
    p.state.reach_checkpoint("voice")
    p.save_state()
    assert data(client.post(f"{B}/approve/voice")) == {"checkpoint": "voice", "status": "approved"}
    assert data(client.get(f"{B}/status"))["checkpoints"]["voice"] == "approved"
    error(client.post(f"{B}/approve/nonsense"), 400)


def file_gap(p):
    scene = store.load_scenes(p)[0]
    [cr] = changes.file_gaps(p, scene, store.load_scenes(p), [{"track": "jonas-knows", "planned": "knows nothing", "observed": "suspects", "evidence": "e"}])
    return cr


def test_change_requests_are_listed_and_decided(full):
    cr = file_gap(full)
    assert data(client.get(f"{B}/changes"))[0]["id"] == cr.id
    assert data(client.get(f"{B}/status"))["pending_changes"] == 1
    assert data(client.get(f"{B}/scenes/b1.ch01.s1"))["change_requests"][0]["id"] == cr.id
    assert data(client.post(f"{B}/changes/{cr.id}/approve"))["status"] == "applied"
    error(client.post(f"{B}/changes/{cr.id}/reject"), 400)
    error(client.post(f"{B}/changes/{cr.id}/maybe"), 404)


def test_assembling(book, full):
    assert data(client.post(f"{B}/assemble"))["scenes"] == 8
    assert "# Act 1" in data(client.get(f"{B}/manuscript"))["markdown"]
    assert data(client.get(f"{B}/status"))["checkpoints"]["final"] == "waiting"


def test_assembling_an_unfinished_book_is_a_400_and_partial_works(book):
    error(client.post(f"{B}/assemble"), 400)
    error(client.get(f"{B}/manuscript"), 404)
    assert data(client.post(f"{B}/assemble", json={"partial": True}))["scenes"] == 0


# ── jobs ────────────────────────────────────────────────────────────────────

def test_a_run_is_a_background_job_with_a_saved_record(book):
    job = data(client.post(f"{B}/run", json={"until": "prose"}), 202)
    assert job["kind"] == "run" and job["status"] in ("running", "done") and job["params"] == {"until": "prose"}
    done = finish(job)
    assert done["status"] == "done" and done["result"]["stopped"] == "checkpoint" and done["result"]["report"].startswith("books/b1/reports/")
    assert (book.book_dir / "logs" / "jobs" / f"{job['id']}.json").exists()
    assert [j["id"] for j in data(client.get(f"{B}/jobs"))] == [job["id"]]
    assert data(client.get(f"{B}/status"))["scenes"]["accepted"] == 2
    error(client.post(f"{B}/run", json={"until": "nonsense"}), 422)
    error(client.get(f"{B}/jobs/nope"), 404)
    error(client.get(f"{B}/jobs/20200101-000000-ffff"), 404)


def test_a_failing_job_is_recorded_not_lost(monkeypatch):
    def boom(project):
        raise RuntimeError("the model server is gone")

    monkeypatch.setattr(api, "make_llm", boom)
    done = finish(data(client.post(f"{B}/run"), 202))
    assert done["status"] == "failed" and "the model server is gone" in done["error"]
    assert data(client.get(f"{B}/status"))["job"] is None  # the series is free again


def test_one_job_at_a_time_and_changes_wait_but_reads_do_not(book, monkeypatch):
    gate = threading.Event()
    started = threading.Event()

    class Slow(RuleLLM):
        def complete(self, role, messages, **options):
            started.set()
            gate.wait(30)
            return super().complete(role, messages, **options)

    monkeypatch.setattr(api, "make_llm", lambda project: Slow(qc_rules()))
    job = data(client.post(f"{B}/run", json={"until": "prose"}), 202)
    assert started.wait(30)
    try:
        assert "is running" in error(client.post(f"{B}/run"), 409)["detail"]
        error(client.post(f"{B}/approve/voice"), 409)
        error(client.post(f"{B}/assemble"), 409)
        error(client.post(f"{B}/bench"), 409)
        assert data(client.get(f"{B}/status"))["job"]["id"] == job["id"]
        assert data(client.get("/api/series"))[0]["busy"]["id"] == job["id"]
        assert data(client.get(f"{B}/scenes"))  # reads are fine
    finally:
        gate.set()
    assert finish(job)["status"] == "done"
    data(client.post(f"{B}/run", json={"until": "prose"}), 202)  # free again
    api.jobs.wait(data(client.get(f"{B}/jobs"))[0]["id"], 60)


def test_a_record_left_running_by_a_dead_process_shows_as_interrupted(book):
    d = book.book_dir / "logs" / "jobs"
    d.mkdir(parents=True)
    (d / "20200101-000000-aaaa.json").write_text(json.dumps({"id": "20200101-000000-aaaa", "series": "series", "book": "b1", "kind": "run", "status": "running"}))
    assert data(client.get(f"{B}/jobs/20200101-000000-aaaa"))["status"] == "interrupted"
    assert data(client.get(f"{B}/status"))["job"] is None


def test_stale_fix_is_a_job(full, monkeypatch):
    constants = store.load_constants(full)
    constants.entities[0].facts = ["a different fact"]
    store.save_constants(full, constants)
    done = finish(data(client.post(f"{B}/stale/fix", json={"only": ["b1.ch01.s1"]}), 202))
    assert done["status"] == "done" and [(f["scene"], f["action"]) for f in done["result"]["fixes"]] == [("b1.ch01.s1", "rechecked")]
    still = [s["scene"] for s in done["result"]["still_stale"]]
    assert "b1.ch01.s1" not in still and "b1.ch01.s2" in still  # only the one asked for was fixed


def test_bench_is_a_job_and_a_bad_name_fails_at_once(book, monkeypatch):
    monkeypatch.setattr(api, "make_llm", lambda project: bench_llm(lambda n: prose(0, 22)))
    error(client.post(f"{B}/bench", json={"only": ["nope"]}), 422)
    done = finish(data(client.post(f"{B}/bench", json={"only": ["quarrel"], "accept": True}), 202))
    assert done["status"] == "done" and done["result"]["accepted"] is True and "quarrel" in done["result"]["results"]
    assert done["result"]["comparison"] is None


def test_doctor_offline(book):
    checks = data(client.get("/api/doctor?offline=true&series=series"))
    assert checks and {"name", "level", "detail"} <= set(checks[0])


# ── the dashboard's views ───────────────────────────────────────────────────

def test_structure_is_acts_chapters_scenes_with_status(full):
    tree = data(client.get(f"{B}/structure"))
    assert [a["title"] for a in tree] == ["Act 1", "Act 2"]
    assert [c["id"] for c in tree[0]["chapters"]] == ["b1.ch01", "b1.ch02"]
    assert [s["id"] for s in tree[1]["chapters"][0]["scenes"]] == ["b1.ch03.s1", "b1.ch03.s2"]
    assert {s["status"] for a in tree for c in a["chapters"] for s in c["scenes"]} == {"accepted"}


def test_structure_of_a_fresh_book_is_empty():
    assert data(client.get(f"{B}/structure")) != []  # the book fixture has its plan, nothing written
    assert {s["status"] for a in data(client.get(f"{B}/structure")) for c in a["chapters"] for s in c["scenes"]} == {"pending"}


def test_tracks_come_with_plan_observed_and_the_story_order(full):
    t = data(client.get(f"{B}/tracks"))
    assert [s["id"] for s in t["scenes"]] == ALL and t["chapters"] == ["b1.ch01", "b1.ch02", "b1.ch03", "b1.ch04"]
    wound = next(x for x in t["tracks"] if x["id"] == "anna-wound")
    assert wound["entity_name"] == "Anna Voss" and [e["from"] for e in wound["plan"]][0].startswith("b1.ch0")
    assert wound["plan"][0]["must_show"] is True


def test_research_lists_facts_with_the_scenes_that_use_them(full):
    from bookforge.research.notes import stores_for
    st = next(iter(stores_for(full).values()))
    f = st.add_fact(claim="A claim.", url="https://example.org/a", title="A", fetched="2026-01-01", quote="q", layer="chapters", question="?", sensitive=True)
    scenes = store.load_scenes(full)
    scenes[1].research = [f.id]
    store.save_scenes(full, scenes)
    [fact] = data(client.get(f"{B}/research"))
    assert fact["claim"] == "A claim." and fact["sensitive"] is True and fact["used_in"] == [scenes[1].id]


def test_a_scene_carries_its_drafts_for_comparison(full):
    one = data(client.get(f"{B}/scenes/b1.ch01.s1"))
    assert sorted(one["drafts"]) == ["draft-1", "draft-2"] and all(len(t) > 100 for t in one["drafts"].values())
    assert one["review"]["chosen"] in one["drafts"]


# ── Web Push ────────────────────────────────────────────────────────────────

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "pk", "auth": "ak"}}


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "push_sender", lambda **kw: calls.append(kw))
    return calls


def test_push_key_is_stable_and_subscriptions_are_counted():
    first = data(client.get("/api/push/key"))
    assert len(first["public_key"]) > 60 and first["subscriptions"] == 0
    assert data(client.get("/api/push/key"))["public_key"] == first["public_key"]
    assert data(client.post("/api/push/subscribe", json=SUB))["subscriptions"] == 1
    assert data(client.post("/api/push/subscribe", json=SUB))["subscriptions"] == 1  # same endpoint: replaced
    assert data(client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}))["subscriptions"] == 0
    error(client.post("/api/push/subscribe", json={"endpoint": "x"}), 422)


def test_the_keys_live_outside_the_series_folder(book):
    data(client.get("/api/push/key"))
    assert (book.root.parent / "push.db").exists() and not list(book.root.rglob("push.db"))


def test_a_test_notification_reaches_every_subscription(sent):
    client.post("/api/push/subscribe", json=SUB)
    client.post("/api/push/subscribe", json={**SUB, "endpoint": "https://push.example/def"})
    assert data(client.post("/api/push/test"))["delivered"] == 2
    payload = json.loads(sent[0]["data"])
    assert payload["title"] == "Bookforge" and sent[0]["subscription_info"]["keys"] == {"p256dh": "pk", "auth": "ak"}
    assert sent[0]["vapid_private_key"].startswith("-----BEGIN")


def test_dead_subscriptions_are_removed(monkeypatch):
    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def sender(**kw):
        raise Gone()

    monkeypatch.setattr(api, "push_sender", sender)
    client.post("/api/push/subscribe", json=SUB)
    assert data(client.post("/api/push/test"))["delivered"] == 0
    assert data(client.get("/api/push/key"))["subscriptions"] == 0


def test_a_run_that_reaches_a_checkpoint_sends_a_notification(book, sent):
    client.post("/api/push/subscribe", json=SUB)
    finish(data(client.post(f"{B}/run", json={"until": "prose"}), 202))
    [call] = sent
    p = json.loads(call["data"])
    assert p["title"] == "Bookforge: waiting for you" and "voice" in p["body"] and p["url"] == "/bookforge/#/series/series/b1"


def test_a_failed_job_sends_a_notification(sent, monkeypatch):
    def boom(project):
        raise RuntimeError("the model server is gone")

    monkeypatch.setattr(api, "make_llm", boom)
    client.post("/api/push/subscribe", json=SUB)
    finish(data(client.post(f"{B}/run"), 202))
    assert json.loads(sent[0]["data"])["title"] == "Bookforge: run failed" and "the model server is gone" in json.loads(sent[0]["data"])["body"]


def test_which_jobs_notify():
    from bookforge.jobs import Job
    def job(kind, result=None, status="done", error=None):
        return Job(id="1", series="s", book="b1", kind=kind, status=status, result=result, error=error)

    assert api.notification_for(job("run", {"stopped": "until"})) is None
    assert api.notification_for(job("stale-fix", {"fixes": []})) is None
    assert api.notification_for(job("bench", {"comparison": {"ships": True}})) is None
    assert api.notification_for(job("bench", {"comparison": {"ships": False}}))[0] == "Bookforge: benchmark loses"
    assert api.notification_for(job("run", {"stopped": "complete", "assembled": {"path": "x"}}))[1].endswith("manuscript assembled")
    assert api.notification_for(job("run", {"stopped": "failed", "detail": "layer 'prose' needs you"}))[0] == "Bookforge: needs you"
    assert api.notification_for(job("run", status="failed", error="e"))[0] == "Bookforge: run failed"


# ── export ──────────────────────────────────────────────────────────────────

@pytest.fixture
def exported(full):
    from bookforge import assemble as asm
    asm.assemble(full)
    full.state.approve_checkpoint("final")
    full.save_state()
    (full.root / "config.yaml").write_text((full.root / "config.yaml").read_text() + "export:\n  title: T\n")
    from bookforge import vcs
    vcs.commit(full.root, "test: export config")
    return full


@pytest.mark.skipif(__import__("shutil").which("pandoc") is None, reason="pandoc is not installed")
def test_export_is_a_job_and_its_files_can_be_downloaded(exported):
    job = data(client.post(f"{B}/export", json={"formats": ["companion"]}), 202)
    done = finish(job)
    assert done["status"] == "done" and done["result"]["files"][0].endswith("b1-companion.md") and done["result"]["tag"].startswith("b1-export-")
    [x] = data(client.get(f"{B}/exports"))
    assert x["name"] == done["result"]["name"] and x["files"][0] == "b1-companion.md"
    r = client.get(f"{B}/exports/{x['name']}/b1-companion.md")
    assert r.status_code == 200 and "# Companion to T" in r.text
    error(client.get(f"{B}/exports/{x['name']}/export.json"), 404)
    error(client.get(f"{B}/exports/{x['name']}/.hidden"), 404)
    error(client.get(f"{B}/exports/{x['name']}/nope.pdf"), 404)
    error(client.get(f"{B}/exports/..%2f..%2fstate.json/x"), 404)


def test_export_validates_formats_and_reports_a_blocked_book_as_a_failed_job(full):
    error(client.post(f"{B}/export", json={"formats": ["mobi"]}), 422)
    done = finish(data(client.post(f"{B}/export"), 202))  # the final checkpoint is not approved
    assert done["status"] == "failed" and "final checkpoint is not approved" in done["error"]


# ── the workbench ───────────────────────────────────────────────────────────

WB = f"{B}/workbench"
RULE = {"id": "no-purple", "type": "style_rule", "text": "No purple prose.", "severity": "warn", "scope": "series", "target": "", "example": "", "phrase": "", "enabled": True}


def test_rules_are_saved_listed_with_stats_and_deleted(full):
    assert data(client.get(f"{WB}/rules")) == {"rules": [], "stats": [], "health": []}
    assert data(client.put(f"{WB}/rules/no-purple", json=RULE))["id"] == "no-purple"
    got = data(client.get(f"{WB}/rules"))
    assert [r["id"] for r in got["rules"]] == ["no-purple"] and got["stats"][0]["applicable"] == 8
    error(client.put(f"{WB}/rules/other", json=RULE), 422)
    error(client.put(f"{WB}/rules/bad", json={**RULE, "id": "bad", "type": "banned_phrase"}), 422)  # no phrase
    assert data(client.delete(f"{WB}/rules/no-purple")) == {"deleted": "no-purple"}
    error(client.delete(f"{WB}/rules/no-purple"), 400)


def test_testing_a_rule_and_proposing_one_are_jobs(full, monkeypatch):
    text = scenefiles_text(full)
    phrase = " ".join(text.split()[2:5])
    done = finish(data(client.post(f"{WB}/rules-test", json={"rule": {**RULE, "type": "banned_phrase", "phrase": phrase}}), 202))
    assert done["status"] == "done" and done["result"]["total_hits"] >= 1
    llm = RuleLLM([("The author read a passage of a scene", json.dumps({"type": "style_rule", "scope": "series", "target": "", "severity": "warn", "text": "Avoid purple.", "example": "", "phrase": ""}))])
    monkeypatch.setattr(api, "make_llm", lambda project: llm)
    done = finish(data(client.post(f"{WB}/rules-propose", json={"scene": "b1.ch01.s1", "passage": "the crimson sky", "comment": "too purple"}), 202))
    assert done["result"]["text"] == "Avoid purple." and done["result"]["id"] == "avoid-purple"


def scenefiles_text(p):
    from bookforge import scenefiles
    return scenefiles.final_path(p, "b1.ch01.s1").read_text()


def test_the_briefing_preview_and_the_input_xray(full):
    b = data(client.get(f"{WB}/briefing/b1.ch02.s1"))
    assert b["sections"] and b["tokens"] == sum(s["tokens"] for s in b["sections"])
    x = data(client.get(f"{WB}/xray/b1.ch02.s1"))
    assert {f["kind"] for f in x["findings"]} >= {"no_style_guide", "no_samples"} and x["diagnosis"]["cause"] == "missing_input" and x["beats"] is None
    error(client.get(f"{WB}/briefing/b1.ch09.s9"), 400)


def test_the_beat_check_is_a_job(full, monkeypatch):
    def reply(messages):
        text = between(user(messages), "scene")
        return json.dumps({"beats": [{"n": i, "happens": True, "evidence": " ".join(text.split()[:8])} for i in (1, 2)]})

    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("Check which of the planned beats", reply)]))
    done = finish(data(client.post(f"{WB}/xray/b1.ch01.s1", json={}), 202))
    assert done["status"] == "done" and [b["happens"] for b in done["result"]["beats"]] == [True, True]


def test_prompts_can_be_listed_checked_overridden_and_restored(full):
    names = {t["name"] for t in data(client.get(f"{WB}/prompts"))}
    assert {"prose", "critic"} <= names
    p = data(client.get(f"{WB}/prompts/prose"))
    assert p["override"] is None and "briefing" in p["slots"]
    bad = data(client.post(f"{WB}/prompts/prose/check", json={"text": "{nonsense}"}))
    assert bad["errors"]
    error(client.put(f"{WB}/prompts/prose", json={"text": "{nonsense}"}), 400)
    assert data(client.put(f"{WB}/prompts/prose", json={"text": p["default"] + "\nBe brief.\n"}))["errors"] == []
    assert "Be brief." in data(client.get(f"{WB}/prompts/prose"))["override"]
    data(client.delete(f"{WB}/prompts/prose"))
    assert data(client.get(f"{WB}/prompts/prose"))["override"] is None
    error(client.get(f"{WB}/prompts/nope"), 400)


def test_an_ab_test_is_a_job_you_vote_on_blind_and_can_promote(full, monkeypatch):
    from test_workbench import ab_llm
    monkeypatch.setattr(api, "make_llm", lambda project: ab_llm())
    default = data(client.get(f"{WB}/prompts/prose"))["default"]
    cand = default.replace("Return only the scene text.", "ZEBRA: return only the scene text.")
    error(client.post(f"{WB}/ab", json={"template": "critic", "candidate": "x"}), 422)
    error(client.post(f"{WB}/ab", json={"template": "prose", "candidate": "{nonsense}"}), 422)
    done = finish(data(client.post(f"{WB}/ab", json={"template": "prose", "candidate": cand, "only": ["quarrel"]}), 202))
    name = done["result"]["name"]
    assert done["result"]["judge"]["b"] == 1
    assert [e["name"] for e in data(client.get(f"{WB}/experiments"))] == [name]
    v = data(client.get(f"{WB}/experiments/{name}"))
    assert v["pairs"][0]["voted"] is False and "first_is" not in v["pairs"][0] and v["judge"] is None
    after = data(client.post(f"{WB}/experiments/{name}/vote", json={"benchmark": "quarrel", "choice": "tie"}))
    assert after["pairs"][0]["voted"] and after["yours"]["tie"] == 1
    error(client.post(f"{WB}/experiments/{name}/vote", json={"benchmark": "quarrel", "choice": "left"}), 400)
    data(client.post(f"{WB}/experiments/{name}/promote"))
    assert "ZEBRA" in data(client.get(f"{WB}/prompts/prose"))["override"]
    error(client.get(f"{WB}/experiments/ab-19990101-000000"), 400)


def test_calibration_scores_and_the_arc(full):
    scores = {c: 4 for c in ("stakes", "voice", "show_dont_tell", "pacing", "dialogue", "beats_covered")}
    r = data(client.put(f"{WB}/calibration/b1.ch01.s1", json={"scores": scores}))
    assert r["scenes"][0]["yours"]["voice"] == 4 and r["scenes"][0]["critic"] is not None
    error(client.put(f"{WB}/calibration/b1.ch01.s1", json={"scores": {"voice": 9}}), 400)
    a = data(client.get(f"{WB}/arc"))
    assert [c["id"] for c in a["tension"]["chapters"]][0] == "b1.ch01" and a["threads"]["threads"] == []
    pre = data(client.post(f"{WB}/arc/tension", json={"chapter": "b1.ch02", "value": 9}))
    assert pre["applied"] is False and "affects 2 scene(s)" in pre["consequence"]
    done = data(client.post(f"{WB}/arc/tension", json={"chapter": "b1.ch02", "value": 9, "apply": True}))
    assert done["applied"] is True
    t = data(client.put(f"{WB}/arc/threads/key", json={"note": "the key", "setup": "b1.ch01.s1"}))
    assert t["unpaid"] == 1
    assert data(client.delete(f"{WB}/arc/threads/key"))["threads"] == []
    error(client.post(f"{WB}/arc/tension", json={"chapter": "b1.ch02", "value": 11}), 400)


def test_workbench_writes_wait_for_an_idle_series_but_reads_do_not(book, monkeypatch):
    gate, started = threading.Event(), threading.Event()

    class Slow(RuleLLM):
        def complete(self, role, messages, **options):
            started.set()
            gate.wait(30)
            return super().complete(role, messages, **options)

    monkeypatch.setattr(api, "make_llm", lambda project: Slow(qc_rules()))
    job = data(client.post(f"{B}/run", json={"until": "prose"}), 202)
    assert started.wait(30)
    try:
        error(client.put(f"{WB}/rules/no-purple", json=RULE), 409)
        error(client.put(f"{WB}/prompts/prose", json={"text": "x"}), 409)
        error(client.post(f"{WB}/arc/tension", json={"chapter": "b1.ch02", "value": 9, "apply": True}), 409)
        assert data(client.get(f"{WB}/rules")) and data(client.post(f"{WB}/arc/tension", json={"chapter": "b1.ch02", "value": 9}))["applied"] is False
    finally:
        gate.set()
    finish(job)
