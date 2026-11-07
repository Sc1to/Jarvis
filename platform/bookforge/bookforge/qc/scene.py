"""Quality control for one scene, cheapest layer first.

1. Mechanical checks on every draft (no model).
2. If more than one draft has no blocking problem, the judge picks one (otherwise the best score wins).
3. On the chosen draft: mechanical, then continuity, then the critic. A layer only runs if the cheaper
   ones passed: a scene with a banned phrase is not worth a critique yet.
4. Whatever was flagged is revised passage by passage by the fast model, then layers 1 and 2 run again.
   The critic runs again only if its first critique scored under the minimum. At most
   `qc.max_revision_rounds` rounds.
5. What is still wrong then is reported, and the scene is left for the author.

Warnings from the mechanical checks, hesitant continuity answers and critic scores that pass are recorded
in the review but never revised.
"""

import hashlib
import json
from dataclasses import dataclass, field

from .. import activity, scenefiles
from ..bible.models import Scene
from ..errors import LayerError
from . import scene_notes
from .continuity import ContinuityReport, check_continuity
from .critic import WHOLE_SCENE, CriticReport, Weak, critic_flags, run_critic
from .judge import choose_draft
from .mechanical import CheckContext, MechanicalReport, all_banned, check_scene
from .revise import Flag, revise_text

FIXABLE_MECHANICAL = {"banned_phrase", "rule_phrase", "chatter", "formatting", "cut_off"}


@dataclass
class SceneQC:
    text: str
    chosen: str
    review: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)  # what is still wrong; empty means the scene can be accepted

    @property
    def accepted(self) -> bool:
        return not self.reasons


def _choose(ctx, scene: Scene, drafts: dict[str, str], reports: dict[str, MechanicalReport]) -> tuple[str, dict | None]:
    candidates = [n for n in drafts if not reports[n].blocking] or list(drafts)
    if len(candidates) == 1 or not ctx.project.config.qc.judge_drafts:
        return min(candidates, key=lambda n: (reports[n].score, n)), None
    activity.set(step="comparing the drafts")
    verdict = choose_draft(ctx, scene, {n: drafts[n] for n in candidates}, {n: reports[n] for n in candidates})
    return verdict.winner, {"candidates": candidates, "wins": verdict.wins, "pairs": verdict.pairs, "error": verdict.error}


def _mechanical_flags(blocking: list) -> tuple[list[Flag], list[str]]:
    fixable, unfixed = [], []
    for i in blocking:
        if i.code in FIXABLE_MECHANICAL and i.start is not None:
            fixable.append(Flag("mechanical", i.code, i.message, quote="", start=i.start, end=i.end))
        else:
            unfixed.append(i.message)
    return fixable, unfixed


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x00".join(p.strip() for p in parts).encode("utf-8")).hexdigest()[:16]  # a draft read back from its file differs only in whitespace


