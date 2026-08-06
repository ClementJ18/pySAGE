"""What each order type actually achieved, so a run reports rather than assumes."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Ledger"]


@dataclass
class Ledger:
    """What each order type actually achieved, so a run reports rather than assumes.

    `unpack` and `attack_move` are unverified constructors; this is how a run says which of
    them worked. Kept as counts rather than a log because the interesting question is "did
    this order type ever do anything", not "what happened at 14:32".

    **An order nothing could check is counted apart from one that worked**, because folding the
    two together turns this report into a claim it cannot support. A buff with no view marker
    leaves nothing in an observation to confirm against, so `stage_cast` can only say it sent
    one - and a measured run reported `cast buff 14/14 took effect` for a power the engine was
    refusing every time, its ready-frame frozen at 10852 while the match ran on. `14 sent, none
    of them checkable` is the same fact without the claim.
    """

    sent: dict[str, int] = field(default_factory=dict)
    worked: dict[str, int] = field(default_factory=dict)
    unverified: dict[str, int] = field(default_factory=dict)

    def record(self, label: str, ok: bool | None) -> None:
        """Count one order. `None` is "sent, and nothing here can say whether it did anything"."""
        self.sent[label] = self.sent.get(label, 0) + 1
        if ok is None:
            self.unverified[label] = self.unverified.get(label, 0) + 1
        elif ok:
            self.worked[label] = self.worked.get(label, 0) + 1

    def report(self) -> str:
        if not self.sent:
            return "  no orders were sent"
        rows = []
        for label in sorted(self.sent):
            good, total = self.worked.get(label, 0), self.sent[label]
            blind = self.unverified.get(label, 0)
            if blind == total:
                verdict = f"{total} sent, none of them checkable"
            elif good == 0:
                verdict = "never did anything"
            else:
                verdict = f"{good}/{total} took effect"
            if blind and blind != total:
                verdict += f" ({blind} unverifiable)"
            rows.append(f"    {label:<16} {verdict}")
        return "\n".join(rows)
