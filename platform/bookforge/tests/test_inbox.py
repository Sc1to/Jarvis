"""The Inbox: what stops a stage, answered from the web page with the same code as the command line."""

import json
import shutil

import pytest
from typer.testing import CliRunner

import main
from bookforge import cli, inbox, ops
from bookforge.bible import store
from bookforge.bible.models import AuthorQuestion, Ledger
from bookforge.project import Project
from test_api import B, client, data, data_dir, error, finish  # noqa: F401  (data_dir is an autouse fixture)
from test_prose_qc import book  # noqa: F401

CONTRADICTION = dict(id="q1", question='These cannot both be true: "A" / "B"', why="A and B conflict", options=["Keep A", "Keep B"], type="contradiction", quotes=["A", "B"])
NAME = dict(id="q2", question='A name that is not in the cast: "Halloway"', why="not in the cast", options=["Use the cast's name"], type="unknown_name", quotes=["Foreman Halloway"])
THIN = dict(id="q3", question="What stands between Mara and the ferry?", why="empty middle", options=["a rival"], type="thin")


def seed(project, *questions):
    store.save_ledger(project, Ledger(events=[], questions=[AuthorQuestion(**q) for q in questions]))
    return project


def finding(stage, code, items, message="a hard finding", evidence=("a quoted line",), severity="hard"):
    return dict(stage=stage, code=code, severity=severity, message=message, items=items, evidence=list(evidence), accepted=False)


def put_findings(project, stage, findings):
    (project.book_dir / "validation").mkdir(parents=True, exist_ok=True)
    (project.book_dir / "validation" / f"{stage}.json").write_text(json.dumps({"stage": stage, "summary": {}, "findings": findings}), encoding="utf-8")


def test_the_inbox_lists_every_open_question_and_hard_finding_blocking_first_labelled_by_series_book_and_stage(book):
    seed(book, THIN, NAME, CONTRADICTION)
    put_findings(book, "chapters", [finding("chapters", "once_only_repeated", ["e4", "b2.ch03"]), finding("chapters", "weights_soft", ["x"], severity="soft")])
    got = data(client.get(f"{B}/inbox"))
    items = got["items"]
    assert [i["id"] for i in items[:2]] == ["question:q1", "question:q2"] and items[2]["stage"] == "chapters" and items[3]["id"] == "question:q3"
    assert [i["blocking"] for i in items] == [True, True, True, False]  # the thin question stops the ledger checkpoint but is not an audit finding
    first = items[0]
    assert (first["series"], first["book"], first["stage"], first["type"], first["status"]) == ("series", "b1", "ledger", "contradiction", "open")
    assert first["quotes"] == ["A", "B"] and first["options"] == ["Keep A", "Keep B"] and first["why"]
    assert {i["stage"] for i in items} == {"ledger", "chapters"} and "soft" not in json.dumps([i["type"] for i in items])
    assert got["summary"]["blocking"] == 3 and got["summary"]["open"] == 4 and got["summary"]["by_stage"] == {"ledger": 3, "chapters": 1}
    assert data(client.get(f"{B}/status"))["inbox"]["blocking"] == 3


def test_a_question_is_answered_edited_until_applied_and_then_refused(book):
    seed(book, CONTRADICTION)
    got = data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep A"}))
    assert [(i["status"], i["answer"]) for i in got["items"]] == [("answered", "Keep A")] and got["summary"]["blocking"] == 0 and got["summary"]["answered_waiting"] == 1
    again = data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep B, and say why"}))  # edit
    assert again["items"][0]["answer"] == "Keep B, and say why" and again["items"][0]["status"] == "answered"
    led = store.load_ledger(book)
    led.questions[0].applied = True  # a run applied it
    store.save_ledger(book, led)
    assert data(client.get(f"{B}/inbox"))["items"][0]["status"] == "applied"
    error(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "too late"}), 400)
    error(client.post(f"{B}/inbox/dismiss", json={"id": "question:q1"}), 400)


def test_a_dismissal_keeps_its_reason_and_counts_toward_the_rate_of_its_type(book):
    seed(book, CONTRADICTION, NAME, THIN)
    data(client.post(f"{B}/inbox/dismiss", json={"id": "question:q2", "reason": "  Halloway is the new foreman, not a mistake "}))
    data(client.post(f"{B}/inbox/dismiss", json={"id": "question:q3"}))
    got = data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep A"}))
    stats = got["stats"]
    assert stats["unknown_name"] == {"raised": 1, "answered": 0, "dismissed": 1, "reasons": ["Halloway is the new foreman, not a mistake"], "dismissal_rate": 1.0}
    assert stats["contradiction"]["answered"] == 1 and stats["contradiction"]["dismissal_rate"] == 0.0 and stats["thin"]["reasons"] == []
    assert [i["status"] for i in got["items"]] == ["answered", "dismissed", "dismissed"] and got["summary"]["open"] == 0


