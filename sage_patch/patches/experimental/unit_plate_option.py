"""Add a 20th row to the shell Options screen and make one model name obey it, so Edain's unit
plates become a player setting instead of a submod.

Three hooks and one cave: the options screen shows the row, `AptOptions::Save` writes its key
alongside the six stock ones (spliced in before `UserPreferences::write` at `0x009204DC`), and the
`Model =` parser substitutes `None` for `unit_plate` unless the option is on. Needs a matching
gadget in `Options.apt`; takes effect at the next launch.

Derivation: `../../docs/options-menu-rows.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
    APT_INIT_GADGETS_LADDER,
    APT_INIT_GADGETS_LADDER_BYTES,
    APT_INIT_GADGETS_LADDER_HOOK,
    APT_INIT_GADGETS_LADDER_HOOK_BYTES,
    APT_INIT_GADGETS_RESOLUTION_ARM,
    APT_OPTIONS_SAVE,
    APT_OPTIONS_SAVE_BYTES,
    APT_OPTIONS_SAVE_FLUSH,
    APT_OPTIONS_SAVE_FLUSH_BYTES,
    APT_OPTIONS_SAVE_PREFS_EBP,
    APT_OPTIONS_SAVE_RESUME,
    MODEL_FIELD_PARSER,
    MODEL_FIELD_PARSER_BYTES,
    MODEL_FIELD_STORE,
    MODEL_FIELD_STORE_BYTES,
    MODEL_FIELD_STORE_RESUME,
    OPTION_PREFERENCES_CTOR,
    OPTION_PREFERENCES_CTOR_BYTES,
    OPTION_PREFERENCES_DTOR,
    OPTION_PREFERENCES_DTOR_BYTES,
    OPTION_PREFERENCES_GET_BOOL,
    OPTION_PREFERENCES_GET_BOOL_BYTES,
    STRICMP,
    USER_PREFERENCES_WRITE,
)
from ...asm import JE, JNE, JNZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, jmp_rel32, va_to_offset
from ..utils.option_row import emit_arm_body, emit_read, emit_read_fresh, emit_save_body

__all__ = [
    "ANCHORS",
    "DEFAULT_GADGET",
    "DEFAULT_KEY",
    "DEFAULT_MODEL",
    "SECTION_NAME",
    "UnitPlateOptionPatch",
    "build_cave",
]

SECTION_NAME = ".uplate"  # <= 8 chars: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds the string
# literals, the remembered gadget and the one-byte preference cache, all written at runtime.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The model name that disappears when the preference is off.
DEFAULT_MODEL = "unit_plate"

#: The `Options.ini` key that controls it. Absent counts as off, so an untouched `Options.ini`
#: reproduces the shipped game exactly.
DEFAULT_KEY = "ShowUnitPlates"

#: The gadget instance name the movie has to give the checkbox. The `Options::` prefix is the
#: convention every stock row follows; the ladder compares the whole string, so it is only a
#: convention, but a row that breaks it would be the only one.
DEFAULT_GADGET = "Options::UnitPlates"

#: What the engine writes in a `ModelConditionState` that draws nothing. Spelled as
#: `unit_plate_remover.inc` spells it, so the substituted state is identical to the one 78 shipped
#: child objects already carry.
_NONE = "None"

#: How a boolean preference is spelled in `Options.ini`. `read` compares against the engine's own
#: `YES_STRING`; these two are what the save path *writes*.
_YES = "yes"
_NO = "no"

#: The cave's mutable head. `state` is a tri-state - 0 unresolved, 1 off, 2 on - because "off" and
#: "not yet asked" are both zero otherwise, and asking costs a full parse of `Options.ini`.
#: `gadget` is the checkbox the row remembered, and `owner` the `AptOptions` it belonged to, so a
#: `Save` for some other screen cannot reach a freed pointer.
_STATE_OFF = 0
_GADGET_OFF = 4
_OWNER_OFF = 8
_STRINGS_OFF = 12

#: Everything the cave calls or replicates and does not rewrite. `OPTION_PREFERENCES_GET_BOOL` is
#: the routine this patch clones with a different key, and the two hook windows are checked so a
#: build that laid the ladder or the save out differently fails here rather than on a wrong answer.
ANCHORS = {
    MODEL_FIELD_PARSER: MODEL_FIELD_PARSER_BYTES,
    OPTION_PREFERENCES_CTOR: OPTION_PREFERENCES_CTOR_BYTES,
    OPTION_PREFERENCES_DTOR: OPTION_PREFERENCES_DTOR_BYTES,
    OPTION_PREFERENCES_GET_BOOL: OPTION_PREFERENCES_GET_BOOL_BYTES,
    APT_INIT_GADGETS_LADDER: APT_INIT_GADGETS_LADDER_BYTES,
    APT_OPTIONS_SAVE: APT_OPTIONS_SAVE_BYTES,
}

#: `(address, stock bytes)` for each of the three hooks, so `apply` writes exactly what `verify`
#: asserts and neither can drift from the other.
_HOOKS = (
    (MODEL_FIELD_STORE, MODEL_FIELD_STORE_BYTES, "model"),
    (APT_INIT_GADGETS_LADDER_HOOK, APT_INIT_GADGETS_LADDER_HOOK_BYTES, "arm"),
    (APT_OPTIONS_SAVE_FLUSH, APT_OPTIONS_SAVE_FLUSH_BYTES, "save"),
)

_STRINGS = ("model", "none", "key", "gadget", "yes", "no")


def _literals(model: str, key: str, gadget: str) -> tuple[bytes, dict[str, int]]:
    """The cave's data block, and the offset of each string inside the section."""
    blob = bytearray(_STRINGS_OFF)  # the state byte, the gadget and its owner
    offsets: dict[str, int] = {}
    for name, text in zip(_STRINGS, (model, _NONE, key, gadget, _YES, _NO), strict=True):
        offsets[name] = len(blob)
        blob += text.encode("ascii") + b"\x00"
    while len(blob) % 4:
        blob += b"\x00"
    return bytes(blob), offsets


