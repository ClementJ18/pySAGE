"""Findings, and how a run is summarised.

Kept apart from `watch` because the counts are the part a reader has to be able to trust: a run
that judged nothing and a run that judged everything and found nothing both print "no violations"
unless the report insists on saying how much it actually looked at.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field

from sage_verify.rules import Verdict

__all__ = ["Finding", "Report"]


@dataclass(frozen=True)
class Finding:
    """One order that could not be accounted for by what its issuer could see."""

    frame: int
    player: int
    player_name: str
    order_type: int
    order_name: str
    confidence: str
    reason: str
    target_object: int | None = None
    target_position: tuple[float, float, float] | None = None

    def line(self) -> str:
        where = (
            f"object {self.target_object}"
            if self.target_object is not None
            else f"({self.target_position[0]:.0f}, {self.target_position[1]:.0f})"
            if self.target_position is not None
            else "?"
        )
        return (
            f"  frame {self.frame:>6}  {self.player_name:<16} {self.order_name:<34} "
            f"{where:<16} [{self.confidence}]\n      {self.reason}"
        )


@dataclass
class Report:
    """Everything one run saw, findings and non-findings alike."""

    findings: list[Finding] = field(default_factory=list)
    #: `{outcome -> count}` over every order that carried a target.
    outcomes: Counter[str] = field(default_factory=Counter)
    #: Why orders went unjudged, so a run that checked nothing says so in detail.
    unjudged_reasons: Counter[str] = field(default_factory=Counter)
    orders_seen: int = 0
    targeted_orders: int = 0
    samples: int = 0
    first_frame: int | None = None
    last_frame: int | None = None
    seat_notes: list[str] = field(default_factory=list)

    def record(self, verdict: Verdict, finding: Finding | None) -> None:
        self.outcomes[verdict.outcome] += 1
        if verdict.outcome == "unjudged":
            self.unjudged_reasons[verdict.reason.split(" - ")[0]] += 1
        if finding is not None:
            self.findings.append(finding)

    @property
    def coverage(self) -> float:
        """The fraction of targeted orders that were actually judged. **The number that decides
        whether "no violations" means anything.**"""
        judged = self.outcomes["ok"] + self.outcomes["violation"]
        return judged / self.targeted_orders if self.targeted_orders else 0.0

    def summary(self) -> str:
        frames = (
            f"{self.first_frame}..{self.last_frame}" if self.first_frame is not None else "none"
        )
        lines = [
            "",
            f"followed frames {frames} over {self.samples} samples",
            f"{self.orders_seen} orders, {self.targeted_orders} of them targeted; "
            f"judged {self.outcomes['ok'] + self.outcomes['violation']} "
            f"({self.coverage:.0%} coverage)",
        ]
        for note in self.seat_notes:
            lines.append(f"  note: {note}")
        if self.outcomes["unjudged"]:
            lines.append(f"{self.outcomes['unjudged']} unjudged:")
            for reason, count in self.unjudged_reasons.most_common():
                lines.append(f"  {count:>5}  {reason}")
        if not self.findings:
            lines.append("")
            lines.append("no violations found.")
            if self.coverage < 0.5:
                lines.append(
                    "  BUT coverage is low - this is 'not checked', not 'clean'. Attach earlier "
                    "in the playback and raise --max-lag."
                )
        else:
            high = sum(1 for f in self.findings if f.confidence == "high")
            lines.append("")
            lines.append(
                f"{len(self.findings)} violation(s): {high} high confidence, "
                f"{len(self.findings) - high} low."
            )
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "findings": [asdict(f) for f in self.findings],
                "outcomes": dict(self.outcomes),
                "unjudged_reasons": dict(self.unjudged_reasons),
                "orders_seen": self.orders_seen,
                "targeted_orders": self.targeted_orders,
                "samples": self.samples,
                "first_frame": self.first_frame,
                "last_frame": self.last_frame,
                "coverage": self.coverage,
                "seat_notes": self.seat_notes,
            },
            indent=2,
        )
