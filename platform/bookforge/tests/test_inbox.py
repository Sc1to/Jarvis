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
from bookforge.remedies.registry import CHECKS_VERSION
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
    (project.book_dir / "validation" / f"{stage}.json").write_text(json.dumps({"stage": stage, "checks_version": CHECKS_VERSION, "summary": {}, "findings": findings}), encoding="utf-8")


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
    put_findings(book, "scenes", [finding("scenes", "scene_event_not_in_chapter", ["b2.ch06.s1", "e4"])])
    items = data(client.get(f"{B}/inbox"))["items"]
    assert [i["stage"] for i in items] == ["acts", "scenes"] and all(i["kind"] == "finding" and i["blocking"] for i in items)
    data(client.post(f"{B}/inbox/answer", json={"id": items[0]["id"], "answer": "the count is right; fix the text"}))
    note = (book.book_dir / "notes" / "acts.md").read_text()
    assert "sizing_reason_mismatch [b2.act1]: the count is right; fix the text" in note  # the next run of the stage reads it
    got = data(client.post(f"{B}/inbox/dismiss", json={"id": items[1]["id"], "reason": "she is the viewpoint, named by pronoun"}))
    assert [(i["stage"], i["status"]) for i in got["items"]] == [("acts", "answered"), ("scenes", "dismissed")] and got["summary"]["blocking"] == 0 and got["summary"]["needs_run"]  # your instruction waits for the next run: not blocking, and a run is due
    assert got["stats"]["scene_event_not_in_chapter"]["reasons"] == ["she is the viewpoint, named by pronoun"] and got["items"][1]["dismiss_reason"]
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
    assert data(client.get(f"{B}/inbox"))["summary"] == {"open": 0, "blocking": 0, "answered_waiting": 1, "resolved": 0, "healed": 0, "outdated": 0, "needs_run": True, "by_stage": {}}
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
    put_findings(book, "chapters", [finding("chapters", "event_not_covered", ["e10"])])
    from bookforge.jobs import Job
    api.jobs.on_finish(Job(id="1", series="series", book="b1", kind="run", status="done", result={"stopped": "checkpoint", "detail": "reached the 'ledger' checkpoint"}))
    p = json.loads(sent[0]["data"])
    assert p["title"] == "Bookforge: waiting for your answers" and "3 blocking item(s) in the Inbox" in p["body"] and "2 in ledger" in p["body"] and "1 in chapters" in p["body"]
    assert p["url"] == "/bookforge/#/series/series/b1/inbox"


SENT_A = "Mara forces her way into the ferry and finds a data drive that names Corso as a smuggler."


def _uncovered(book, sentence):
    (book.book_dir / "synopsis.md").write_text("# Synopsis\n\nMara is a salvage pilot who finds a derelict ferry in the harbor yard.\n\n" + sentence + "\n", encoding="utf-8")
    put_findings(book, "ledger", [finding("ledger", "sentence_not_covered", [sentence[:60]], message=f'this sentence of the synopsis is quoted by no event: "{sentence}".', evidence=(sentence[:140],))])
    (book.book_dir / "validation" / "ledger_attempt.json").write_text(json.dumps({"events": [
        dict(id="e2", text="Mara forces her way into the ferry", excerpt="Mara is a salvage pilot who finds a derelict ferry in the harbor yard", once_only=True, source="synopsis")]}), encoding="utf-8")


def test_a_failed_ledger_attempt_leaves_its_events_for_the_suggestions(book, monkeypatch):
    from conftest import RuleLLM
    from bookforge import api
    _uncovered(book, SENT_A)
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("A sentence of a story synopsis has no event", json.dumps(
        {"outcome": "change", "change": "Mara finds a drive naming Corso as a smuggler", "words": "finds a data drive that names Corso", "reason": "a discovery"}))]))
    job = finish(data(client.post(f"{B}/inbox/propose"), 202))
    assert job["status"] == "done" and job["result"] == {"proposals": 1, "no_suggestion": {}}
    item = next(i for i in data(client.get(f"{B}/inbox"))["items"] if i["kind"] == "finding")
    p = item["proposal"]
    assert p["outcome"] == "widen" or p["outcome"] == "new_event"  # e2 tells "Mara forces her way into the ferry": which step answers depends on the words; either way a suggestion, not an action
    assert p["applied"] is False and p["mode"] == "shadow" and p["answer"]


