"""
Composable prompt-block functions for the Writer agent.

Each function returns a non-empty string or "" (empty blocks are filtered out
by assemble_writer_context before joining). This makes it trivial to add or
remove a block from any agent's context without touching the assembly call.
"""


def block_writing_rules(north_star: str, writing_prefs: str) -> str:
    parts = []
    if north_star:
        parts.append(f"## North Star\n\n{north_star}")
    if writing_prefs:
        parts.append(f"## Writing Preferences\n\n{writing_prefs}")
    return "\n\n".join(parts)


_LEDGER_CHAR_LIMIT = 80_000  # ~20k tokens — enough for hundreds of entities


def block_active_entities(ledger_json: str) -> str:
    if not ledger_json or ledger_json in ("{}", "null", ""):
        return ""
    if len(ledger_json) > _LEDGER_CHAR_LIMIT:
        ledger_json = ledger_json[:_LEDGER_CHAR_LIMIT] + "\n... [ledger truncated for context length]"
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
    blocks = [
        block_writing_rules(north_star, writing_prefs),
        block_active_entities(ledger_json),
        block_story_history(prior_text, prior_bridge),
        block_foreshadowing(),
        block_scene_contract(chapter, scene_num, brief, entry_state, exit_state, rewrite_note),
    ]
    return "\n\n".join(b for b in blocks if b)
