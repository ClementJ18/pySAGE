"""Rules over CommandSet button slots: references that resolve to no CommandButton, and a
REVIVE button wired into two slots of the same set."""

from collections.abc import Iterator

from sage_ini.model.enums import CommandTypes
from sage_ini.model.game import Game
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.suggest import suggestion_hint
from sage_lint.rules.base import Rule

# An empty slot is written `NONE` (or left blank); that is the engine's "no button here", not
# a dangling reference, so it is never flagged.
_NONE_SENTINELS = frozenset({"", "none"})


class CommandSetButtonRule(Rule):
    """A numbered CommandSet slot (`3 = Command_Foo`) naming a CommandButton no definition
    declares: in-game the slot is empty - the button silently never appears - a content bug,
    usually a typo or a button renamed in one place but not the other. `NONE` slots are the
    engine's "no button here" and are left alone. CommandButtons are always defined in the
    data, so unlike art/audio references this resolves authoritatively (WARNING, not INFO)."""

    code = "dangling-commandbutton"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        buttons = game.commandbuttons
        for commandset in game.commandsets.values():
            for slot, value in commandset._fields.items():
                if not slot.isdigit():
                    continue
                if isinstance(value, list):
                    value = value[-1]  # a repeated slot keeps only its last button
                if not isinstance(value, str) or value.strip().lower() in _NONE_SENTINELS:
                    continue
                name = value.strip()
                if game.lookup("commandbuttons", name)[0] is not None:
                    continue  # resolves (case-insensitively, the way the engine looks it up)
                hint, suggestion = suggestion_hint(name, buttons)
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"CommandSet {commandset.name!r} slot {slot} references CommandButton "
                        f"{name!r}, which no definition declares.{hint}"
                    ),
                    span=commandset._field_spans.get(slot, commandset.span),
                    severity=Severity.WARNING,
                    extra={
                        "name": name,
                        "table": "commandbuttons",
                        "type": "CommandSet",
                        "key": slot,
                        "suggestion": suggestion,
                    },
                )


def _is_revive(button) -> bool:
    """Whether a resolved CommandButton is a REVIVE button (`Command = REVIVE`). Reviving a
    fallen hero is index-based, so the same revive button never belongs in two slots."""
    try:
        return button.Command is CommandTypes.REVIVE
    except Exception:  # noqa: BLE001 - a malformed Command is the converter's diagnostic, not ours
        return False


class DuplicateReviveButtonRule(Rule):
    """The same REVIVE CommandButton wired into two slots of one CommandSet. Each revive button
    is bound to a fixed hero slot index, so listing it twice makes two GUI buttons fight over the
    same hero - one silently never works. This is a content bug (usually a copy-paste when adding
    a hero), so it is a WARNING; empty/unresolved slots and non-revive duplicates are left alone."""

    code = "duplicate-revive-button"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for commandset in game.commandsets.values():
            # button name -> the slots that name it, in slot order. Keyed by the display spelling
            # of its first sighting; matched case-insensitively (the way the engine resolves).
            occurrences: dict[str, list[str]] = {}
            display: dict[str, str] = {}
            for slot, value in commandset._fields.items():
                if not slot.isdigit():
                    continue
                for name in value if isinstance(value, list) else [value]:
                    if not isinstance(name, str) or name.strip().lower() in _NONE_SENTINELS:
                        continue
                    name = name.strip()
                    button = game.lookup("commandbuttons", name)[0]
                    if button is None or not _is_revive(button):
                        continue
                    key = name.casefold()
                    display.setdefault(key, name)
                    occurrences.setdefault(key, []).append(slot)

            for key, slots in occurrences.items():
                if len(slots) < 2:
                    continue
                name = display[key]
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"CommandSet {commandset.name!r} wires REVIVE button {name!r} into "
                        f"{len(slots)} slots ({', '.join(slots)}); a revive button belongs in only "
                        f"one slot, or every one but the first is dead."
                    ),
                    span=commandset._field_spans.get(slots[1], commandset.span),
                    severity=Severity.WARNING,
                    extra={
                        "name": name,
                        "type": "CommandSet",
                        "commandset": commandset.name,
                        "slots": slots,
                    },
                )
