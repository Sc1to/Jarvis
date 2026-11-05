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
from qc_fakes import EXTRACT, JUDGE, extractor, judge
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
