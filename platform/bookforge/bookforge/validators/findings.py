"""The common result of every validator."""

from dataclasses import dataclass, field

HARD, SOFT = "hard", "soft"


@dataclass
class Finding:
    stage: str  # ledger | acts | chapters | scenes | state | prose | research
    code: str  # stable machine name, e.g. "once_only_repeated"
    severity: str  # hard | soft
    message: str  # written for a model to act on and for the author to read
    items: list[str] = field(default_factory=list)  # ids the finding concerns (event, chapter, scene...)
    evidence: list[str] = field(default_factory=list)  # short quotations

    def to_dict(self) -> dict:
        return {"stage": self.stage, "code": self.code, "severity": self.severity, "message": self.message,
                "items": self.items, "evidence": self.evidence}

    def line(self) -> str:
        where = f" [{', '.join(self.items[:6])}{'...' if len(self.items) > 6 else ''}]" if self.items else ""
        return f"{self.code}{where}: {self.message}"


def hard(stage: str, code: str, message: str, items=(), evidence=()) -> Finding:
    return Finding(stage, code, HARD, message, list(items), list(evidence))


def soft(stage: str, code: str, message: str, items=(), evidence=()) -> Finding:
    return Finding(stage, code, SOFT, message, list(items), list(evidence))


def summarize(findings: list[Finding]) -> dict:
    return {"hard": sum(f.severity == HARD for f in findings), "soft": sum(f.severity == SOFT for f in findings),
            "codes": sorted({f.code for f in findings})}
