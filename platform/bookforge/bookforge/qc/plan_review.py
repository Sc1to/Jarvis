"""The critic's review of a plan (acts, the chapters of an act, the scenes of a chapter).

The design has the critic check each child against its parent and both north stars, and System One
check it against the bible's state at that point. Here both are one critic call: the state tracks
are part of what it is given. The result is a list of problems, each naming the item it concerns.
A review that cannot be obtained is reported as no problems: it never blocks a layer.
"""

from ..errors import BookforgeError
from .support import ask_json


def _check(data: dict) -> list[str]:
    if not isinstance(data.get("ok"), bool):
        return ['"ok" must be true or false']
    problems = data.get("problems")
    if not isinstance(problems, list):
        return ['"problems" must be a list']
    if data["ok"]:
        return []
    bad = [i for i, p in enumerate(problems) if not isinstance(p, dict) or not str(p.get("item", "")).strip() or not str(p.get("issue", "")).strip()]
    if bad:
        return [f"problems[{i}] needs an 'item' and an 'issue'" for i in bad]
    return [] if problems else ['"ok" is false but no problems are listed']


def review_plan(ctx, label: str, what: str, parent: str, proposed: str, tracks: str, north_stars: dict[str, str], ledger: str = "none (this book has no ledger)") -> list[str]:
    try:
        data = ask_json(ctx, f"{label} review", "critic", "plan_review", _check, max_tokens=900, what=what, parent=parent,
                        proposed=proposed, tracks=tracks, ledger=ledger, series_north_star=north_stars["series_north_star"],
                        book_north_star=north_stars["book_north_star"])
    except BookforgeError:
        return []
    if data["ok"]:
        return []
    return [f"{str(p['item']).strip()}: {str(p['issue']).strip()}" for p in data["problems"]]
