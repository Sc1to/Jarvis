"""A chapter may claim only the state changes its own events (and earlier ones) account for.

A chapter about deciding to do something must not end with it done. The wording check cannot see this ("decides to broadcast" / "the data is
now public" share no words), so this compares the CHANGE OF STATE each text asserts: common result words are grouped into classes (made
public, taken, killed, destroyed, agreed, gone), and two texts that name the same class and share an object describe the same change.
Nothing here is about any one story: the classes are the ordinary results stories report."""

from dataclasses import replace

from .findings import Finding, hard, soft
from .text import WORD, canon, content_stems, stem

_RESULT_CLASSES = {
    "PUBLIC": "broadcast upload publish public release leak transmit expose post circulate disclose",
    "TAKEN": "arrest capture seize detain imprison confiscate kidnap",
    "DEAD": "die kill dead murder execute slay",
    "DESTROYED": "destroy burn wreck demolish ruin shatter",
    "AGREED": "sign agree accept consent swear pledge",
    "GONE": "depart sail vanish disappear",
    "BREACHED": "breach rupture pierce",
}
_RESULT = {stem(w): label for label, words in _RESULT_CLASSES.items() for w in words.split()}


def signature(text: str) -> set[str]:
    """Content stems of the text with result words replaced by their class (names are left in: the same change to someone else is another change)."""
    out = set()
    for t in WORD.findall(text):
        s = stem(t)
        out.add(_RESULT.get(s) or canon(t)) if len(s) >= 3 else None
    drop = {canon(w) for w in WORD.findall(text) if len(w) < 3}
    return {x for x in out if x not in drop and x in set(content_stems(text)) | set(_RESULT.values())}


def classes_in(sig: set[str]) -> set[str]:
    return sig & set(_RESULT_CLASSES)


def same_change(a: set[str], b: set[str], ignore: set[str] = frozenset()) -> set[str]:
    """What two signatures share when they report the same kind of change of the same thing: a result class and at least one other word.
    `ignore` are words too common in this book to say what a change is about (the protagonist's name, the place everything happens)."""
    shared = a & b
    return shared if classes_in(shared) and len(shared - set(_RESULT_CLASSES) - set(ignore)) >= 1 else set()


def ubiquitous(texts: list[str], share: float = 0.25, minimum: int = 3) -> set[str]:
    """Words that turn up in at least a quarter of the book's chapters: a name or a setting every chapter mentions says nothing about WHICH change two
    texts describe (so 'Eli' and 'accept' in both a chapter and an event is not the same change)."""
    sigs = [signature(t) for t in texts]
    count: dict[str, int] = {}
    for sig in sigs:
        for w in sig - set(_RESULT_CLASSES):
            count[w] = count.get(w, 0) + 1
    need = max(minimum, int(len(sigs) * share))
    return {w for w, n in count.items() if n >= need}


def _owned(c: dict) -> set[str]:
    return set(c.get("events_covered") or []) | set(c.get("events_continued") or [])


def end_state_overreach(chapters: list[dict], events: list[dict], stage: str = "chapters") -> list[Finding]:
    """A chapter's end_state and summary may report only what its own events and the earlier chapters' events (and their child events) bring about.
    One that describes the outcome of an event a LATER chapter tells is claiming too much (hard)."""
    by_id = {e["id"]: e for e in events}
    out: list[Finding] = []
    seen: set[str] = set()
    common = ubiquitous([" ".join(str(c.get(k, "")) for k in ("end_state", "summary")) for c in chapters])
    for i, c in enumerate(chapters):
        mine = _owned(c)
        owned_now = seen | mine
        children = {e["id"] for e in events if e.get("parent") in owned_now}
        later: set[str] = set()
        for later_c in chapters[i + 1:]:
            later |= _owned(later_c)
        claim_text = " ".join(str(c.get(k, "")) for k in ("end_state", "summary"))
        claim = signature(claim_text)
        for ev_id in later - owned_now - children:
            ev = by_id.get(ev_id)
            if not ev or not ev.get("once_only", True):
                continue
            shared = same_change(claim, signature(ev.get("text", "")), common)
            if shared:
                out.append(hard(stage, "end_state_overreach", f"{c['id']} reports the outcome of {ev_id} ('{ev['text'][:80]}') in its summary or end_state, but a later chapter tells it: "
                                "a chapter may claim only the changes its own events bring about (a chapter about deciding to do something does not end with it done)",
                                [c["id"], ev_id], [f"chapter: {claim_text[:200]}", f"event {ev_id}: {ev['text'][:200]}"]))
        seen |= mine
    return out