def test_what_you_do_with_a_suggestion_is_recorded_and_counted(book, monkeypatch):
    from bookforge import resolve
    _uncovered(book, SENT_A)
    resolve.save(book, {"finding:ledger:sentence_not_covered:" + SENT_A[:60]: {"outcome": "waive", "answer": "No event needed: description.", "rationale": "r", "label": "tool housekeeping"}})
    item = data(client.get(f"{B}/inbox"))["items"][0]
    assert item["proposal"]["outcome"] == "waive"
    data(client.post(f"{B}/inbox/answer", json={"id": item["id"], "answer": "No event needed: description."}))  # the suggestion, as it was
    data(client.post(f"{B}/inbox/answer", json={"id": item["id"], "answer": "Actually give it an event"}))  # edited
    got = data(client.post(f"{B}/inbox/dismiss", json={"id": item["id"]}))  # overridden
    assert got["proposal_stats"]["waive"] == {"proposed": 3, "accepted": 1, "edited": 1, "overridden": 1, "applied": 0, "undone": 0, "override_rate": 0.67}


def test_assist_mode_settles_housekeeping_marks_it_resolved_by_the_tool_and_undo_takes_it_back(book, monkeypatch):
    from conftest import RuleLLM
    from bookforge import answers, api
    sentence = "The harbor is cold and grey in the early morning light over the yard."
    _uncovered(book, sentence)
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("A sentence of a story synopsis has no event", json.dumps(
        {"outcome": "commentary", "change": "", "words": "", "reason": "it only describes the harbor"}))]))
    assert data(client.put(f"{B}/inbox/mode", json={"mode": "assist"}))["mode"] == "assist"
    error(client.put(f"{B}/inbox/mode", json={"mode": "magic"}), 400)
    finish(data(client.post(f"{B}/inbox/propose"), 202))
    got = data(client.get(f"{B}/inbox"))
    item = got["items"][0]
    assert item["status"] == "resolved" and not item["blocking"] and item["proposal"]["applied"] and item["proposal"]["outcome"] == "waive"
    assert got["summary"]["open"] == 0 and got["summary"]["resolved"] == 1 and got["summary"]["blocking"] == 0
    assert answers.load(book)["waived"] == [{"quote": sentence, "reason": "it only describes the harbor", "decided_by": "tool"}]
    after = data(client.post(f"{B}/inbox/undo", json={"id": item["id"]}))
    back = after["items"][0]
    assert back["status"] == "open" and back["blocking"] and not back["proposal"]["applied"] and after["summary"]["resolved"] == 0
    assert answers.load(book)["waived"] == [] and answers.load(book)["undone"] == [sentence]
    finish(data(client.post(f"{B}/inbox/propose"), 202))  # the tool does not decide that sentence again
    assert data(client.get(f"{B}/inbox"))["items"][0]["status"] == "open"
    error(client.post(f"{B}/inbox/undo", json={"id": item["id"]}), 400)
    stats = after["proposal_stats"]["waive"]
    assert stats["applied"] == 1 and stats["undone"] == 1 and stats["override_rate"] == 1.0


def test_shadow_mode_applies_nothing(book, monkeypatch):
    from conftest import RuleLLM
    from bookforge import answers, api
    _uncovered(book, "The harbor is cold and grey in the early morning light over the yard.")
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("A sentence of a story synopsis has no event", json.dumps(
        {"outcome": "commentary", "change": "", "words": "", "reason": "description"}))]))
    assert answers.load(book)["mode"] == "shadow"
    finish(data(client.post(f"{B}/inbox/propose"), 202))
    item = data(client.get(f"{B}/inbox"))["items"][0]
    assert item["status"] == "open" and item["blocking"] and not item["proposal"]["applied"] and answers.load(book)["waived"] == []


