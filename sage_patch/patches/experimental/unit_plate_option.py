"""The unit-plate-option patch: a real Options-screen row, and a model that obeys it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The options-screen half is
derived in ``../docs/options-menu-rows.md``; the parse-time gate is derived below.

**The gap.** Edain's `unit_plate.inc` puts a `W3DScriptedModelDraw` tagged `Module_UnitPlate` on
552 unit objects, drawing the model ``unit_plate`` under every unit as a house-coloured
identification disc. The shipped game carries the draw module but **not** the model, so the plate
is invisible; a submod that ships nothing but ``art\\w3d\\un\\unit_plate.w3d`` turns it on for
everybody, permanently, with no way back. Players want the disc, and players want it off - it is
one extra render object per unit, which a late-game battle multiplies by four figures.

**What it does.** Adds a 20th option to the shell Options screen and makes one model name obey it.
Three hooks, one cave:

1. **The row** - `AptOptions::InitGadgets` is an inlined ladder of `stricmp`s with no table to
   extend, so the cave takes over the ladder's entry branch (`0x00920602`), answers for its own
   gadget name, and hands every other name back to the stock ladder. Matching means remembering
   the gadget and seeding the checkbox from the preference.
2. **The save** - `AptOptions::Save` writes only six hardcoded keys, so the cave splices itself in
   front of the `UserPreferences::write` at `0x009204DC`, adds its own key to the map the stock
   code is about to flush, and then flushes it.
3. **The model** - the `ModelConditionState` ``Model =`` field parser substitutes ``None`` for one
   named model unless the preference reads ``yes``.

**Why the "off" state is safe.** It is not new engine behaviour. A draw module whose model is
``None`` is still constructed, still tagged and still house-colourable; it just has no geometry -
which is exactly the state the shipped game is in today, and exactly what `unit_plate_remover.inc`
already produces on 78 shipped child objects.

**Why the model name and not the module tag.** Both are uniform across the 552 objects, but the
model name is what the renderer consumes, and ``unit_plate.inc`` is a single file - so the INI side
is one line under the mod's control, not a convention 552 files have to keep.

**When it takes effect.** The model substitution happens once per ``Model =`` line at INI parse
time, so a change of preference is visible at the next launch, not mid-match, and costs nothing per
frame. The checkbox itself always shows the *saved* value: the row reads the preference fresh,
while the model gate reads it once per launch and caches it, because constructing an
`OptionPreferences` parses the whole of `Options.ini`.

**The movie is a separate, required half.** Hooks 1 and 2 do nothing until `Options.apt` declares a
gadget with the matching instance name - a `placeobject` plus a label character, described in
``../docs/options-menu-rows.md`` §4. Applying this patch without that movie edit is inert rather
than harmful: the ladder arm never matches, and `Save` finds no gadget and writes nothing.

**Determinism.** Nothing here enters the simulation. The model name lives on client-side draw
module data and the preference is a per-machine file; no logic module, model-condition bit or
`GameMessage` is involved, and two peers disagreeing about the preference disagree about nothing
that is sent, checksummed or saved. Like `observer-switch` and unlike `production-condition`, it
does not have to be on every peer.

**Composition.** Order-independent. It allocates its cave with `allocate_section` and edits twenty
bytes at three sites (`0x004C2266`, `0x00920602`, `0x009204D9`) that no other bundled patch
touches, and reads nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ...addresses import (
    APT_INIT_GADGETS_EPILOGUE,
    APT_INIT_GADGETS_LADDER,
    APT_INIT_GADGETS_LADDER_BYTES,
    APT_INIT_GADGETS_LADDER_HOOK,
    APT_INIT_GADGETS_LADDER_HOOK_BYTES,
    APT_INIT_GADGETS_RESOLUTION_ARM,
    APT_OPTIONS_SAVE,
    APT_OPTIONS_SAVE_BYTES,
    APT_OPTIONS_SAVE_FLUSH,
    APT_OPTIONS_SAVE_FLUSH_BYTES,
    APT_OPTIONS_SAVE_MAP_EBP,
    APT_OPTIONS_SAVE_PREFS_EBP,
    APT_OPTIONS_SAVE_RESUME,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    EMPTY_STRING,
    GET_CHECKBOX_STATE,
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
    PREFERENCES_MAP_FIND,
    PREFERENCES_MAP_INDEX,
    SET_CHECKBOX_STATE,
    STRICMP,
    USER_PREFERENCES_WRITE,
    YES_STRING,
)
from ...asm import JE, JNE, JNZ, JZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

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

#: ``(address, stock bytes)`` for each of the three hooks, so `apply` writes exactly what `verify`
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
    _emit_read_fresh(a)
    _emit_read(a, base_va + at["key"])
    a.finish()  # resolve the internal branches, so `label_va` describes a real layout
    return a


def _emit_model_hook(a: Asm, model_va: int, none_va: int) -> None:
    """The six bytes lifted out of `MODEL_FIELD_STORE`, with the substitution in front of them.

    Entered with the parser's own frame still live, so ``[ebp-0x10]`` is the model-name token the
    stock code is about to copy into an `AsciiString`. `pushad`/`popad` spans the decision because
    the parser holds the target object in ``ebx`` and its own state in ``esi``/``edi`` across this
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
    `Options::Resolution` comparison are still live and the branch is re-taken here. ``edi`` is the
    `AptOptions`, ``esi`` the gadget and ``[ebp+8]`` the gadget's instance name, exactly as every
    stock arm sees them. Both exits are stock instruction boundaries.
    """
    a.label("arm")
    a.jcc(JNE, "arm_mine")  # jne .mine           ; the branch the hook displaced
    a.jmp_absolute(APT_INIT_GADGETS_RESOLUTION_ARM)  # it *is* Resolution -> the stock arm

    a.label("arm_mine")
    a.emit(0x68, struct.pack("<I", gadget_va))  # push <"Options::UnitPlates">
    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]      ; the gadget's name
    a.call_absolute(STRICMP)  # call stricmp
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "arm_ladder")  # jne .ladder       ; someone else's row -> stock ladder

    # Ours. Remember the gadget and whose screen it belongs to, then show the saved value. Read
    # fresh, not from the cache: after a save-and-reopen the cache still holds the launch value.
    a.emit(0x89, 0x3D, struct.pack("<I", base_va + _OWNER_OFF))  # mov [owner], edi
    a.emit(0x89, 0x35, struct.pack("<I", base_va + _GADGET_OFF))  # mov [gadget], esi
    a.call("read_fresh")  # call .read_fresh        ; eax = 0 or 1
    a.emit(0x50)  # push eax                        ; the state
    a.emit(0x56)  # push esi                        ; the gadget
    a.call_absolute(SET_CHECKBOX_STATE)  # call setCheckBoxState
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.jmp_absolute(APT_INIT_GADGETS_EPILOGUE)

    a.label("arm_ladder")
    a.jmp_absolute(APT_INIT_GADGETS_LADDER)


def _emit_save(a: Asm, base_va: int, key_va: int, yes_va: int, no_va: int) -> None:
    """The key this patch owns, added to the map `AptOptions::Save` is about to flush.

    Spliced in front of `UserPreferences::write` rather than after it, so the new key rides the
    same flush the six stock keys do. `Save`'s frame is still live: the `OptionPreferences` sits at
    ``[ebp-0x34]`` and its map at ``[ebp-0x30]``, and ``edi`` is the `AptOptions` whose gadget this
    has to be. `pushad`/`popad` spans the insertion because the stock code after it reads ``edi``.
    """
    a.label("save")
    a.emit(0x60)  # pushad
    a.emit(0xA1, struct.pack("<I", base_va + _OWNER_OFF))  # mov eax, [owner]
    a.emit(b"\x3b\xc7")  # cmp eax, edi
    a.jcc(JNE, "save_done")  # jne .done          ; a screen our row never initialised
    a.emit(0xA1, struct.pack("<I", base_va + _GADGET_OFF))  # mov eax, [gadget]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JZ, "save_done")  # jz .done            ; the movie has no such gadget

    a.emit(0x50)  # push eax
    a.call_absolute(GET_CHECKBOX_STATE)  # call getCheckBoxState -> al
    a.emit(0x59)  # pop ecx
    a.emit(b"\x0f\xb6\xd8")  # movzx ebx, al      ; survives the calls below

    a.emit(0x6A, 0x00)  # push 0                  ; the scratch AsciiString
    a.emit(0x68, struct.pack("<I", key_va))  # push <"ShowUnitPlates">
    a.emit(b"\x8d\x4c\x24\x04")  # lea ecx, [esp+4]
    a.call_absolute(ASCII_STRING_CTOR)  # call AsciiString::AsciiString   (ret 4)
    a.emit(b"\x8b\xc4")  # mov eax, esp           ; &key
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x8d", struct.pack("<i", APT_OPTIONS_SAVE_MAP_EBP))  # lea ecx, [ebp-0x30]
    a.call_absolute(PREFERENCES_MAP_INDEX)  # call map::operator[]  (ret 4) -> &value
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc_short(JZ, "save_no")  # jz .no
    a.emit(0x68, struct.pack("<I", yes_va))  # push <"yes">
    a.jmp_short("save_set")

    a.label("save_no")
    a.emit(0x68, struct.pack("<I", no_va))  # push <"no">

    a.label("save_set")
    a.emit(b"\x8b\xc8")  # mov ecx, eax           ; the map's value slot
    a.call_absolute(ASCII_STRING_SET)  # call AsciiString::operator=(const char *)  (ret 4)
    a.emit(b"\x8b\xcc")  # mov ecx, esp           ; &key
    a.call_absolute(ASCII_STRING_DTOR)  # call AsciiString::~AsciiString
    a.emit(b"\x83\xc4\x04")  # add esp, 4

    a.label("save_done")
    a.emit(0x61)  # popad
    a.emit(b"\x8d\x8d", struct.pack("<i", APT_OPTIONS_SAVE_PREFS_EBP))  # the two stock
    a.call_absolute(USER_PREFERENCES_WRITE)  # instructions, unchanged
    a.jmp_absolute(APT_OPTIONS_SAVE_RESUME)


def _emit_enabled(a: Asm, state_va: int) -> None:
    """``bool enabled()`` - the preference, resolved once per launch and cached.

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


