"""Layer 4 of quality control: which draft is better?

Pairwise, A against B, run twice with the order swapped. If the two runs name different drafts the
pair is a tie. With three drafts every pair is judged and the draft with most wins is chosen; ties
are settled by the mechanical score and then by draft number. Models tend to favour longer text
and their own style; the swap and the separate judge reduce that but do not remove it.
"""

from dataclasses import dataclass, field
from itertools import combinations

from ..bible.models import Scene
from ..errors import BookforgeError
from .mechanical import MechanicalReport
from .support import ask_json, scene_brief, voice_excerpt


@dataclass
class JudgeResult:
    winner: str
    wins: dict[str, int] = field(default_factory=dict)
    pairs: list[dict] = field(default_factory=list)
    error: str | None = None


def _check(data: dict) -> list[str]:
    return [] if data.get("winner") in ("A", "B") else ['"winner" must be "A" or "B"']


def _ask(ctx, scene: Scene, label: str, first: str, second: str) -> str:
    """'first' or 'second', whichever the judge preferred."""
    project = ctx.project
    data = ask_json(ctx, label, "critic", "judge", _check, max_tokens=300, brief=scene_brief(project, scene),
                    voice=voice_excerpt(project), a=first, b=second)
    return "first" if data["winner"] == "A" else "second"


def judge_pair(ctx, scene: Scene, name_a: str, text_a: str, name_b: str, text_b: str) -> tuple[str | None, dict]:
    """The winning draft name, or None for a tie, plus the record of both runs."""
    one = _ask(ctx, scene, f"{scene.id} judge {name_a} vs {name_b}", text_a, text_b)
    two = _ask(ctx, scene, f"{scene.id} judge {name_b} vs {name_a}", text_b, text_a)
    first_run = name_a if one == "first" else name_b
    second_run = name_b if two == "first" else name_a
    winner = first_run if first_run == second_run else None
    return winner, {"a": name_a, "b": name_b, "run1": first_run, "run2": second_run, "winner": winner}


def choose_draft(ctx, scene: Scene, drafts: dict[str, str], reports: dict[str, MechanicalReport]) -> JudgeResult:
    names = list(drafts)
    wins = {n: 0 for n in names}
    pairs = []
    try:
        for a, b in combinations(names, 2):
            winner, record = judge_pair(ctx, scene, a, drafts[a], b, drafts[b])
            pairs.append(record)
            if winner:
                wins[winner] += 1
    except BookforgeError as e:
        best = min(names, key=lambda n: (reports[n].score, n))
        return JudgeResult(best, wins, pairs, error=str(e))
    best = min(names, key=lambda n: (-wins[n], reports[n].score, n))
    return JudgeResult(best, wins, pairs)
