"""Length targets, standing notes, condensed Writer context, pause/resume and regenerate-after."""

import asyncio
import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from git import Repo

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"
QA_PASS = {"pass": True, "issues": [], "notes": "fine"}


# ── Prompt blocks ──────────────────────────────────────────────────────────────

def test_strip_event_logs_keeps_state_drops_history():
    from prompt_blocks import strip_event_logs
    ledger = {"CHAR_001": {"name": "Mary", "book_facts": {"task": "find the ledger"}, "eventLog": [{"description": "x"}]}}
    out = json.loads(strip_event_logs(json.dumps(ledger)))
    assert out == {"CHAR_001": {"name": "Mary", "book_facts": {"task": "find the ledger"}}}


def test_condense_prior_scenes_summarises_all_but_previous():
    from prompt_blocks import condense_prior_scenes
    text = condense_prior_scenes(
        [(1, "Scene one prose " * 50), (2, "Scene two prose.")],
        {1: "Mary gets the task. Ends with: she has the key"},
    )
    assert "- Scene 1: Mary gets the task. Ends with: she has the key" in text
    assert "Scene one prose" not in text
    assert "[Previous scene — Scene 2]\nScene two prose." in text
    assert condense_prior_scenes([]) == "None yet."


def test_cap_event_logs_truncates_history_keeps_state():
    from prompt_blocks import cap_event_logs
    ledger = {
        "CHAR_001": {
            "name": "Mary",
            "book_facts": {"task": "find the ledger"},
            "eventLog": [{"description": f"event {i}"} for i in range(25)],
        },
        "CHAR_002": {"name": "Tom", "eventLog": [{"description": "only one"}]},
    }
    out = json.loads(cap_event_logs(json.dumps(ledger), max_events=20))
    assert out["CHAR_001"]["book_facts"] == {"task": "find the ledger"}
    assert out["CHAR_001"]["eventLog"][0] == {"omitted_earlier": 5}
    assert len(out["CHAR_001"]["eventLog"]) == 21  # marker + last 20
    assert out["CHAR_001"]["eventLog"][-1] == {"description": "event 24"}
    # under the cap — untouched, no marker added
    assert out["CHAR_002"]["eventLog"] == [{"description": "only one"}]


def test_cap_event_logs_handles_missing_or_empty_input():
    from prompt_blocks import cap_event_logs
    assert cap_event_logs("") == ""
    assert cap_event_logs("{}") == "{}"
    assert cap_event_logs("null") == "null"
    assert cap_event_logs("not json") == "not json"


def test_writer_context_has_notes_before_contract_with_length():
    from prompt_blocks import assemble_writer_context
    ctx = assemble_writer_context(
        north_star="", writing_prefs="", ledger_json="{}", prior_text="None yet.",
        chapter=1, scene_num=2, brief="b", entry_state="", exit_state="",
        author_notes="Never mention the key again.", word_target=500, word_limit=625,
    )
    assert ctx.index("## Author standing notes") < ctx.index("## Scene contract")
    assert "Never mention the key again." in ctx
    assert "Length: about 500 words — hard limit 625 words" in ctx


# ── Steering file ──────────────────────────────────────────────────────────────

