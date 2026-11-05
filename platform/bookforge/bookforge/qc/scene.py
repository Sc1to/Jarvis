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

from dataclasses import dataclass, field

from ..bible.models import Scene
from ..errors import LayerError
from .continuity import ContinuityReport, check_continuity
from .critic import CriticReport, critic_flags, run_critic
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
    verdict = choose_draft(ctx, scene, {n: drafts[n] for n in candidates}, {n: reports[n] for n in candidates})
    return verdict.winner, {"candidates": candidates, "wins": verdict.wins, "pairs": verdict.pairs, "error": verdict.error}


def _mechanical_flags(report: MechanicalReport) -> tuple[list[Flag], list[str]]:
    fixable, unfixed = [], []
    for i in report.blocking:
        if i.code in FIXABLE_MECHANICAL and i.start is not None:
            fixable.append(Flag("mechanical", i.code, i.message, quote="", start=i.start, end=i.end))
        else:
            unfixed.append(i.message)
    return fixable, unfixed


def settle_scene(ctx, scene: Scene, scenes: list[Scene], drafts: dict[str, str], mech: CheckContext) -> SceneQC:
    cfg = ctx.project.config.qc
    drafts_reports = {n: check_scene(t, mech) for n, t in drafts.items()}
    chosen, judge = _choose(ctx, scene, drafts, drafts_reports)
    text = drafts[chosen]
    review: dict = {"chosen": chosen, "mechanical": {n: r.to_dict() for n, r in drafts_reports.items()},
                    "judge": judge, "rounds": []}

    critic: CriticReport | None = None
    critic_given_up = False
    continuity: ContinuityReport | None = None
    report = drafts_reports[chosen]
    unfixable: list[str] = []
    for r in range(cfg.max_revision_rounds + 1):
        report = check_scene(text, mech)
        flags, unfixable = _mechanical_flags(report)
        continuity = None
        if not report.blocking and cfg.continuity_check:
            continuity = check_continuity(ctx, scene, scenes, text)
            for f in continuity.flags:
                if f.fixable:
                    flags.append(Flag("continuity", "contradiction", f.message(), quote=f.evidence))
                else:
                    unfixable.append(f.message())
        cheap_ok = not report.blocking and not (continuity and continuity.flags)
        if cheap_ok and cfg.critic_check and not critic_given_up and (critic is None or critic.needs_work(cfg.critic_min_score)):
            critic = run_critic(ctx, scene, text)
            if critic.error:
                critic_given_up = True
            elif critic.needs_work(cfg.critic_min_score):
                flags += critic_flags(ctx.project, critic)
        record = {"round": r, "mechanical_blocking": [i.message for i in report.blocking],
                  "continuity_flags": [f.message() for f in continuity.flags] if continuity else [],
                  "critic_lowest": critic.lowest if critic and critic.scores else None, "revisions": []}
        review["rounds"].append(record)
        if not flags or r == cfg.max_revision_rounds:
            break
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

    reasons = [i.message for i in report.blocking] + unfixable
    if continuity:
        reasons += [f.message() for f in continuity.flags if f.message() not in reasons]
    if critic and critic.needs_work(cfg.critic_min_score):
        low = [c for c, v in critic.scores.items() if v < cfg.critic_min_score]
        reasons.append(f"the critic scored {', '.join(f'{c} {critic.scores[c]}' for c in low)} (minimum {cfg.critic_min_score})")
    reasons = list(dict.fromkeys(reasons))
    review.update({"final_mechanical": report.to_dict(), "continuity": continuity.to_dict() if continuity else None,
                   "critic": critic.to_dict() if critic else None, "revised": text != drafts[chosen], "unresolved": reasons})
    return SceneQC(text=text, chosen=chosen, review=review, reasons=reasons)
