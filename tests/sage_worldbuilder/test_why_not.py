"""Why a script did not fire, from a script tree and the condition watch - no game needed.

The verdicts lean on how the engine walks the conditions (`0x0060930F`): clauses in order until one
passes, conditions in a clause until one fails, a disabled condition skipped as a pass, an empty
clause never passing and a script with no clauses never true.
"""

from __future__ import annotations

from dataclasses import replace

from sage_live.backends.script_trace import ConditionResult
from sage_live.backends.scripts import LiveCondition, LiveScript, LiveScriptGroup
from sage_worldbuilder.scripting import new_item, new_or_condition, new_script
from sage_worldbuilder.templates import TemplateKind, template
from sage_worldbuilder.why_not import Verdict, condition_texts, explain

COUNTER, FLAG, TRUE, TIMER = 1, 2, 3, 4


def live(**overrides: object) -> LiveScript:
    script = LiveScript(
        name="Attack",
        address=0x1000,
        active=True,
        authored_active=True,
        one_shot=True,
        subroutine=False,
        easy=True,
        normal=True,
        hard=True,
        delay_seconds=0,
        sequential=False,
        next_frame=0,
    )
    return replace(script, **overrides)  # type: ignore[arg-type]


def condition(address: int, kind: int = COUNTER, enabled: bool = True) -> LiveCondition:
    return LiveCondition(address, kind, enabled, inverted=False)


def judged(evaluation: int, passed: bool, frame: int = 100) -> ConditionResult:
    return ConditionResult(evaluation, frame, passed, int(passed), int(not passed))


def names(clauses) -> list[list[str]]:
    return [[f"c{c.address:x}" for c in clause] for clause in clauses]


def verdicts(explanation) -> list[list[Verdict]]:
    return [[line.verdict for line in clause] for clause in explanation.clauses]


def run(clauses, results, script: LiveScript | None = None, **kwargs):
    kwargs.setdefault("frame", 100)
    kwargs.setdefault("rate", 5)
    return explain(script or live(), (), clauses, results, names(clauses), **kwargs)


def test_the_first_failure_in_a_clause_hides_the_rest_of_it() -> None:
    clauses = ((condition(0xA), condition(0xB), condition(0xC)),)
    # The third condition passed once, in an older evaluation.
    results = {0xA: judged(7, True), 0xB: judged(7, False), 0xC: judged(3, True, frame=40)}
    explanation = run(clauses, results)
    assert verdicts(explanation) == [[Verdict.PASSED, Verdict.FAILED, Verdict.NOT_REACHED]]
    assert explanation.passed is False and explanation.frame == 100
    assert explanation.summary == "False at frame 100: “cb” failed."
    assert explanation.clauses[0][2].result == judged(3, True, frame=40)


def test_a_later_clause_can_pass_after_an_earlier_one_fails() -> None:
    clauses = ((condition(0xA),), (condition(0xB), condition(0xC)))
    results = {0xA: judged(7, False), 0xB: judged(7, True), 0xC: judged(7, True)}
    explanation = run(clauses, results)
    assert verdicts(explanation) == [[Verdict.FAILED], [Verdict.PASSED, Verdict.PASSED]]
    assert explanation.passed is True
    assert explanation.summary == "Its conditions passed at frame 100."


def test_a_passing_clause_leaves_the_later_ones_unreached() -> None:
    clauses = ((condition(0xA),), (condition(0xB),), (condition(0xC),))
    results = {0xA: judged(7, True), 0xB: judged(2, False)}
    explanation = run(clauses, results)
    assert verdicts(explanation) == [[Verdict.PASSED], [Verdict.NOT_REACHED], [Verdict.UNSEEN]]
    assert explanation.passed is True


def test_every_failing_clause_is_counted_in_the_summary() -> None:
    clauses = ((condition(0xA),), (condition(0xB),))
    results = {0xA: judged(7, False), 0xB: judged(7, False)}
    assert run(clauses, results).summary == "False at frame 100: “ca” failed, and 1 more."


def test_a_disabled_condition_counts_as_passed() -> None:
    clauses = ((condition(0xA, enabled=False), condition(0xB)),)
    explanation = run(clauses, {0xB: judged(7, True)})
    assert verdicts(explanation) == [[Verdict.DISABLED, Verdict.PASSED]]
    assert explanation.passed is True


def test_an_empty_clause_never_passes() -> None:
    clauses = ((), (condition(0xB),))
    explanation = run(clauses, {0xB: judged(7, False)})
    assert explanation.passed is False


def test_before_any_evaluation_it_waits() -> None:
    explanation = run(((condition(0xA),),), {})
    assert verdicts(explanation) == [[Verdict.UNSEEN]]
    assert explanation.passed is None
    assert explanation.summary == "Waiting for the game to evaluate it."


def test_no_conditions_is_false_to_the_engine() -> None:
    assert "counts as false" in run((), {}).summary


def test_what_stops_it_being_evaluated_comes_first() -> None:
    fired = run((), {}, script=live(active=False))
    assert fired.summary == (
        "Not evaluated: it has already fired, and a one-shot switches itself off."
    )
    off = run((), {}, script=live(active=False, authored_active=False, one_shot=False))
    assert off.blockers == ("the map makes it inactive, and nothing has enabled it",)
    sub = run((), {}, script=live(subroutine=True))
    assert sub.blockers == ("it is a subroutine, run only when a script calls it",)


def test_an_enclosing_group_can_stop_it() -> None:
    group = LiveScriptGroup("Waves", 0x9000, active=False, subroutine=False, scripts=(), groups=())
    explanation = explain(live(), (group,), (), {}, [], 100, 5)
    assert explanation.blockers == ("its group “Waves” is inactive in the game",)


def test_brutal_reads_the_hard_flag() -> None:
    explanation = run((), {}, script=live(hard=False), difficulty=3)
    assert explanation.blockers == ("it is off on brutal difficulty",)
    assert explanation.notes == (
        "An AI player's scripts go by that AI's difficulty, not the game's.",
    )
    assert run((), {}, script=live(hard=False), difficulty=1).blockers == ()


def test_the_delay_is_a_note_not_a_blocker() -> None:
    explanation = run((), {}, script=live(delay_seconds=30, next_frame=150), frame=100)
    assert explanation.blockers == ()
    assert explanation.notes == ("Evaluated again at frame 150, in 10.0 s.",)


def map_condition(kind: int):
    found = template(TemplateKind.CONDITION, kind)
    assert found is not None
    return new_item(found)


def test_the_map_wording_is_used_when_the_shapes_agree() -> None:
    script = new_script("Attack")
    script.or_conditions = [new_or_condition()]
    script.or_conditions[0].conditions = [map_condition(TRUE), map_condition(TIMER)]
    clauses = ((condition(0xA, TRUE), condition(0xB, TIMER)),)
    texts = condition_texts(script, clauses)
    assert texts[0][0] == "True."
    assert texts[0][1].startswith("Timer")
    # A map edited since the game loaded it: the game's own shape, named by template.
    fallback = condition_texts(script, ((condition(0xA, FLAG),),))
    assert fallback == [["Flag compared to a value"]]


def test_an_inverted_condition_is_named_with_not() -> None:
    clauses = ((LiveCondition(0xA, TRUE, True, inverted=True),),)
    assert condition_texts(None, clauses) == [["NOT True"]]