def test_a_question_about_the_world_gets_a_proposal_by_the_books_policy_and_a_story_question_gets_none(book, monkeypatch):
    from conftest import RuleLLM
    from bookforge import api
    world = dict(id="q1", question="The plasma cutter is used but never explained", why="no one says how it works", options=[], type="unestablished_object", quotes=["armed with a plasma cutter"])
    story = dict(id="q2", question="Why does Mara yield to Corso?", why="nothing forces her", options=["She is in debt"], type="motive_gap", quotes=["Mara yields"])
    seed(book, world, story)

    def classify(messages):
        return json.dumps({"kind": "world_fact", "fact": "How does a plasma cutter work?", "reason": "a technology"} if "plasma cutter" in messages[-1]["content"]
                          else {"kind": "story_decision", "fact": "", "reason": "a choice"})
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("Decide whether answering it needs a fact about the WORLD", classify),
                                                                  ("A story needs a fact about its world", json.dumps({"rule": "It cuts by a confined arc of ionised gas.", "basis": "real plasma cutters work this way",
                                                                                                                        "changes_what_happens": False, "reason": "a routine"}))]))
    got = data(client.put(f"{B}/inbox/policy", json={"world_facts": "extrapolate"}))
    assert got["policy"] == {"world_facts": "extrapolate", "invention": "minor", "source": "you"}
    error(client.put(f"{B}/inbox/policy", json={"world_facts": "dream"}), 400)
    finish(data(client.post(f"{B}/inbox/propose"), 202))
    items = {i["id"]: i for i in data(client.get(f"{B}/inbox"))["items"]}
    p = items["question:q1"]["proposal"]
    assert p["outcome"] == "world_fact" and p["label"] == "extrapolated" and "ionised gas" in p["answer"] and p["applied"] is False and p["size"] == "minor"
    assert items["question:q2"]["proposal"] is None  # a story decision is yours: its suggested options are all there is
    data(client.put(f"{B}/inbox/mode", json={"mode": "assist"}))
    finish(data(client.post(f"{B}/inbox/propose"), 202))
    assert not {i["id"]: i for i in data(client.get(f"{B}/inbox"))["items"]}["question:q1"]["proposal"]["applied"]  # even in assist mode a world fact is never applied by the tool


def test_an_answer_that_invents_something_is_recorded_as_canon_and_can_be_undone_from_the_page(book, monkeypatch):
    from conftest import RuleLLM
    from bookforge import api
    from bookforge.research.notes import approved_decisions
    seed(book, CONTRADICTION)
    reply = json.dumps({"entities": [{"name": "Ash Token", "kind": "object", "facts": ["a steel token Eli copies the data onto"]}], "rules": ["Dockers use the Ash Token to open the lock-ups."]})
    monkeypatch.setattr(api, "make_llm", lambda project: RuleLLM([("An author answered a question about their story", reply)]))
    answer = "Eli copies the data onto a steel token called the Ash Token. Dockers use the Ash Token to open the lock-ups."
    got = data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": answer}))
    [entry] = got["canon"]
    assert entry["entities"] == ["ash-token"] and entry["item"] == "question:q1" and len(approved_decisions(book)) == 1
    assert "ash-token" in {e.id for e in store.load_constants(book).entities}
    gone = data(client.post(f"{B}/inbox/canon/undo", json={"id": entry["id"]}))
    assert gone["canon"] == [] and "ash-token" not in {e.id for e in store.load_constants(book).entities} and approved_decisions(book) == []
    error(client.post(f"{B}/inbox/canon/undo", json={"id": entry["id"]}), 400)  # already undone


def test_an_answer_with_no_model_at_hand_is_still_recorded(book, monkeypatch):
    from bookforge import api

    def no_model(project):
        raise RuntimeError("the model server is gone")
    monkeypatch.setattr(api, "make_llm", no_model)
    seed(book, CONTRADICTION)
    got = data(client.post(f"{B}/inbox/answer", json={"id": "question:q1", "answer": "Keep A"}))
    assert got["items"][0]["status"] == "answered" and got["canon"] == []


