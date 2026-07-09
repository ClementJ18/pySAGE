"""The lint rule framework: a `Rule` produces `Diagnostic`s over a loaded `Game`. Each
subclass with a `code` auto-registers; `run_rules` isolates a faulty rule so it cannot
abort the rest of the run.

A rule may opt out of the default run by setting `default = False`: it then runs only when the
caller asks for it (the CLI's `--assets`/`--select`). The missing-file rules use this - without
the base-game archives loaded they would report every base asset as missing, so they are opt-in
rather than flooding a plain `lint`.

An opt-in rule that also sets `assets = True` is one `--assets` turns on as a group (the
asset-file rules); an opt-in rule that leaves `assets = False` is reachable only by naming it in
`--select` (e.g. `unused-object`), so `--assets` does not silently drag it in."""

from collections.abc import Iterable, Iterator

from sage_ini.model.game import Game
from sage_ini.parser.diagnostics import Diagnostic, Diagnostics
from sage_ini.parser.location import Span

RULES: list[type["Rule"]] = []


class Rule:
    code: str = ""  # set by a concrete subclass to enable auto-registration
    default: bool = True  # whether a plain run (no --select/--assets) includes this rule
    assets: bool = False  # whether --assets turns this (opt-in) rule on as part of the asset group

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.code:
            RULES.append(cls)

    def check(self, game: Game) -> Iterator[Diagnostic]:
        raise NotImplementedError


def default_rules() -> list[type["Rule"]]:
    """The rules a plain run executes: every registered rule except the opt-in ones."""
    return [rule for rule in RULES if rule.default]


def run_rules(game: Game, rules: Iterable[type[Rule]] | None = None) -> Diagnostics:
    """Run `rules` over `game`, collecting diagnostics. `None` runs the default set (every
    registered rule except those marked `default = False`); pass an explicit list to run exactly
    those, opt-in rules included."""
    diagnostics = Diagnostics()
    for rule_cls in default_rules() if rules is None else rules:
        rule = rule_cls()
        try:
            diagnostics.items.extend(rule.check(game))
        except Exception as exc:  # noqa: BLE001 - a faulty rule must not abort the others
            diagnostics.add(
                "rule-error", f"{rule_cls.__name__} failed: {exc}", Span("<rules>", 1, 1)
            )
    return diagnostics