def build_cave(
    base_va: int,
    model: str = DEFAULT_MODEL,
    key: str = DEFAULT_KEY,
    gadget: str = DEFAULT_GADGET,
) -> Asm:
    """The cave, laid out at the address it will occupy, as an `Asm` whose labels name each hook.

    Data first, at offsets known before a byte of code is laid out, because the code has to push
    the literals' absolute addresses - `command-point-upkeep` puts its block key and row array in
    front of its code for the same reason.
    """
    data, at = _literals(model, key, gadget)
    a = Asm(base_va)
    a.emit(data)  # never executed; the entry points are the labels below

    _emit_model_hook(a, base_va + at["model"], base_va + at["none"])
    _emit_arm(a, base_va, base_va + at["gadget"])
    _emit_save(a, base_va, base_va + at["key"], base_va + at["yes"], base_va + at["no"])
    _emit_enabled(a, base_va + _STATE_OFF)
    emit_read_fresh(a)
    emit_read(a, base_va + at["key"])
    a.finish()  # resolve the internal branches, so `label_va` describes a real layout
    return a


def _emit_model_hook(a: Asm, model_va: int, none_va: int) -> None:
    """The six bytes lifted out of `MODEL_FIELD_STORE`, with the substitution in front of them.

    Entered with the parser's own frame still live, so `[ebp-0x10]` is the model-name token the
    stock code is about to copy into an `AsciiString`. `pushad`/`popad` spans the decision because
    the parser holds the target object in `ebx` and its own state in `esi`/`edi` across this
    point; the substitution is written to memory, which `popad` does not undo.
    """
    a.label("model")
    a.emit(0x60)  # pushad
    a.call("enabled")  # call .enabled            ; al = should plates draw?
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNZ, "model_keep")  # jnz .keep         ; on -> leave the name alone
    a.emit(0x68, struct.pack("<I", model_va))  # push <"unit_plate">
    a.emit(b"\xff\x75\xf0")  # push dword [ebp-0x10]   ; the parsed name
    a.call_absolute(STRICMP)  # call stricmp
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "model_keep")  # jne .keep         ; a different model -> untouched
    a.emit(b"\xc7\x45\xf0", struct.pack("<I", none_va))  # mov [ebp-0x10], <"None">

    a.label("model_keep")
    a.emit(0x61)  # popad
    a.emit(b"\xff\x75\xf0")  # push dword [ebp-0x10]   ; the six stock bytes,
    a.emit(b"\x8d\x4d\x0c")  # lea ecx, [ebp+0xc]      ; now reading the substitution
    a.jmp_absolute(MODEL_FIELD_STORE_RESUME)