def state_change_repeated(chapters: list[dict], events: list[dict], stage: str = "chapters") -> list[Finding]:
    """Two chapters whose own events change the same thing in the same way (made public twice): a repeat the wording check misses (soft: a model confirms)."""
    by_id = {e["id"]: e for e in events}
    out: list[Finding] = []
    sigs = []
    for c in chapters:
        sigs.append([(x, signature(by_id[x]["text"])) for x in sorted(_owned(c)) if x in by_id and by_id[x].get("once_only", True)])
    for i in range(len(chapters)):
        for j in range(i + 1, len(chapters)):
            for xa, sa in sigs[i]:
                for xb, sb in sigs[j]:
                    if xa != xb and same_change(sa, sb):
                        out.append(soft(stage, "state_change_repeated", f"{chapters[i]['id']} ({xa}) and {chapters[j]['id']} ({xb}) both bring about the same change ({', '.join(sorted(same_change(sa, sb)))}): check that the second is not the first again",
                                        [chapters[i]["id"], chapters[j]["id"], xa, xb], [f"{xa}: {by_id[xa]['text'][:160]}", f"{xb}: {by_id[xb]['text'][:160]}"]))
    return out


def scene_end_state_overreach(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """The scene-level twin: a scene's purpose, beats and end_state may report only what the events told so far (its own and earlier ones) bring about.
    A scene is a unit that owns its events (a scene that only goes on with the one before it owns the same ones); the check is the chapter check run over
    the scenes in story order, so the outcome of an event a LATER scene or chapter tells is caught where it is claimed too early."""
    by_ch = {c["id"]: c for c in chapters}
    units: list[dict] = []
    prev_owned: set[str] = set()
    last_chapter = None
    for sc in scenes:
        chapter = sc.get("chapter") or sc["id"].rsplit(".s", 1)[0]
        own = set(sc.get("events") or [])
        if chapter != last_chapter:
            own |= set(by_ch.get(chapter, {}).get("events_continued") or [])
            prev_owned = set()
        owned = own or prev_owned  # a scene with no event of its own goes on with the scene before it
        prev_owned = owned
        last_chapter = chapter
        units.append({"id": sc["id"], "events_covered": sorted(owned), "end_state": sc.get("end_state", ""),
                      "summary": " ".join([str(sc.get("purpose", ""))] + [str(b) for b in sc.get("beats") or []])})
    found = end_state_overreach(units, events, stage)
    out = []
    for f in found:
        sid = f.items[0]
        sc = next((x for x in scenes if x["id"] == sid), {})
        quoted = f"scene: {sc.get('purpose', '')} {' '.join(str(b) for b in sc.get('beats') or [])} End: {sc.get('end_state', '')}"[:220]
        ev_line = next((t for t in f.evidence if t.startswith("event ")), "")
        text = (f.message.replace("summary or end_state", "purpose, beats or end_state").replace("a later chapter tells it", "a later scene or chapter tells it")
                .replace("a chapter may claim", "a scene may claim").replace("a chapter about deciding", "a scene about deciding"))
        out.append(replace(f, message=text, evidence=[f"chapter: {quoted[len('scene: '):]}", ev_line]))
    return out