@pytest.fixture
def book(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    book_dir = tmp_path / BOOK
    (book_dir / "tier4").mkdir(parents=True)
    (book_dir / "tier4" / "chapter_01.md").write_text(
        "### Scene 1 — Arrival\nMary arrives.\n\n### Scene 2 — Talk\nThey talk.\n\n### Scene 3 — Exit\nShe leaves."
    )
    Repo.init(book_dir)
    return book_dir


def test_scene_word_target(book):
    import steering
    assert steering.scene_word_target(BOOK, 3) == steering.DEFAULT_SCENE_WORDS
    steering.write(BOOK, {"target_chapter_words": 1500})
    assert steering.scene_word_target(BOOK, 3) == 500
    assert steering.scene_word_target(BOOK, 100) == steering.MIN_SCENE_WORDS
    assert steering.word_limit(500) == 625
    assert steering.planned_scene_count(BOOK, 1) == 3


def test_notes_for_combines_book_and_chapter(book):
    import steering
    steering.write(BOOK, {"book_notes": "No recaps.", "chapter_notes": {"1": "Keep it quiet.", "2": "  "}})
    assert steering.notes_for(BOOK, 1) == "Whole book:\nNo recaps.\n\nThis chapter:\nKeep it quiet."
    assert steering.notes_for(BOOK, 2) == "Whole book:\nNo recaps."
    assert steering.read(BOOK)["chapter_notes"] == {"1": "Keep it quiet."}


# ── Chapter writer ─────────────────────────────────────────────────────────────

def _setup_writer(monkeypatch, *, qa=QA_PASS, retry=False, writer_words=100, plan_scenes=3, extra_settings=None):
    """Stub LLM calls. Returns a dict recording writer prompts and tighten calls."""
    import db
    from routes import phase3, text_ops

    settings = {
        "agent_writer_agent_provider": "p", "agent_writer_agent_model": "m",
        "agent_qa_agent_provider": "p", "agent_qa_agent_model": "m",
        "agent_bible_agent_provider": "p", "agent_bible_agent_model": "m",
        "qa_retry_manual": "true" if retry else None,
        **(extra_settings or {}),
    }
    monkeypatch.setattr(db, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(db, "append_job_log", lambda *a: None)
    rec = {"writer_prompts": [], "tighten": []}

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False, **kwargs):
        if system == phase3.SCENE_PLANNER_SYSTEM:
            return json.dumps([{"scene": n, "brief": f"brief {n}", "entry_state": "", "exit_state": f"exit {n}"}
                               for n in range(1, plan_scenes + 1)])
        if system == phase3.QA_SYSTEM:
            return json.dumps(qa)
        rec["writer_prompts"].append(messages[0]["content"])
        n = len(rec["writer_prompts"])
        return " ".join([f"draft{n}"] * writer_words)

    async def fake_tighten(prose, target, user, book_id=None):
        rec["tighten"].append(target)
        return " ".join(["tight"] * target)

    monkeypatch.setattr(phase3, "_call", fake_call)
    monkeypatch.setattr(text_ops, "tighten_prose", fake_tighten)
    return rec


def _write(pause=False, auto=False):
    from routes import phase3
    events = []

    async def emit(ev):
        events.append(ev)

    finished = asyncio.run(phase3._write_chapter_core(
        BOOK, 1, "local", emit, lambda m: None, auto=auto, pause_after_scene=pause))
    return finished, events


def _meta(book_dir):
    return json.loads((book_dir / "chapter_01_meta.json").read_text())


def test_manual_over_length_scene_is_held_not_trimmed(book, monkeypatch):
    import steering
    steering.write(BOOK, {"target_chapter_words": 600})  # 200 words per scene, limit 250
    rec = _setup_writer(monkeypatch, writer_words=400, plan_scenes=3)
    finished, events = _write()
    assert finished
    assert rec["tighten"] == []
    scene = _meta(book)["scenes"][0]
    assert scene["qa_pass"] is False and scene["word_target"] == 200
    assert any(i["type"] == "length" and i["severity"] == "error" for i in scene["qa_issues"])
    assert {"type": "qa_held", "scene": 1} in events
    assert "Length: about 200 words" in rec["writer_prompts"][0]


def test_auto_mode_trims_over_length_scene(book, monkeypatch):
    import steering
    steering.write(BOOK, {"target_chapter_words": 600})
    rec = _setup_writer(monkeypatch, writer_words=400, plan_scenes=3)
    finished, _ = _write(auto=True)
    assert finished
    assert rec["tighten"] == [200, 200, 200]
    scenes = _meta(book)["scenes"]
    assert all(s["qa_pass"] and s["word_count"] == 200 for s in scenes)


def test_auto_write_stops_on_unresolved_qa(book, monkeypatch):
    QA_FAIL = {"pass": False, "issues": [{"type": "content", "description": "stalls", "severity": "error"}], "notes": "stalls"}
    rec = _setup_writer(monkeypatch, qa=QA_FAIL, plan_scenes=3,
                         extra_settings={"qa_stop_auto_write_on_unresolved": "true"})
    finished, events = _write(auto=True)
    assert finished == "qa_stopped"
    assert {"type": "qa_stopped", "scene": 1, "notes": "stalls"} in events
    assert _meta(book)["status"] == "in_progress"
    # Only Scene 1 was attempted — 3 retries, still failing — and it stopped there
    assert len(rec["writer_prompts"]) == 3


def test_auto_write_keeps_going_on_unresolved_qa_when_setting_off(book, monkeypatch):
    QA_FAIL = {"pass": False, "issues": [], "notes": "stalls"}
    _setup_writer(monkeypatch, qa=QA_FAIL, plan_scenes=2)  # setting left off by default
    finished, _ = _write(auto=True)
    assert finished == "finished"
    scenes = _meta(book)["scenes"]
    assert len(scenes) == 2 and all(not s["qa_pass"] for s in scenes)


def test_writer_gets_notes_and_condensed_history(book, monkeypatch):
    import steering
    steering.write(BOOK, {"book_notes": "Do not restate the task."})
    rec = _setup_writer(monkeypatch, plan_scenes=3)
    _write()
    third = rec["writer_prompts"][2]
    assert "Do not restate the task." in third
    assert "- Scene 1: brief 1 Ends with: exit 1" in third
    assert "draft1" not in third  # scene 1 prose is summarised, not repeated
    assert "[Previous scene — Scene 2]" in third and "draft2" in third


def test_pause_resume_keeps_author_edits(book, monkeypatch):
    from routes import phase3
    rec = _setup_writer(monkeypatch, plan_scenes=2)

    finished, events = _write(pause=True)
    assert finished == "paused"
    assert {"type": "paused", "scene": 1, "remaining": 1} in events
    assert _meta(book)["status"] == "in_progress"
    assert Repo(book).head.commit.message == "Write Chapter 1 — paused after Scene 1"

    # Author edits the paused scene through the normal save endpoint
    app = FastAPI()
    app.include_router(phase3.router)
    client = TestClient(app)
    assert client.post(f"/books/{BOOK}/phase3/chapter/1/approve").status_code == 409
    assert client.put(f"/books/{BOOK}/phase3/chapter/1/scene/1/prose", json={"content": "Edited opening."}).status_code == 200

    finished, _ = _write(pause=True)
    assert finished
    content = (book / "chapter_01.md").read_text()
    assert "## Scene 1\n\nEdited opening." in content and "## Scene 2" in content
    meta = _meta(book)
    assert meta["status"] == "written"
    assert meta["scenes"][0]["author_edited"] is True
    assert "Edited opening." in rec["writer_prompts"][1]
    assert not os.path.exists(book / "chapter_01_progress.json")


def test_regenerate_after_drops_later_scenes_and_rewrites_them(book, monkeypatch):
    from routes import phase3
    rec = _setup_writer(monkeypatch, plan_scenes=3)
    _write()
    assert len(rec["writer_prompts"]) == 3

    dropped = phase3._prepare_regenerate_after(BOOK, 1, 1)
    assert dropped == 2
    assert _meta(book)["status"] == "in_progress"
    sections = phase3._scene_sections((book / "chapter_01.md").read_text())
    assert list(sections) == [1]

    finished, _ = _write()
    assert finished
    sections = phase3._scene_sections((book / "chapter_01.md").read_text())
    assert list(sections) == [1, 2, 3]
    assert sections[1].startswith("draft1") and sections[2].startswith("draft4")


def test_regenerate_after_rejects_approved_chapter(book, monkeypatch):
    from fastapi import HTTPException
    from routes import phase3
    _setup_writer(monkeypatch, plan_scenes=2)
    _write()
    meta = _meta(book)
    meta["status"] = "approved"
    (book / "chapter_01_meta.json").write_text(json.dumps(meta))
    with pytest.raises(HTTPException) as exc:
        phase3._prepare_regenerate_after(BOOK, 1, 1)
    assert exc.value.status_code == 409


def test_steering_endpoints_roundtrip_and_commit(book):
    from routes import phase3
    Repo(book).index.commit("init")
    app = FastAPI()
    app.include_router(phase3.router)
    client = TestClient(app)
    body = {"target_chapter_words": 2400, "book_notes": "No recaps.", "chapter_notes": {"3": "Slow down."}}
    assert client.put(f"/books/{BOOK}/phase3/steering", json=body).json()["data"] == body
    assert client.get(f"/books/{BOOK}/phase3/steering").json()["data"] == body
    assert Repo(book).head.commit.message == "Update length target and standing notes"


def test_rewrite_scene_caps_qa_prior_scenes(book, monkeypatch):
    """rewrite_scene's QA prior-scenes text must be word-capped like _write_chapter_core's,
    not every other scene in the chapter joined in full and uncapped."""
    import db
    import jobs as job_store
    from routes import phase3

    monkeypatch.setattr(db, "get_setting", lambda k: {
        "agent_writer_agent_provider": "p", "agent_writer_agent_model": "m",
        "agent_qa_agent_provider": "p", "agent_qa_agent_model": "m",
    }.get(k))

    # Three "other" scenes (1, 3, 4), each large enough that all three together
    # exceed _truncate_prior_scenes' 4000-word cap; the middle scene (2) is being rewritten.
    def scene_block(n, num, words=1800):
        return f"## Scene {num}\n\nSCENE{num}_TOKEN " + "filler " * words

    content = "# Chapter 1\n\n" + "\n\n---\n\n".join([
        scene_block(1, 1), "## Scene 2\n\nShort scene two.", scene_block(3, 3), scene_block(4, 4),
    ])
    (book / "chapter_01.md").write_text(content)

    captured = {}

    async def fake_provider_tokens(provider, model, messages, system, user_id, json_mode=False, usage=None):
        yield "Rewritten scene two."

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False, **kwargs):
        captured["qa_user"] = messages[0]["content"]
        return json.dumps(QA_PASS)

    monkeypatch.setattr(phase3.llm, "provider_tokens", fake_provider_tokens)
    monkeypatch.setattr(phase3, "_call", fake_call)

    async def run():
        resp = await phase3.rewrite_scene(BOOK, 1, 2, phase3.RewriteBody(directive="Tighten it"), user="local")
        job_id = resp["job_id"]
        for _ in range(200):
            job = job_store.get(job_id)
            if job["status"] != "running":
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("background rewrite never finished")
        return job

    job = asyncio.run(run())
    assert job["status"] == "done"

    qa_user = captured["qa_user"]
    # The most recent scenes (3 and 4) fit under the cap and are kept in full;
    # the oldest (1) is dropped and its omission is noted rather than silently sent in full.
    assert "SCENE3_TOKEN" in qa_user
    assert "SCENE4_TOKEN" in qa_user
    assert "SCENE1_TOKEN" not in qa_user
    assert "earlier scene(s) omitted for context length" in qa_user


def test_scene_section_helpers():
    from routes.phase3 import _replace_scene_section, _scene_sections
    content = "# Chapter 1\n\n## Scene 1\n\nOne.\n\n---\n\n## Scene 10\n\nTen."
    assert _scene_sections(content) == {1: "One.", 10: "Ten."}
    assert _scene_sections(_replace_scene_section(content, 1, "Uno \\n")) == {1: "Uno \\n", 10: "Ten."}
    assert _scene_sections(_replace_scene_section(content, 2, "Two.")) == {1: "One.", 10: "Ten.", 2: "Two."}
    assert _replace_scene_section("# Chapter 1", 1, "One.") == "# Chapter 1\n\n## Scene 1\n\nOne."