def test_auto_mode_and_re_enabling_an_outcome_work_from_the_page(book):
    from bookforge import resolve
    assert data(client.put(f"{B}/inbox/mode", json={"mode": "auto"}))["mode"] == "auto"
    path = resolve.path(book).with_name("decisions.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(dict(item="x", outcome="waive", label="l", mode="assist", verdict=v, at=f"2026-11-15T10:0{i}:00+00:00")) + "\n"
                            for i, v in enumerate(["applied", "applied", "applied", "undone", "undone", "undone"])), encoding="utf-8")
    got = data(client.get(f"{B}/inbox"))
    assert list(got["demoted"]) == ["waive"] and got["demoted"]["waive"]["rate"] == 1.0
    back = data(client.post(f"{B}/inbox/reenable", json={"outcome": "waive"}))
    assert back["demoted"] == {}


def test_answering_a_finding_shows_it_answered_not_blocking_and_a_run_is_due_until_the_run_reads_it(book):
    from bookforge import inbox
    put_findings(book, "ledger", [finding("ledger", "sentence_not_covered", ["A sentence that has no event of its own here"])])
    first = data(client.get(f"{B}/inbox"))
    assert first["summary"]["blocking"] == 1 and not first["summary"]["needs_run"]
    got = data(client.post(f"{B}/inbox/answer", json={"id": first["items"][0]["id"], "answer": "Add an event for it"}))
    item = got["items"][0]
    assert (item["status"], item["answer"], item["blocking"]) == ("answered", "Add an event for it", False)
    assert got["summary"]["blocking"] == 0 and got["summary"]["answered_waiting"] == 1 and got["summary"]["open"] == 0 and got["summary"]["needs_run"]
    inbox.clear_answered(book)  # what a run does when it starts: it has read the instruction
    assert data(client.get(f"{B}/inbox"))["items"][0]["status"] == "open"  # the finding still holds, so it is open again


def test_a_stage_that_failed_needs_a_run_even_when_everything_was_dismissed(book):
    from bookforge.state import Item
    put_findings(book, "ledger", [finding("ledger", "sentence_not_covered", ["Another sentence with no event at all here"])])
    item = data(client.get(f"{B}/inbox"))["items"][0]
    book.state.set_layer_status("ledger", "flagged", note="still has problems")
    book.save_state()
    got = data(client.post(f"{B}/inbox/dismiss", json={"id": item["id"], "reason": "description"}))
    assert got["summary"]["blocking"] == 0 and got["summary"]["needs_run"]  # nothing left to answer, but the stage has to run again


def test_accepting_the_tools_suggestion_waives_the_sentence_without_writing_an_instruction(book):
    from bookforge import answers, resolve
    sentence = "The harbor is cold and grey in the early morning light over the yard."
    _uncovered(book, sentence)
    iid = "finding:ledger:sentence_not_covered:" + sentence[:60]
    resolve.save(book, {iid: {"outcome": "waive", "answer": "No event needed: description.", "rationale": "it only describes", "label": "tool housekeeping", "quote": sentence, "applied": False, "mode": "shadow", "decided_by": "tool"}})
    got = data(client.post(f"{B}/inbox/accept", json={"id": iid}))
    item = got["items"][0]
    assert item["status"] == "answered" and got["summary"]["blocking"] == 0 and got["summary"]["needs_run"] and got["proposal_stats"]["waive"]["accepted"] == 1
    assert answers.load(book)["waived"] == [{"quote": sentence, "reason": "it only describes", "decided_by": "you"}]
    error(client.post(f"{B}/inbox/accept", json={"id": "finding:nope"}), 400)


def test_what_the_tool_corrected_by_itself_is_listed_as_fixed_automatically_and_never_counts_or_blocks(book):
    from bookforge import healing
    seed(book, THIN)
    healing.begin(book, "chapters")
    healing.note(book, "chapters", "b2.act4", ["b2.ch13 listed e16, which belongs to another act; taken out so it is told only there"])
    healing.note(book, "scenes", "b2.ch01", ["scene ids renumbered"])  # another stage's pending notes are saved only by that stage's commit
    healing.commit(book, "chapters")
    got = data(client.get(f"{B}/inbox"))
    healed = [i for i in got["items"] if i["kind"] == "healed"]
    assert [(i["stage"], i["status"], i["blocking"]) for i in healed] == [("chapters", "healed", False)] and "e16" in healed[0]["title"]
    assert got["summary"]["open"] == 1 and got["summary"]["blocking"] == 0 and got["summary"]["healed"] == 1  # only the thin question is open
    assert inbox.blocking_for_checkpoint(book, "structure") == []  # approving never has to skip it
    assert all(i["kind"] != "healed" for i in inbox.collect(book, include_done=False) if i["status"] == "healed")


