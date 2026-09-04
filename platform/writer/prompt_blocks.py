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
) -> str:
    # Filter the ledger to only entities referenced in this scene's context
    scene_context = f"{brief} {entry_state} {exit_state} {prior_text}"
    filtered_ledger = filter_ledger_for_scene(ledger_json, scene_context)

    blocks = [
        block_writing_rules(north_star, writing_prefs),
        block_active_entities(filtered_ledger),
        block_story_history(prior_text, prior_bridge),
        block_foreshadowing(),
        block_scene_contract(chapter, scene_num, brief, entry_state, exit_state, rewrite_note),
    ]
    return "\n\n".join(b for b in blocks if b)
