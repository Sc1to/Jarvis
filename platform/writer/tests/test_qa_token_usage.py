"""QA gets a scene-scoped ledger and QA-driven retries send only a targeted fix request."""

import json
import os
import sys

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

from prompt_blocks import qa_ledger_for_scene

LEDGER = json.dumps({
    "a": {"name": "Clara Voss", "book_facts": {"eyes": "grey"}, "eventLog": [{"n": i} for i in range(30)]},
    "b": {"name": "Willem Decker", "book_facts": {"eyes": "brown"}, "eventLog": [{"n": 1}]},
    "c": {"name": "Porter", "book_facts": {"hat": "red"}, "eventLog": []},
})


def test_qa_ledger_includes_only_mentioned_entities_plus_roster():
    out = qa_ledger_for_scene(LEDGER, "Clara waits for the train.", max_events=5)
    body, roster = out.split("\n\nOther known entities")
    ledger = json.loads(body)
    assert list(ledger) == ["a"]
    assert ledger["a"]["eventLog"][0] == {"omitted_earlier": 25}
    assert len(ledger["a"]["eventLog"]) == 6
    assert "Willem Decker" in roster and "Porter" in roster
    assert "grey" in body and "brown" not in out and "red" not in out


def test_qa_ledger_all_mentioned_has_no_roster():
    out = qa_ledger_for_scene(LEDGER, "Clara, Willem and the Porter.")
    assert "Other known entities" not in out


def test_qa_ledger_empty_passthrough():
    assert qa_ledger_for_scene("{}", "anything") == "{}"


def test_retry_is_targeted_fix_without_ledger(tmp_path, monkeypatch):
    import asyncio
    from git import Repo
    import db
    from routes import phase3

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    settings = {f"agent_{a}_{k}": v for a in ("writer_agent", "qa_agent", "bible_agent")
                for k, v in (("provider", "p"), ("model", "m"))}
    settings["qa_retry_manual"] = "true"
    monkeypatch.setattr(db, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(db, "append_job_log", lambda *a: None)

    book = tmp_path / "book1"
    (book / "tier4").mkdir(parents=True)
    (book / "tier4" / "chapter_01.md").write_text("### Scene 1 — b")
    (book / "bible.json").write_text(json.dumps({"ledger": {"x": {"name": "Zebulon", "book_facts": {"secret": "LEDGERMARK"}}}}))
    Repo.init(book)

    fail = {"pass": False, "notes": "n", "issues": [
        {"type": "entity", "description": "Wrong eyes", "quote": "grey eyes", "fix": "Eyes are brown", "severity": "error"}]}
    qa_results = [fail, {"pass": True, "issues": [], "notes": ""}]
    writer_msgs = []

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False, **kw):
        if system == phase3.SCENE_PLANNER_SYSTEM:
            return json.dumps([{"scene": 1, "brief": "Zebulon arrives", "entry_state": "", "exit_state": "locked"}])
        if system == phase3.QA_SYSTEM:
            return json.dumps(qa_results.pop(0))
        writer_msgs.append((system, messages[-1]["content"]))
        return "Zebulon had grey eyes." if len(writer_msgs) == 1 else "Zebulon had brown eyes."

    monkeypatch.setattr(phase3, "_call", fake_call)
    q: asyncio.Queue = asyncio.Queue()
    asyncio.run(phase3._write_chapter_task("book1", 1, "local", "job", q))

    assert len(writer_msgs) == 2
    first_system, first_msg = writer_msgs[0]
    fix_system, fix_msg = writer_msgs[1]
    assert "LEDGERMARK" in first_msg
    assert fix_system == phase3.FIX_SYSTEM
    assert "LEDGERMARK" not in fix_msg
    assert "Eyes are brown" in fix_msg and "Zebulon had grey eyes." in fix_msg
    assert "locked" in fix_msg
    assert "Zebulon had brown eyes." in (book / "chapter_01.md").read_text()


def test_chapter_usage_sums_per_scene_and_agent(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db, "_local", type("L", (), {})())
    db.log_llm_usage("writer_agent", input_tokens=100, output_tokens=10, book_id="b", chapter=1, scene=1)
    db.log_llm_usage("writer_agent", input_tokens=30, output_tokens=5, book_id="b", chapter=1, scene=1)
    db.log_llm_usage("qa_agent", input_tokens=50, output_tokens=2, book_id="b", chapter=1, scene=1)
    db.log_llm_usage("bible_agent", input_tokens=7, output_tokens=1, book_id="b", chapter=1)
    db.log_llm_usage("writer_agent", input_tokens=999, output_tokens=9, book_id="b", chapter=2, scene=1)
    u = db.get_chapter_usage("b", 1)
    s1 = u["scenes"][1]
    assert (s1["input"], s1["output"], s1["calls"]) == (180, 17, 3)
    assert s1["by_agent"]["writer_agent"] == {"input": 130, "output": 15, "calls": 2}
    assert u["chapter"]["input"] == 7 and list(u["scenes"]) == [1]