def test_a_slip_that_comes_back_in_the_next_run_is_open_but_still_not_blocking_and_a_clean_run_clears_the_list(book):
    from bookforge import healing
    note = "b2.ch13 listed e16, which belongs to another act; taken out so it is told only there"
    for _ in range(2):
        healing.begin(book, "chapters")
        healing.note(book, "chapters", "b2.act4", [note])
        healing.commit(book, "chapters")
    item = next(i for i in inbox.collect(book) if i["kind"] == "healed")
    assert item["repeated"] and item["status"] == "open" and not item["blocking"]
    assert inbox.summary(book)["blocking"] == 0 and inbox.summary(book)["needs_run"] is False
    healing.begin(book, "chapters")
    healing.commit(book, "chapters")  # the next run needed no correction
    assert [i for i in inbox.collect(book) if i["kind"] == "healed"] == []


def test_a_failed_attempt_leaves_no_note_and_a_retry_of_the_same_piece_replaces_its_notes(book):
    from bookforge import healing
    healing.begin(book, "scenes")
    healing.note(book, "scenes", "b2.ch01", ["first attempt slip"])
    healing.note(book, "scenes", "b2.ch01", ["second attempt slip"])
    healing.begin(book, "scenes")  # the layer failed and starts again: the old attempt is forgotten
    healing.note(book, "scenes", "b2.ch01", ["scene ids renumbered"])
    assert healing.commit(book, "scenes") == ["scene ids renumbered"]


def test_a_ledger_run_s_soft_auto_repaired_findings_are_listed_as_fixed_automatically(book):
    seed(book)
    put_findings(book, "ledger", [finding("ledger", "auto_repaired", [], message="e3 moved after e2", severity="soft")])
    item = next(i for i in inbox.collect(book) if i["kind"] == "healed")
    assert item["stage"] == "ledger" and item["status"] == "healed" and not item["blocking"] and item["title"] == "e3 moved after e2"


def test_the_suggestion_job_says_which_open_items_it_has_nothing_to_suggest_for(book, monkeypatch):
    seed(book)
    put_findings(book, "chapters", [finding("chapters", "end_state_overreach", ["b2.ch16", "e22"])])
    job = finish(data(client.post(f"{B}/inbox/propose"), 202))
    assert job["status"] == "done" and job["result"]["proposals"] == 0 and job["result"]["no_suggestion"] == {"end_state_overreach": 1}


def test_thirty_six_findings_of_one_cause_are_one_item_that_answering_or_dismissing_settles_together(book):
    seed(book)
    many = [finding("scenes", "pov_not_in_text", [f"b2.ch{i:02d}.s1", "eli"], message="pov slip") for i in range(1, 7)] + [finding("scenes", "state_regression", ["other-track", "b2.ch03.s1"])]
    put_findings(book, "scenes", many)
    got = data(client.get(f"{B}/inbox"))
    items = [i for i in got["items"] if i["stage"] == "scenes"]
    assert len(items) == 7  # six different scenes: nothing in common to group by
    same = [finding("scenes", "state_regression", ["containment-seal-status", f"b2.ch{i:02d}.s1"], message="goes back") for i in range(11, 15)] + [finding("scenes", "state_regression", ["data-drive", "b2.ch15.s1"])]
    put_findings(book, "scenes", same)
    got = data(client.get(f"{B}/inbox"))
    items = got["items"]
    lead = next(i for i in items if i.get("group"))
    assert lead["group"]["count"] == 4 and "and 3 more like it" in lead["title"] and len(items) == 2 and got["summary"]["open"] == 2
    data(client.post(f"{B}/inbox/dismiss", json={"id": lead["id"], "reason": "the seal is breached and hardened on purpose"}))
    after = data(client.get(f"{B}/inbox"))
    assert [i["status"] for i in after["items"] if i["status"] == "open"] == ["open"]  # only the other track's item is left