def _emit_arm(a: Asm, base_va: int, gadget_va: int) -> None:
    """The 20th ladder arm, spliced into the ladder's entry branch.

    Entered by an unconditional `jmp` that replaces `jne 0x920791`, so the flags from the
    `Options::Resolution` comparison are still live and the branch is re-taken here. `edi` is the
    `AptOptions`, `esi` the gadget and `[ebp+8]` the gadget's instance name, exactly as every
    stock arm sees them. Both exits are stock instruction boundaries.
    """
    a.label("arm")
    a.jcc(JNE, "arm_mine")  # jne .mine           ; the branch the hook displaced
    a.jmp_absolute(APT_INIT_GADGETS_RESOLUTION_ARM)  # it *is* Resolution -> the stock arm

    emit_arm_body(
        a, "arm", gadget_va, base_va + _OWNER_OFF, base_va + _GADGET_OFF, APT_INIT_GADGETS_LADDER
    )


def _emit_save(a: Asm, base_va: int, key_va: int, yes_va: int, no_va: int) -> None:
    """The key this patch owns, added to the map `AptOptions::Save` is about to flush.

    Spliced in front of `UserPreferences::write` rather than after it, so the new key rides the
    same flush the six stock keys do. `Save`'s frame is still live: the `OptionPreferences` sits at
    `[ebp-0x34]` and its map at `[ebp-0x30]`, and `edi` is the `AptOptions` whose gadget this
    has to be. `pushad`/`popad` spans the insertion because the stock code after it reads `edi`.
    """
    a.label("save")
    a.emit(0x60)  # pushad
    emit_save_body(a, "save", base_va + _OWNER_OFF, base_va + _GADGET_OFF, key_va, yes_va, no_va)

    a.label("save_done")
    a.emit(0x61)  # popad
    a.emit(b"\x8d\x8d", struct.pack("<i", APT_OPTIONS_SAVE_PREFS_EBP))  # the two stock
    a.call_absolute(USER_PREFERENCES_WRITE)  # instructions, unchanged
    a.jmp_absolute(APT_OPTIONS_SAVE_RESUME)


def _emit_enabled(a: Asm, state_va: int) -> None:
    """`bool enabled()` - the preference, resolved once per launch and cached.

    The `Model =` parser runs thousands of times per launch and reading a preference parses the
    whole of `Options.ini`, so it is asked exactly once. The Options row deliberately does *not*
    use this: it needs the saved value, not the launch value.
    """
    a.label("enabled")
    a.emit(0xA0, struct.pack("<I", state_va))  # mov al, [state]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "enabled_resolve")  # je .resolve
    a.emit(b"\xfe\xc8")  # dec al                 ; 1 -> off, 2 -> on
    a.emit(0xC3)  # ret

    a.label("enabled_resolve")
    a.call("read_fresh")  # call .read_fresh      ; eax = 0 or 1
    a.emit(0x40)  # inc eax                       ; -> the 1/2 cache encoding
    a.emit(0xA2, struct.pack("<I", state_va))  # mov [state], al
    a.emit(0x48)  # dec eax
    a.emit(0xC3)  # ret


