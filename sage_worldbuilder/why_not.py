"""Why a script did not fire: what stops the game evaluating it at all, and, once it is evaluated,
which of its conditions failed.

The first half is read from the script tree alone: a script is skipped when it or an enclosing
group is off, when it is a subroutine no one called, when its difficulty flag is clear, and until
its evaluation delay has passed (`sage_patch/docs/script-debugger.md` §2). The second half needs
the trace's condition watch (`sage_live.backends.script_trace`), which records the engine's verdict
on each watched condition and the evaluation it belonged to.

The engine evaluates the clauses in order and stops at the first that passes; inside a clause it
stops at the first condition that fails, and skips a disabled condition as if it passed. So in the
latest evaluation a condition either was judged - and carries that evaluation's number - or was
never reached, and the number tells the two apart exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from sage_live.backends.script_trace import ConditionResult
from sage_live.backends.scripts import LiveCondition, LiveScript, LiveScriptGroup
from sage_map.assets.player_scripts import Script
from sage_worldbuilder.scripting import item_text
from sage_worldbuilder.templates import TemplateKind, template

__all__ = [
    "ConditionLine",
    "Explanation",
    "Verdict",
    "condition_texts",
    "explain",
]

# The due check's difficulty test (`0x00603878`): 0 reads the Easy flag, 1 Normal, and 2 and 3
# (Brutal) both read Hard. Any other value passes.
_DIFFICULTIES = {
    0: ("easy", "easy"),
    1: ("normal", "normal"),
    2: ("hard", "hard"),
    3: ("brutal", "hard"),
}


class Verdict(Enum):
    PASSED = "passed"
    FAILED = "failed"
    # The latest evaluation stopped before it: an earlier condition in its clause failed, or an
    # earlier clause passed.
    NOT_REACHED = "not reached"
    # Skipped by the engine, which counts it as passed.
    DISABLED = "disabled"
    # Not judged since the watch began.
    UNSEEN = "not evaluated yet"


@dataclass(frozen=True)
class ConditionLine:
    clause: int
    index: int
    text: str
    verdict: Verdict
    # The last time the engine judged it, which for NOT_REACHED is an earlier evaluation.
    result: ConditionResult | None = None


@dataclass(frozen=True)
class Explanation:
    # Why the game does not evaluate the script at all; empty when it does.
    blockers: tuple[str, ...]
    # Worth knowing, but not a reason it never fires: the delay, the difficulty caveat.
    notes: tuple[str, ...]
    clauses: tuple[tuple[ConditionLine, ...], ...]
    # The latest evaluation's frame and verdict, None before the first one seen.
    frame: int | None
    passed: bool | None

    @property
    def summary(self) -> str:
        """One line: the answer to "why doesn't it fire?"."""
        if self.blockers:
            return f"Not evaluated: {self.blockers[0]}."
        if not self.clauses:
            return "It has no conditions, which the engine counts as false: only false actions run."
        if self.passed is None:
            return "Waiting for the game to evaluate it."
        if self.passed:
            return f"Its conditions passed at frame {self.frame}."
        failed = [
            line for clause in self.clauses for line in clause if line.verdict is Verdict.FAILED
        ]
        if not failed:
            return f"Its conditions were false at frame {self.frame}."
        first = failed[0]
        more = f", and {len(failed) - 1} more" if len(failed) > 1 else ""
        return f"False at frame {self.frame}: “{first.text}” failed{more}."


def condition_texts(
    script: Script | None, clauses: Sequence[Sequence[LiveCondition]]
) -> list[list[str]]:
    """Each live condition's sentence: the map's own wording when the map's script has the same
    shape as the game's, the template's name otherwise (a library script, or a map edited since
    the game loaded it)."""
    if script is not None:
        mapped = [clause.conditions for clause in script.or_conditions]
        same = len(mapped) == len(clauses) and all(
            len(ours) == len(theirs)
            and all(a.content_type == b.type for a, b in zip(ours, theirs, strict=True))
            for ours, theirs in zip(mapped, clauses, strict=True)
        )
        if same:
            return [[item_text(c, TemplateKind.CONDITION) for c in clause] for clause in mapped]
    out = []
    for clause in clauses:
        texts = []
        for condition in clause:
            found = template(TemplateKind.CONDITION, condition.type)
            name = (
                found.path[-1].rstrip(".") if found is not None else f"condition {condition.type}"
            )
            texts.append(f"NOT {name}" if condition.inverted else name)
        out.append(texts)
    return out


def _blockers(
    script: LiveScript, groups: Sequence[LiveScriptGroup], difficulty: int | None
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    notes: list[str] = []
    for group in groups:
        if not group.active:
            blockers.append(f"its group “{group.name}” is inactive in the game")
        if group.subroutine:
            blockers.append(
                f"its group “{group.name}” is a subroutine, run only when a script calls it"
            )
    if script.subroutine:
        blockers.append("it is a subroutine, run only when a script calls it")
    if not script.active:
        if script.one_shot and script.authored_active:
            blockers.append("it has already fired, and a one-shot switches itself off")
        elif not script.authored_active:
            blockers.append("the map makes it inactive, and nothing has enabled it")
        else:
            blockers.append("it has been disabled in the game")
    if difficulty in _DIFFICULTIES:
        name, flag = _DIFFICULTIES[difficulty]
        if not getattr(script, flag):
            blockers.append(f"it is off on {name} difficulty")
        # The due check asks the evaluated player's AI first; this is only the game's setting.
        if not (script.easy and script.normal and script.hard):
            notes.append("An AI player's scripts go by that AI's difficulty, not the game's.")
    return blockers, notes


def explain(
    script: LiveScript,
    groups: Sequence[LiveScriptGroup],
    clauses: Sequence[Sequence[LiveCondition]],
    results: dict[int, ConditionResult],
    texts: Sequence[Sequence[str]],
    frame: int,
    rate: int,
    difficulty: int | None = None,
) -> Explanation:
    """Why `script` has or has not fired, from one poll of the game.

    `groups` encloses the script, outermost first; `clauses` are its live conditions and `texts`
    their sentences, clause for clause (`condition_texts`); `results` is the condition watch.
    """
    blockers, notes = _blockers(script, groups, difficulty)
    if not blockers and script.next_frame > frame:
        wait = (script.next_frame - frame) / max(rate, 1)
        notes.insert(0, f"Evaluated again at frame {script.next_frame}, in {wait:.1f} s.")

    judged = [results[c.address] for clause in clauses for c in clause if c.address in results]
    latest = max((result.evaluation for result in judged), default=None)
    lines: list[tuple[ConditionLine, ...]] = []
    passed: bool | None = None
    for clause_index, clause in enumerate(clauses):
        row: list[ConditionLine] = []
        # An empty clause never passes; one whose conditions are all disabled always does.
        clause_passed = latest is not None and bool(clause)
        for index, condition in enumerate(clause):
            result = results.get(condition.address)
            if not condition.enabled:
                verdict = Verdict.DISABLED
            elif result is None:
                verdict = Verdict.UNSEEN
                clause_passed = False
            elif result.evaluation == latest:
                verdict = Verdict.PASSED if result.passed else Verdict.FAILED
                clause_passed = clause_passed and result.passed
            else:
                verdict = Verdict.NOT_REACHED
                clause_passed = False
            text = texts[clause_index][index] if clause_index < len(texts) else ""
            row.append(ConditionLine(clause_index, index, text, verdict, result))
        lines.append(tuple(row))
        if clause_passed:
            passed = True
    if latest is not None and passed is None:
        passed = False
    frame_seen = next((result.frame for result in judged if result.evaluation == latest), None)
    return Explanation(tuple(blockers), tuple(notes), tuple(lines), frame_seen, passed)
