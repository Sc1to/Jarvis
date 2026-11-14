"""The cast editor: add, edit, delete and rename the entities of a book's bible (`books/<book>/bible/constants.yaml`).

Every change is checked against the rest of the book and is all or nothing: if it would leave a chapter, a scene or a track pointing at an
entity that is not there, it is refused with the reason and nothing is written. Editing the facts or the name of an entity changes what the
writer is told about it, so the scenes already written with the old text are marked out of date by their dependency fingerprints.

A series that still shares one bible between its books (older series, until `split-bible`) can add, edit and delete (usage is counted
across every book) but not rename: a rename has to change every reference in every book.
"""

import re
from pathlib import Path

from pydantic import ValidationError

from . import rules as rules_mod, vcs
from .bible import store
from .bible.models import Constants, Entity, problems_from
from .bible.validate import validate_bible
from .books import book_ids
from .errors import BookforgeError
from .project import Project

SLUG = re.compile(r"^[a-z][a-z0-9-]{0,59}$")


class CastError(BookforgeError):
    pass


def _projects(project: Project) -> list[Project]:
    """The books whose files may refer to an entity of this bible: just this one, or every book while the bible is shared."""
    if store.shared_bible(project):
        return [Project.open(project.root, b) for b in book_ids(project.root)]
    return [project]


def usage(project: Project, entity_id: str) -> list[dict]:
    """Every place that refers to the entity: [{where, as}]."""
    out: list[dict] = []
    for p in _projects(project):
        if store.chapters_path(p).exists():
            for c in store.load_chapters(p):
                if c.pov == entity_id:
                    out.append({"where": f"chapter {c.id} ({c.title})", "as": "viewpoint character"})
                if c.setting == entity_id:
                    out.append({"where": f"chapter {c.id} ({c.title})", "as": "setting"})
        if store.scenes_path(p).exists():
            for s in store.load_scenes(p):
                if s.pov == entity_id:
                    out.append({"where": f"scene {s.id}", "as": "viewpoint character"})
                if s.setting == entity_id:
                    out.append({"where": f"scene {s.id}", "as": "setting"})
                if entity_id in s.characters and s.pov != entity_id:
                    out.append({"where": f"scene {s.id}", "as": "present"})
        led = store.load_ledger(p) if store.ledger_path(p).exists() else None
        if led:
            out += [{"where": f"story event {e.id}", "as": "viewpoint"} for e in led.events if e.pov == entity_id]
    for t in store.load_tracks(project):
        if t.entity == entity_id:
            out.append({"where": f"state track {t.id}", "as": "owner"})
    try:
        out += [{"where": f"rule {r.id} of the rules panel", "as": "target"} for r in rules_mod.load_rules(project) if r.scope == "character" and r.target == entity_id]
    except BookforgeError:
        pass
    return out


def overview(project: Project) -> dict:
    constants = store.load_constants(project)
    return {"entities": [{**e.model_dump(), "used": len(usage(project, e.id))} for e in constants.entities],
            "rules": [r.model_dump() for r in constants.rules], "shared_bible": store.shared_bible(project)}


def _commit(project: Project, message: str, paths: list[Path]) -> None:
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: {message}", [str(p) for p in paths])


def _clean_facts(facts: list[str]) -> list[str]:
    out = [" ".join(str(f).split()) for f in facts if str(f).strip()]
    if not out:
        raise CastError("an entity needs at least one fact (something about it that does not change)")
    return out


def _check_entity(entity_id: str, kind: str, name: str, facts: list[str]) -> Entity:
    if not SLUG.match(entity_id):
        raise CastError(f"'{entity_id}' is not a usable id: lowercase letters, digits and '-', starting with a letter (like anna-voss)")
    try:
        return Entity(id=entity_id, kind=kind, name=name, facts=_clean_facts(facts))
    except ValidationError as e:  # the message names the field that is wrong
        raise CastError("; ".join(problems_from(e, limit=3))) from e


def _save_checked(project: Project, constants: Constants, what: str, message: str) -> None:
    """Write the cast, then check the whole book against it: a change that adds problems is put back and refused."""
    path = store.constants_path(project)
    before = validate_bible(project, False)
    with store.transaction([path]):
        store.save_constants(project, constants)
        new = [p for p in validate_bible(project, False) if p not in before]
        if new:
            raise CastError(f"{what} would leave the book inconsistent: " + "; ".join(new[:4]))
    _commit(project, message, [path])