def put_unversioned(project, stage, findings):
    """Findings as an older run saved them: no checks_version."""
    (project.book_dir / "validation").mkdir(parents=True, exist_ok=True)
    (project.book_dir / "validation" / f"{stage}.json").write_text(json.dumps({"stage": stage, "summary": {}, "findings": findings}), encoding="utf-8")


def b2_flood():
    two = [finding("scenes", "two_places_at_once", [f"b2.ch01.s1", f"b2.ch{i:02d}.s1"]) for i in range(2, 22)]
    regress = [finding("scenes", "state_regression", ["containment-seal-status", f"b2.ch{i:02d}.s1"]) for i in (12, 14, 16)] + [finding("scenes", "state_regression", ["data-drive-status", "b2.ch15.s1"])]
    patterns = [finding("scenes", "action_pattern_repeated", [f"b2.ch{i:02d}" for i in (2, 5, 6)]), finding("scenes", "event_repeated", ["b2.ch15", "b2.ch18", "b2.ch20"])]
    return two + regress + patterns


def test_findings_an_older_version_of_the_checks_saved_never_block_and_the_page_offers_run_again(book):
    seed(book)
    put_unversioned(book, "scenes", b2_flood())  # the b2 Inbox after pulling phase 5 without running the stage again
    got = data(client.get(f"{B}/inbox"))
    items = got["items"]
    assert items and all(i["status"] == "outdated" and not i["blocking"] for i in items)
    assert got["summary"]["blocking"] == 0 and got["summary"]["open"] == 0 and got["summary"]["needs_run"] is True and got["summary"]["outdated"] >= 1
    lead = next(i for i in items if i["type"] == "two_places_at_once")
    assert lead["group"]["count"] == 20 and "older version of the checks" in lead["why"]  # 20 scene pairs of one cause: one item
    assert inbox.blocking_for_checkpoint(book, "structure") == []


def test_the_same_findings_saved_by_the_current_checks_keep_structural_ones_blocking_and_show_the_rest_as_warnings(book):
    seed(book)
    put_findings(book, "scenes", [finding("scenes", "chapter_event_not_in_scenes", ["b2.ch03", "e5"]), finding("scenes", "action_pattern_repeated", ["b2.ch02", "b2.ch05"]),
                                  finding("scenes", "pov_not_in_text", ["b2.ch06.s1", "silas-thorne"])])
    items = {i["type"]: i for i in data(client.get(f"{B}/inbox"))["items"]}
    assert items["chapter_event_not_in_scenes"]["blocking"] and not items["chapter_event_not_in_scenes"].get("warning")
    assert not items["action_pattern_repeated"]["blocking"] and items["action_pattern_repeated"]["warning"]
    assert not items["pov_not_in_text"]["blocking"] and items["pov_not_in_text"]["warning"]
    summary = data(client.get(f"{B}/inbox"))["summary"]
    assert summary["blocking"] == 1
    assert [i["type"] for i in inbox.blocking_for_checkpoint(book, "structure")] == ["chapter_event_not_in_scenes"]  # a warning never has to be skipped


def test_a_scene_pair_two_places_finding_is_retired_even_when_saved_by_the_current_version_and_a_track_one_is_not(book):
    seed(book)
    put_findings(book, "scenes", [finding("scenes", "two_places_at_once", ["b2.ch01.s1", "b2.ch04.s1"]), finding("scenes", "two_places_at_once", ["eli-vance", "b2.ch01.s1"])])
    by_items = {tuple(i["items"]): i for i in data(client.get(f"{B}/inbox"))["items"]}
    assert by_items[("b2.ch01.s1", "b2.ch04.s1")]["status"] == "outdated"
    assert by_items[("eli-vance", "b2.ch01.s1")]["status"] == "open"  # a track contradiction: still a decision (a warning below the ledger stage)


def test_a_stage_run_stamps_the_findings_with_the_current_checks_version(project):
    from bookforge.remedies.registry import CHECKS_VERSION
    from bookforge.validators import findings as F, store as findings_store
    findings_store.save(project, "scenes", [F.soft("scenes", "tic_word", "x", [])])
    assert findings_store.load(project, "scenes")["checks_version"] == CHECKS_VERSION and isinstance(CHECKS_VERSION, int)