def test_a_hard_finding_of_any_stage_is_answered_with_an_instruction_or_dismissed_as_a_false_alarm(book):
    put_findings(book, "acts", [finding("acts", "sizing_reason_mismatch", ["b2.act1"])])
    put_findings(book, "scenes", [finding("scenes", "pov_not_in_text", ["b2.ch06.s1", "silas-thorne"])])
    items = data(client.get(f"{B}/inbox"))["items"]
    assert [i["stage"] for i in items] == ["acts", "scenes"] and all(i["kind"] == "finding" and i["blocking"] for i in items)
    data(client.post(f"{B}/inbox/answer", json={"id": items[0]["id"], "answer": "the count is right; fix the text"}))
    note = (book.book_dir / "notes" / "acts.md").read_text()
    assert "sizing_reason_mismatch [b2.act1]: the count is right; fix the text" in note  # the next run of the stage reads it
    got = data(client.post(f"{B}/inbox/dismiss", json={"id": items[1]["id"], "reason": "she is the viewpoint, named by pronoun"}))
    assert [(i["stage"], i["status"]) for i in got["items"]] == [("acts", "open"), ("scenes", "dismissed")] and got["summary"]["blocking"] == 1
    assert got["stats"]["pov_not_in_text"]["reasons"] == ["she is the viewpoint, named by pronoun"] and got["items"][1]["dismiss_reason"]
    error(client.post(f"{B}/inbox/answer", json={"id": "finding:nope", "answer": "x"}), 404)
    error(client.post(f"{B}/inbox/answer", json={"id": "nonsense", "answer": "x"}), 422)


def test_approving_a_checkpoint_as_it_is_needs_an_explicit_skip_when_blocking_items_remain(book):
    seed(book, CONTRADICTION, THIN)
    book.state.checkpoints["ledger"].status = "waiting"
    book.save_state()
    refused = error(client.post(f"{B}/approve/ledger"), 409)
    assert "would skip 2 open item(s)" in refused["detail"] and "contradiction" in refused["detail"] and "skip_open" in refused["detail"]
    assert data(client.get(f"{B}/status"))["checkpoints"]["ledger"] == "waiting"
    done = data(client.post(f"{B}/approve/ledger", json={"skip_open": True}))
    assert done == {"checkpoint": "ledger", "status": "approved"}


def test_a_checkpoint_with_nothing_open_for_its_stages_approves_without_ceremony(book):
    seed(book)  # no questions
    book.state.checkpoints["ledger"].status = "waiting"
    book.save_state()
    assert data(client.post(f"{B}/approve/ledger"))["status"] == "approved"


def test_the_inbox_page_runs_again_with_the_ordinary_run_and_answered_items_wait_for_it(book):
    seed(book, CONTRADICTION)
    data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep A"}))
    assert data(client.get(f"{B}/inbox"))["summary"] == {"open": 0, "blocking": 0, "answered_waiting": 1, "by_stage": {}}
    job = data(client.post(f"{B}/run", json={"until": "ledger"}), 202)  # the button posts this: the same call as `run` on the command line
    assert finish(job)["status"] in ("done", "failed")


def test_the_web_page_and_the_command_line_write_the_same_ledger_file(book, tmp_path, monkeypatch):
    seed(book, CONTRADICTION, NAME, THIN)
    twin = tmp_path / "twin"
    shutil.copytree(book.root, twin / "series")
    runner = CliRunner()
    # the command line on the copy
    assert runner.invoke(cli.app, ["ledger-answer", str(twin / "series"), "q1", "Keep A, drop B"]).exit_code == 0
    assert runner.invoke(cli.app, ["ledger-dismiss", str(twin / "series"), "q2", "--reason", "new foreman"]).exit_code == 0
    # the web page on the original
    data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep A, drop B"}))
    data(client.post(f"{B}/inbox/dismiss", json={"id": "question:q2", "reason": "new foreman"}))
    assert (book.book_dir / "ledger.yaml").read_bytes() == (twin / "series" / "books" / "b1" / "ledger.yaml").read_bytes()
    # an edit through the page equals the same edit through the command line
    runner.invoke(cli.app, ["ledger-answer", str(twin / "series"), "q1", "Keep B instead"])
    data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep B instead"}))
    assert (book.book_dir / "ledger.yaml").read_bytes() == (twin / "series" / "books" / "b1" / "ledger.yaml").read_bytes()


def test_a_run_that_stops_for_your_answers_sends_a_notification_that_counts_them_and_links_to_the_inbox(book, monkeypatch):
    from bookforge import api
    sent = []
    monkeypatch.setattr(api, "push_sender", lambda **kw: sent.append(kw))
    client.post("/api/push/subscribe", json={"endpoint": "https://push.example/x", "keys": {"p256dh": "k", "auth": "a"}})
    seed(book, CONTRADICTION, NAME)
    put_findings(book, "chapters", [finding("chapters", "end_state_overreach", ["b2.ch10"])])
    from bookforge.jobs import Job
    api.jobs.on_finish(Job(id="1", series="series", book="b1", kind="run", status="done", result={"stopped": "checkpoint", "detail": "reached the 'ledger' checkpoint"}))
    p = json.loads(sent[0]["data"])
    assert p["title"] == "Bookforge: waiting for your answers" and "3 blocking item(s) in the Inbox" in p["body"] and "2 in ledger" in p["body"] and "1 in chapters" in p["body"]
    assert p["url"] == "/bookforge/#/series/series/b1/inbox"