def add(project: Project, entity_id: str, kind: str, name: str, facts: list[str]) -> Entity:
    entity = _check_entity(entity_id, kind, name, facts)
    constants = store.load_constants(project)
    if any(e.id == entity_id for e in constants.entities):
        raise CastError(f"'{entity_id}' is already in the cast")
    _save_checked(project, Constants(entities=constants.entities + [entity], rules=constants.rules), f"adding {entity_id}", f"you added {entity.name} to the cast")
    return entity


def update(project: Project, entity_id: str, kind: str | None = None, name: str | None = None, facts: list[str] | None = None) -> Entity:
    constants = store.load_constants(project)
    old = next((e for e in constants.entities if e.id == entity_id), None)
    if old is None:
        raise CastError(f"no entity '{entity_id}' in the cast")
    new = _check_entity(entity_id, kind or old.kind, name if name is not None else old.name, facts if facts is not None else old.facts)
    if new == old:
        return old
    _save_checked(project, Constants(entities=[new if e.id == entity_id else e for e in constants.entities], rules=constants.rules),
                  f"changing {entity_id}", f"you edited {new.name} in the cast")
    return new


def delete(project: Project, entity_id: str) -> None:
    constants = store.load_constants(project)
    old = next((e for e in constants.entities if e.id == entity_id), None)
    if old is None:
        raise CastError(f"no entity '{entity_id}' in the cast")
    used = usage(project, entity_id)
    if used:
        shown = "; ".join(f"{u['where']} ({u['as']})" for u in used[:8])
        raise CastError(f"{old.name} is still used in {len(used)} place(s): {shown}{' ...' if len(used) > 8 else ''}. Change or remove those first")
    _save_checked(project, Constants(entities=[e for e in constants.entities if e.id != entity_id], rules=constants.rules),
                  f"removing {entity_id}", f"you removed {old.name} from the cast")


def rename(project: Project, old_id: str, new_id: str) -> int:
    """Change an entity's id everywhere it is used in this book. Returns how many references changed."""
    if store.shared_bible(project):
        raise CastError("this series still shares one bible between its books: give each book its own first (split-bible), then rename")
    if not SLUG.match(new_id):
        raise CastError(f"'{new_id}' is not a usable id: lowercase letters, digits and '-', starting with a letter")
    constants = store.load_constants(project)
    if not any(e.id == old_id for e in constants.entities):
        raise CastError(f"no entity '{old_id}' in the cast")
    if any(e.id == new_id for e in constants.entities):
        raise CastError(f"'{new_id}' is already in the cast")
    paths = [store.constants_path(project), store.tracks_path(project), store.chapters_path(project), store.scenes_path(project), store.ledger_path(project),
             rules_mod.rules_path(project)]
    changed = len(usage(project, old_id))
    before = validate_bible(project, False)
    with store.transaction(paths):
        store.save_constants(project, Constants(entities=[e.model_copy(update={"id": new_id}) if e.id == old_id else e for e in constants.entities], rules=constants.rules))
        tracks = store.load_tracks(project)
        for t in tracks:
            if t.entity == old_id:
                t.entity = new_id
        store.save_tracks(project, tracks)
        if store.chapters_path(project).exists():
            chapters = store.load_chapters(project)
            for c in chapters:
                if c.pov == old_id:
                    c.pov = new_id
                if c.setting == old_id:
                    c.setting = new_id
            store.save_chapters(project, chapters)
        if store.scenes_path(project).exists():
            scenes = store.load_scenes(project)
            for s in scenes:
                if s.pov == old_id:
                    s.pov = new_id
                if s.setting == old_id:
                    s.setting = new_id
                if old_id in s.characters:
                    s.characters = [new_id if c == old_id else c for c in s.characters]
            store.save_scenes(project, scenes)
        if store.ledger_path(project).exists():
            led = store.load_ledger(project)
            for e in led.events:
                if e.pov == old_id:
                    e.pov = new_id
            store.save_ledger(project, led)
        rule_list = rules_mod.load_rules(project)
        if any(r.scope == "character" and r.target == old_id for r in rule_list):
            for r in rule_list:
                if r.scope == "character" and r.target == old_id:
                    r.target = new_id
            rules_mod.save_rules(project, rule_list)
        new = [p for p in validate_bible(project, False) if p not in before]
        if new:
            raise CastError("the rename would leave the book inconsistent: " + "; ".join(new[:4]))
    _commit(project, f"you renamed {old_id} to {new_id} in the cast ({changed} reference(s) changed)", [p for p in paths if p.exists()])
    return changed
