"""
Composable prompt-block functions for the Writer agent.

Each function returns a non-empty string or "" (empty blocks are filtered out
by assemble_writer_context before joining). This makes it trivial to add or
remove a block from any agent's context without touching the assembly call.
"""
import json


def block_writing_rules(north_star: str, writing_prefs: str) -> str:
    parts = []
    if north_star:
        parts.append(f"## North Star\n\n{north_star}")
    if writing_prefs:
        parts.append(f"## Writing Preferences\n\n{writing_prefs}")
    return "\n\n".join(parts)


def filter_ledger_for_scene(ledger_json: str, scene_context: str) -> str:
    """Return a JSON string containing only entities whose name is mentioned in scene_context.

    Matches on any word from the entity name that is 3+ characters long, so
    "Willem Decker" is included if the context mentions "Willem" or "Decker".
    Falls back to the full ledger if nothing matches (shouldn't happen in
    practice since the brief always names the POV character).
    """
    if not ledger_json or ledger_json in ("{}", "null", ""):
        return ledger_json
    try:
        ledger = json.loads(ledger_json)
    except Exception:
        return ledger_json

    context_lower = scene_context.lower()
    filtered = {}
    for eid, entity in ledger.items():
        name = entity.get("name", "")
        if not name:
            continue
        name_parts = [p for p in name.lower().split() if len(p) >= 3]
        if any(part in context_lower for part in name_parts):
            filtered[eid] = entity

    if not filtered:
        return ledger_json  # nothing matched — send full ledger as safety net
    return json.dumps(filtered, indent=2)


def strip_event_logs(ledger_json: str) -> str:
    """Drop each entity's eventLog. The Writer needs current state for consistency;
    the event history only invites it to recap things the reader already knows."""
    if not ledger_json or ledger_json in ("{}", "null", ""):
        return ledger_json
    try:
        ledger = json.loads(ledger_json)
    except Exception:
        return ledger_json
    if not isinstance(ledger, dict):
        return ledger_json
    stripped = {
        eid: {k: v for k, v in entity.items() if k != "eventLog"} if isinstance(entity, dict) else entity
        for eid, entity in ledger.items()
    }
    return json.dumps(stripped, indent=2)


def block_active_entities(ledger_json: str) -> str:
    if not ledger_json or ledger_json in ("{}", "null", ""):
        return ""
    return f"## Entity Ledger\n\n{ledger_json}"


def block_story_history(prior_text: str, prior_bridge: str = "") -> str:
    parts = []
    if prior_text and prior_text != "None yet.":
        parts.append(f"## Prior scenes in this chapter\n\n{prior_text}")
    elif prior_text:
        parts.append("## Prior scenes in this chapter\n\nNone yet.")
    if prior_bridge:
        parts.append(f"## Prior chapter context\n\n{prior_bridge}")
    return "\n\n".join(parts)


def _truncate_prior_scenes(scenes: list[str], max_words: int = 4000) -> str:
    """Keep the most recent scenes that fit within max_words, oldest first."""
    if not scenes:
        return "None yet."
    included: list[str] = []
    total = 0
    for scene in reversed(scenes):
        wc = len(scene.split())
        if total + wc > max_words and included:
            break
        included.insert(0, scene)
        total += wc
    if len(included) < len(scenes):
        prefix = f"[{len(scenes) - len(included)} earlier scene(s) omitted for context length]\n\n"
        return prefix + "\n\n---\n\n".join(included)
    return "\n\n---\n\n".join(included)


def _tail_words(text: str, n: int) -> str:
    words = text.split()
    return text.strip() if len(words) <= n else "… " + " ".join(words[-n:])


def condense_prior_scenes(
    scenes: list[tuple[int, str]],
    summaries: dict[int, str] | None = None,
    last_scene_words: int = 1200,
) -> str:
    """Writer view of the chapter so far: one line per earlier scene, the previous scene in full.

    Full text of every prior scene is an invitation to repeat it. The Writer only
    needs the previous scene verbatim (for flow) and to know what the rest covered.
    `summaries` maps scene number -> planned brief/exit state; scenes without one
    fall back to a short tail of their prose.
    """
    if not scenes:
        return "None yet."
    summaries = summaries or {}
    parts = []
    earlier = scenes[:-1]
    if earlier:
        lines = ["Already covered in this chapter — the reader knows all of this; do not restate it:"]
        for num, text in earlier:
            lines.append(f"- Scene {num}: {summaries.get(num) or _tail_words(text, 60)}")
        parts.append("\n".join(lines))
    last_num, last_text = scenes[-1]
    parts.append(f"[Previous scene — Scene {last_num}]\n{_tail_words(last_text, last_scene_words)}")
    return "\n\n".join(parts)


def block_author_notes(notes: str) -> str:
    if not notes.strip():
        return ""
    return (
        "## Author standing notes\n\n"
        "Binding directions from the author. Where they conflict with the brief or the "
        "writing preferences, these win.\n\n"
        f"{notes.strip()}"
    )


def block_foreshadowing() -> str:
    # Stub — returns "" until foreshadowing_brief.json is implemented (per WRITER_SPEC.md §4.4)
    return ""


def block_scene_contract(
    chapter: int,
    scene_num: int,
    brief: str,
    entry_state: str,
    exit_state: str,
    rewrite_note: str = "",
    word_target: int | None = None,
    word_limit: int | None = None,
) -> str:
    lines = [
        "## Scene contract",
        "",
        f"Chapter: {chapter} | Scene: {scene_num}",
        f"Brief: {brief}",
    ]
    if entry_state:
        lines.append(f"Entry state: {entry_state}")
    if exit_state:
        lines.append(f"Exit state: {exit_state}")
    if word_target:
        limit = f" — hard limit {word_limit} words" if word_limit else ""
        lines.append(
            f"Length: about {word_target} words{limit}. This overrides any other length guidance. "
            "Cover the beats economically; cut rather than pad."
        )
    if rewrite_note:
        lines.append(rewrite_note)
    return "\n".join(lines)


def assemble_writer_context(
    north_star: str,
    writing_prefs: str,
    ledger_json: str,
    prior_text: str,
    chapter: int,
    scene_num: int,
    brief: str,
    entry_state: str,
    exit_state: str,
    prior_bridge: str = "",
    rewrite_note: str = "",
    author_notes: str = "",
    word_target: int | None = None,
    word_limit: int | None = None,
) -> str:
    # Filter the ledger to only entities referenced in this scene's context,
    # and drop their event history (see strip_event_logs)
    scene_context = f"{brief} {entry_state} {exit_state} {prior_text}"
    filtered_ledger = strip_event_logs(filter_ledger_for_scene(ledger_json, scene_context))

    blocks = [
        block_writing_rules(north_star, writing_prefs),
        block_active_entities(filtered_ledger),
        block_story_history(prior_text, prior_bridge),
        block_foreshadowing(),
        block_author_notes(author_notes),
        block_scene_contract(chapter, scene_num, brief, entry_state, exit_state, rewrite_note,
                             word_target, word_limit),
    ]
    return "\n\n".join(b for b in blocks if b)