class UnitPlateOptionPatch(Patch):
    name = "unit-plate-option"
    author = "officialNecro"
    runtime_verified = "yes"
    experimental = True
    description = (
        "Add a 20th row to the shell Options screen and make one model name obey it, so Edain's "
        "unit plates become a player-side toggle instead of a submod. Needs a matching gadget in "
        "Options.apt; takes effect on the model at the next launch"
    )

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        key: str = DEFAULT_KEY,
        gadget: str = DEFAULT_GADGET,
    ) -> None:
        for label, text in (("model", model), ("key", key), ("gadget", gadget)):
            if not text or not text.isascii():
                raise ValueError(f"{label} must be a non-empty ASCII string, got {text!r}")
        self.model = model
        self.key = key
        self.gadget = gadget

    def __str__(self) -> str:
        return f"{self.name} (model={self.model}, key={self.key}, gadget={self.gadget})"

    def _cave(self, base_va: int) -> Asm:
        return build_cave(base_va, self.model, self.key, self.gadget)

    def _edits(self, section_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """`(virtual address, original bytes, patched bytes, note)` for all three hooks, from one
        layout - so nothing can be pointed at a routine that moved."""
        labels = self._cave(section_va).label_va
        return [
            (
                va,
                stock,
                jmp_rel32(va, labels(label), len(stock)),
                f"{label} hook -> {SECTION_NAME}",
            )
            for va, stock, label in _HOOKS
        ]

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    def apply(self, data: bytearray) -> None:
        for va, _stock, _label in _HOOKS:
            self._offset(data, va)
        self._check_anchors(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._cave(base).finish(), _CHARACTERISTICS
        )
        for va, stock, patched, note in self._edits(section_va):
            apply_byte_patch(data, self._offset(data, va), stock, patched, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, section_size = located

        problems: list[str] = []
        expected = self._cave(section_va).finish()
        if section_size < len(expected):
            problems.append(
                f"{SECTION_NAME} holds {section_size} bytes, less than the {len(expected)} "
                "this patch emits"
            )
        elif bytes(data[section_off : section_off + len(expected)]) != expected:
            problems.append(
                f"{SECTION_NAME} does not hold the cave this patch builds for "
                f"model={self.model!r} key={self.key!r} gadget={self.gadget!r}"
            )
        else:
            for va, _stock, patched, note in self._edits(section_va):
                off = va_to_offset(data, va)
                if off is None:
                    problems.append(f"{va:#010x} is not mapped by any section")
                elif bytes(data[off : off + len(patched)]) != patched:
                    problems.append(f"{va:#010x} does not carry the {note.split()[0]} hook")
        problems += self._anchor_problems(data)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> UnitPlateOptionPatch | None:
        """Recover the parameters from the cave's own literals - they are the only record of what
        this patch was applied with, and `verify` rebuilds the whole cave from them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        _, section_off, section_size = located
        blob = bytes(data[section_off + _STRINGS_OFF : section_off + min(section_size, 0x200)])
        parts = blob.split(b"\x00")
        if len(parts) < len(_STRINGS):
            return None
        found = dict(zip(_STRINGS, parts, strict=False))
        fixed = {"none": _NONE, "yes": _YES, "no": _NO}
        if any(found[n] != want.encode("ascii") for n, want in fixed.items()):
            return None
        try:
            return cls(
                found["model"].decode("ascii"),
                found["key"].decode("ascii"),
                found["gadget"].decode("ascii"),
            )
        except (UnicodeDecodeError, ValueError):
            return None

    @classmethod
    def add_cli_arguments(cls, parser) -> None:  # noqa: ANN001 - argparse.ArgumentParser
        parser.add_argument(
            "--model",
            default=DEFAULT_MODEL,
            help=f"the model name that disappears when the option is off (default {DEFAULT_MODEL})",
        )
        parser.add_argument(
            "--key",
            default=DEFAULT_KEY,
            help=f"the Options.ini key the row reads and writes (default {DEFAULT_KEY})",
        )
        parser.add_argument(
            "--gadget",
            default=DEFAULT_GADGET,
            help=f"the gadget instance name Options.apt must use (default {DEFAULT_GADGET})",
        )

    @classmethod
    def from_cli_args(cls, args) -> UnitPlateOptionPatch:  # noqa: ANN001 - argparse.Namespace
        return cls(args.model, args.key, args.gadget)

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("; ".join(problems))

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        for va, want in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
            elif bytes(data[off : off + len(want)]) != want:
                problems.append(f"{va:#010x} does not carry its expected bytes")
        return problems