class Progress:
    """The expensive checks a scene already passed, kept in progress.json while the scene is being settled. A run that is paused or
    fails therefore does not repeat the judge, a clean continuity check or a critique of the same text. Keys are hashes of the text."""

    def __init__(self, project, scene_id: str):
        self.path = scenefiles.progress_path(project, scene_id)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}

    def get(self, kind: str, key: str):
        entry = self.data.get(kind)
        return entry.get(key) if isinstance(entry, dict) else None

    def put(self, kind: str, key: str, value) -> None:
        self.data.setdefault(kind, {})[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # progress is an optimisation, never a reason to fail a scene


def clear_progress(project, scene_id: str) -> None:
    scenefiles.progress_path(project, scene_id).unlink(missing_ok=True)


def settle_scene(ctx, scene: Scene, scenes: list[Scene], drafts: dict[str, str], mech: CheckContext, can_rewrite: bool = False) -> SceneQC:
    cfg = ctx.project.config.qc
    drafts_reports = {n: check_scene(t, mech) for n, t in drafts.items()}
    progress = Progress(ctx.project, scene.id)
    judge_key = _sha(*[f"{n}\x01{t}" for n, t in sorted(drafts.items())])
    saved_choice = progress.get("judge", judge_key)
    if saved_choice and saved_choice.get("chosen") in drafts:
        chosen, judge = saved_choice["chosen"], saved_choice.get("judge")
    else:
        chosen, judge = _choose(ctx, scene, drafts, drafts_reports)
        progress.put("judge", judge_key, {"chosen": chosen, "judge": judge})
    text = drafts[chosen]
    review: dict = {"chosen": chosen, "mechanical": {n: r.to_dict() for n, r in drafts_reports.items()},
                    "judge": judge, "rounds": []}

    critic: CriticReport | None = None
    accepted = scene_notes.read(ctx.project, scene.id)["accepted"]  # reasons the author accepted: they neither block nor get revised
    accepted_critic = {k.split(":", 1)[1] for k in accepted if k.startswith("critic:")}
    critic_given_up = False
    advised: list[str] = []  # whole-scene criteria that call for writing the scene again (see WHOLE_SCENE)
    continuity: ContinuityReport | None = None
    report = drafts_reports[chosen]
    open_blocking: list = []
    open_flags: list = []
    unfixable: list[str] = []
    for r in range(cfg.max_revision_rounds + 1):
        report = check_scene(text, mech)
        open_blocking = [i for i in report.blocking if scene_notes.mechanical_key(i) not in accepted]
        flags, unfixable = _mechanical_flags(open_blocking)
        continuity = None
        open_flags = []
        if not open_blocking and cfg.continuity_check:
            activity.set(step="checking continuity")
            text_key = _sha(text)
            clean = progress.get("continuity", text_key)
            if clean is not None:
                continuity = ContinuityReport(questions=clean.get("questions", 0), unsure=clean.get("unsure", []))
            else:
                continuity = check_continuity(ctx, scene, scenes, text)
                if not continuity.flags and not continuity.error:
                    progress.put("continuity", text_key, {"questions": continuity.questions, "unsure": continuity.unsure})
            instructions = scene_notes.read(ctx.project, scene.id)["instructions"]
            open_flags = [f for f in continuity.flags if scene_notes.continuity_key(f.question) not in accepted]
            for f in open_flags:
                if f.fixable:
                    flags.append(Flag("continuity", f.kind, f.message(), quote=f.evidence, fact=f.question,
                                      instruction=instructions.get(f.question, "")))
                else:
                    unfixable.append(f.message())
        cheap_ok = not open_blocking and not open_flags
        if cheap_ok and cfg.critic_check and not critic_given_up and not advised and (critic is None or critic.needs_work(cfg.critic_min_score, accepted_critic)):
            activity.set(step="the critic is reading it")
            saved = progress.get("critic", _sha(text))
            if saved is not None:
                critic = CriticReport(saved["scores"], [Weak(**w) for w in saved.get("weakest", [])], beats=saved.get("beats", []))
            else:
                critic = run_critic(ctx, scene, text)
                if not critic.error and critic.scores:
                    progress.put("critic", _sha(text), critic.to_dict())
            if critic.error:
                critic_given_up = True
            elif critic.needs_work(cfg.critic_min_score, accepted_critic):
                whole = [c for c in WHOLE_SCENE if c in critic.low(cfg.critic_min_score, accepted_critic)]
                if whole and can_rewrite and cfg.critic_rewrite:
                    # A missing beat or uneven pacing is not a problem of three lines. The caller writes the scene again with these
                    # notes, so patching its lines now would only spend time: record the advice and leave the critic's lines alone.
                    advised = whole
                else:
                    flags += critic_flags(ctx.project, critic, accepted_critic)
        record = {"round": r, "mechanical_blocking": [i.message for i in open_blocking],
                  "continuity_flags": [f.message() for f in open_flags],
                  "critic_lowest": critic.lowest if critic and critic.scores else None, "revisions": []}
        review["rounds"].append(record)
        if not flags or r == cfg.max_revision_rounds:
            break
        activity.set(step=f"revising (round {r + 1})")
        try:
            revision = revise_text(ctx, text, flags, all_banned(mech), f"{scene.id} round {r + 1}")
        except LayerError as e:  # the model could not produce an acceptable revision: leave the scene for the author
            record["revision_error"] = str(e)
            break
        record["revisions"] = revision.applied
        record["unfixed"] = [f.message for f in revision.unfixed]
        if not revision.applied:
            break
        text = revision.text

    # What still stands in the way, one item per reason, so each can be accepted on its own (key, kind, message).
    items = [{"key": scene_notes.mechanical_key(i), "kind": "mechanical", "message": i.message} for i in open_blocking]
    items += [{"key": scene_notes.continuity_key(f.question), "kind": "continuity", "message": f.message()} for f in open_flags]
    low = critic.low(cfg.critic_min_score, accepted_critic) if critic else []
    items += [{"key": scene_notes.critic_key(c), "kind": "critic", "message": f"the critic scored {c} {critic.scores[c]} (minimum {cfg.critic_min_score})"} for c in low]
    items = list({i["key"]: i for i in items}.values())  # the same phrase twice is one reason (accepting it covers both)
    reasons = [i.message for i in open_blocking] + unfixable
    if continuity:
        reasons += [f.message() for f in open_flags if f.message() not in reasons]
    if low:
        reasons.append(f"the critic scored {', '.join(f'{c} {critic.scores[c]}' for c in low)} (minimum {cfg.critic_min_score})")
    reasons = list(dict.fromkeys(reasons))
    review.update({"final_mechanical": report.to_dict(), "continuity": continuity.to_dict() if continuity else None,
                   "critic": critic.to_dict() if critic else None, "revised": text != drafts[chosen], "unresolved": reasons,
                   "reason_items": items})
    if accepted:
        review["accepted_reasons"] = accepted
    if advised:
        review["rewrite_advised"] = advised
    return SceneQC(text=text, chosen=chosen, review=review, reasons=reasons)