def _emit_read_fresh(a: Asm) -> None:
    """``bool read_fresh()`` - construct an `OptionPreferences`, read the key, destroy it.

    0x80 bytes of stack is comfortably more than the object needs and costs nothing to
    over-reserve. `ebx`/`esi`/`edi` are preserved because both callers hold live values in them.
    """
    a.label("read_fresh")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x81\xec", struct.pack("<I", 0x80))  # sub esp, 0x80
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(b"\x8d\x8d", struct.pack("<i", -0x80))  # lea ecx, [ebp-0x80]
    a.call_absolute(OPTION_PREFERENCES_CTOR)  # call OptionPreferences::ctor -> eax = this
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call("read")  # call .read                  ; al = the value
    a.emit(b"\x0f\xb6\xd8")  # movzx ebx, al      ; survive the dtor
    a.emit(b"\x8d\x8d", struct.pack("<i", -0x80))  # lea ecx, [ebp-0x80]
    a.call_absolute(OPTION_PREFERENCES_DTOR)  # call OptionPreferences::dtor
    a.emit(b"\x8b\xc3")  # mov eax, ebx
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_read(a: Asm, key_va: int) -> None:
    """``bool read(OptionPreferences *this)`` - `OPTION_PREFERENCES_GET_BOOL` with our key.

    Instruction for instruction the engine's own accessor: look the key up in the map at
    ``this+4``, and answer true only if the stored value is ``yes``. A key that is not in the file
    lands on the same ``xor al, al`` the stock routine uses, so an untouched `Options.ini` reads as
    off - which is the shipped behaviour.
    """
    a.label("read")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x51)  # push ecx                      ; reserve [ebp-4]
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(b"\x8b\xf1")  # mov esi, ecx           ; this
    a.emit(0x68, struct.pack("<I", key_va))  # push <"ShowUnitPlates">
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CTOR)  # call AsciiString::AsciiString
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(b"\x83\xc6\x04")  # add esi, 4         ; -> the preference map
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(PREFERENCES_MAP_FIND)  # call map::find -> node, or the header
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.call_absolute(ASCII_STRING_DTOR)  # call AsciiString::~AsciiString
    a.emit(b"\x3b\x3e")  # cmp edi, [esi]         ; end() is the header node
    a.jcc_short(JNE, "read_found")  # jne .found
    a.emit(b"\x32\xc0")  # xor al, al             ; absent -> off
    a.jmp_short("read_out")

    a.label("read_found")
    a.emit(b"\x8b\x7f\x14")  # mov edi, [edi+0x14]    ; the value AsciiString's buffer
    a.emit(b"\x85\xff")  # test edi, edi
    a.emit(b"\x8d\x47\x08")  # lea eax, [edi+8]       ; chars live at +8, not +4
    a.jcc_short(JNE, "read_compare")  # jne .compare
    a.emit(0xB8, struct.pack("<I", EMPTY_STRING))  # mov eax, <"">

    a.label("read_compare")
    a.emit(0x68, struct.pack("<I", YES_STRING))  # push <"yes">
    a.emit(0x50)  # push eax
    a.call_absolute(STRICMP)  # call stricmp
    a.emit(b"\xf7\xd8")  # neg eax                ; eax == 0  ->  al = 1
    a.emit(0x59)  # pop ecx
    a.emit(b"\x1a\xc0")  # sbb al, al
    a.emit(0x59)  # pop ecx
    a.emit(b"\xfe\xc0")  # inc al

    a.label("read_out")
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _jmp_bytes(at: int, target: int, width: int) -> bytes:
    """A `jmp rel32` sited at ``at``, padded with `nop` to ``width``.

    Padding rather than splitting: every hook here displaces whole instructions, and a `jmp` that
    left a fragment of one behind would be entered part-way through on the return path.
    """
    return b"\xe9" + struct.pack("<i", target - (at + 5)) + b"\x90" * (width - 5)


class UnitPlateOptionPatch(Patch):
    name = "unit-plate-option"
    author = "officialNecro"
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
        """``(virtual address, original bytes, patched bytes, note)`` for all three hooks, from one
        layout - so nothing can be pointed at a routine that moved."""
        labels = self._cave(section_va).label_va
        return [
            (
                va,
                stock,
                _jmp_bytes(va, labels(label), len(stock)),
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
