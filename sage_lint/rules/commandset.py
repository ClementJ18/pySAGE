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

# The ControlBar draws at most this many buttons at once - a fixed-size UI array in the engine
# (ControlBar singleton, the 33-slot command-button arrays). `InitialVisible` feeds that count,
# so a value above it can never be honoured on screen. This ceiling is unaffected by the
# CommandSet 33->64 data-limit patch, which only enlarges how many buttons a set may *define*.
MAX_VISIBLE_BUTTONS = 33

# The `m_command[]` array size after the 33->64 engine patch (see sage_patch).
# A `PUSH_VISIBLE_COMMAND_RANGE` window reaching index >= this reads past the array into the
# object's count/flag fields and the game dereferences that value as a button pointer -> crash.
MAX_COMMANDSET_SLOTS = 64


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


class InitialVisibleLimitRule(Rule):
    """A CommandSet whose `InitialVisible` exceeds the on-screen button ceiling. The ControlBar
    has a fixed number of button widgets (33); asking for more can never draw
    them, and in practice the over-large count breaks the bar's layout (buttons past the limit go
    missing). The engine patch that lifts the *data* limit to 64 does not raise this display
    ceiling, so the rule holds regardless. WARNING - it converts fine, the bar just misbehaves."""

    code = "initial-visible-over-max"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for commandset in game.commandsets.values():
            try:
                value = commandset.InitialVisible
            except (ValueError, KeyError, TypeError, IndexError):
                continue  # a non-numeric value is the conversion pass's job, not ours
            if value is None or value <= MAX_VISIBLE_BUTTONS:
                continue
            yield Diagnostic(
                code=self.code,
                message=(
                    f"CommandSet {commandset.name!r} sets InitialVisible = {value}, above the "
                    f"{MAX_VISIBLE_BUTTONS}-button on-screen limit; buttons past "
                    f"{MAX_VISIBLE_BUTTONS} cannot be shown."
                ),
                span=commandset._field_spans.get("InitialVisible", commandset.span),
                severity=Severity.WARNING,
                extra={
                    "type": "CommandSet",
                    "commandset": commandset.name,
                    "key": "InitialVisible",
                    "value": value,
                    "maximum": MAX_VISIBLE_BUTTONS,
                },
            )


def _int_field(button, key: str) -> int:
    """A CommandButton's integer field as an int, treating unset/non-numeric as 0."""
    try:
        value = getattr(button, key)
    except (ValueError, KeyError, TypeError, IndexError):
        return 0
    return value if isinstance(value, int) else 0


class PushCommandRangeOverflowRule(Rule):
    """A `PUSH_VISIBLE_COMMAND_RANGE` button whose `CommandRangeStart + CommandRangeCount` reaches
    past the buttons of the CommandSet it sits in. That window paints slots of the current set;
    `CommandRangeStart` is a 0-based slot index, so the range covers slots
    `Start+1 .. Start+Count`. Overshooting the set's highest slot paints empty positions, and -
    worse - reaching slot 64+1 runs off the `m_command[]` array into the
    object's count field, which the engine then dereferences as a button pointer and crashes
    (the exact `PUSH_VISIBLE_COMMAND_RANGE` crash documented in sage_patch).

    ERROR when the window runs off the array end (a hard crash); WARNING when it only overshoots
    into empty slots of the same set."""

    code = "command-range-overflow"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for commandset in game.commandsets.values():
            slots = [int(slot) for slot in commandset._fields if slot.isdigit()]
            if not slots:
                continue
            highest_slot = max(slots)  # 1-based; = number of array positions the set uses
            for slot, value in commandset._fields.items():
                if not slot.isdigit():
                    continue
                if isinstance(value, list):
                    value = value[-1]  # a repeated slot keeps only its last button
                if not isinstance(value, str) or value.strip().lower() in _NONE_SENTINELS:
                    continue
                button = game.lookup("commandbuttons", value.strip())[0]
                if button is None or not _is_push_visible_range(button):
                    continue
                start = _int_field(button, "CommandRangeStart")
                count = _int_field(button, "CommandRangeCount")
                end = start + count  # exclusive; last slot index read is end-1 (0-based)
                if end <= highest_slot:
                    continue  # stays within the set's defined slots
                crashes = end > MAX_COMMANDSET_SLOTS
                detail = (
                    f"runs off the {MAX_COMMANDSET_SLOTS}-slot command array (reaching slot "
                    f"{end}) into the set's count field - the engine dereferences that as a "
                    f"button pointer and crashes"
                    if crashes
                    else f"overshoots the set's highest slot {highest_slot} into empty positions"
                )
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"CommandButton {button.name!r} (PUSH_VISIBLE_COMMAND_RANGE) in CommandSet "
                        f"{commandset.name!r} shows slots {start + 1}..{end} "
                        f"(CommandRangeStart {start} + CommandRangeCount {count}), which {detail}. "
                        f"Keep CommandRangeStart + CommandRangeCount <= {highest_slot}."
                    ),
                    span=commandset._field_spans.get(slot, commandset.span),
                    severity=Severity.ERROR if crashes else Severity.WARNING,
                    extra={
                        "type": "CommandSet",
                        "commandset": commandset.name,
                        "key": slot,
                        "name": button.name,
                        "start": start,
                        "count": count,
                        "highest_slot": highest_slot,
                        "crashes": crashes,
                    },
                )


def _is_push_visible_range(button) -> bool:
    """Whether a resolved CommandButton pages the bar (`Command = PUSH_VISIBLE_COMMAND_RANGE`)."""
    try:
        return button.Command is CommandTypes.PUSH_VISIBLE_COMMAND_RANGE
    except Exception:  # noqa: BLE001 - a malformed Command is the converter's diagnostic, not ours
        return False


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
