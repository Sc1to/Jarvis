import json

from bookforge.research.notes import QuestionRecord, ResearchStore, normalize_question, notes_for_prompt, stores_for

FACT = dict(claim="A clavicle fracture takes about 6 weeks to heal.", url="https://a.example/x", title="A", fetched="2026-11-05",
            quote="most clavicle fractures heal in six weeks", layer="series_north_star", question="How long does it heal?")


def test_fact_ids_count_up_per_prefix(project):
    stores = stores_for(project)
    assert stores["series"].add_fact(**FACT).id == "s-0001"
    assert stores["series"].add_fact(**FACT).id == "s-0002"
    assert stores["book"].add_fact(**FACT).id == "b1-0001"


def test_ids_continue_after_reload_and_survive_gaps(project):
    store = stores_for(project)["series"]
    store.add_fact(**FACT)
    store.add_fact(**FACT)
    lines = store.sources_path.read_text().splitlines()
    store.sources_path.write_text(lines[1] + "\n")  # fact 1 deleted by the author
    assert store.next_fact_id() == "s-0003"


def test_sources_file_is_one_json_object_per_line(project):
    store = stores_for(project)["book"]
    store.add_fact(**FACT)
    rec = json.loads(store.sources_path.read_text().splitlines()[0])
    assert set(rec) == {"id", "claim", "url", "title", "fetched", "quote", "layer", "question", "sensitive"}
    assert store.facts()[0].quote == FACT["quote"]


def test_malformed_lines_are_skipped_not_fatal(project):
    store = stores_for(project)["series"]
    store.add_fact(**FACT)
    with store.sources_path.open("a") as f:
        f.write("not json\n{\"id\": \"s-9\"}\n\n")
    assert [f.id for f in store.facts()] == ["s-0001"]


def test_known_urls_and_questions(project):
    store = stores_for(project)["series"]
    store.add_fact(**FACT)
    store.add_question(QuestionRecord(layer="x", question="Q?", query="q", answered=False, reason="blocked"))
    assert store.known_urls() == {"https://a.example/x"}
    assert store.questions()[0].reason == "blocked"


def test_question_normalisation():
    assert normalize_question("  How LONG  does it\theal? ") == normalize_question("how long does it heal?")


def test_readable_notes_show_answers_and_gaps(project):
    store = stores_for(project)["series"]
    fact = store.add_fact(**FACT, sensitive=True)
    store.add_question(QuestionRecord("series_north_star", "How long does it heal?", "q", True, [fact.id], sensitive=True))
    store.add_question(QuestionRecord("series_north_star", "Who invented the sling?", "q2", False, reason="search blocked"))
    store.add_question(QuestionRecord("synopsis", "Other layer", "q3", False, reason="x"))
    text = store.write_notes("series_north_star").read_text()
    assert "## How long does it heal? (sensitive: verify)" in text
    assert "[s-0001] A clavicle fracture" in text and "https://a.example/x" in text and 'quote: "most clavicle' in text
    assert "No answer found: search blocked" in text
    assert "Other layer" not in text


def test_prompt_notes_are_none_until_research_exists(project):
    assert notes_for_prompt(project, 6000) == "none yet"


def test_prompt_notes_combine_both_scopes_and_name_sources(project):
    stores = stores_for(project)
    stores["series"].add_fact(**FACT)
    stores["book"].add_fact(**{**FACT, "claim": "Book fact."})
    text = notes_for_prompt(project, 6000)
    assert "[s-0001]" in text and "[b1-0001] Book fact." in text and "a.example/x" in text
    assert "6 weeks to heal" in text


def test_prompt_notes_keep_the_newest_when_over_budget(project):
    store = stores_for(project)["series"]
    for i in range(10):
        store.add_fact(**{**FACT, "claim": f"claim number {i}"})
    text = notes_for_prompt(project, 200)
    assert "claim number 9" in text and "claim number 0" not in text
    assert len(text) <= 200
    assert notes_for_prompt(project, 5) == "none yet"
