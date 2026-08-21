"""A third global weather, `DESERT`, driving a new `SAND` model condition.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/desert-weather.md``.

**The gap.** The engine's global weather is a two-value enum - ``NORMAL``, ``SNOWY`` - parsed from
`GameData`'s ``Weather`` field into `GlobalData+0x138`, and it does exactly one thing to models:
when a `Drawable` is bound to its `Object`, the engine sets model condition ``SNOW`` if and only if
the weather is ``SNOWY`` (gated on ``ForceModelsToFollowWeather``). That is what lets one art set
carry snowy variants and have the engine pick them per map. There is no second such pairing, so a
desert map has no equivalent hook: a mod can only fake it per-object.

**What this does.** Adds ``DESERT`` as weather index 2 and ``SAND`` as a model condition, and wires
them together at the two places the engine relates weather to `Object+0x10C`:

* ``Drawable::bindToObject`` (``0x00690F02``) - the primary one. The stock block sets ``SNOW`` to
  ``weather == SNOWY``; the patched one also sets ``SAND`` to ``weather == DESERT``, through the
  engine's own `ModelConditionFlags::set` so a *false* result clears the bit exactly as it does
  for ``SNOW``.
* the timed-upgrade expiry update (``0x0080585F``) - when an upgrade's model conditions are pulled
  off an object, the engine re-asserts ``SNOW`` if it had just cleared it and the weather still
  says snowy. Without the same treatment, an upgrade that lists ``SAND`` would strip it for good.

**What comes free.** ``WeatherTexture`` (both draw-module parsers) resolves its token through the
same NULL-terminated name table and matches the stored value against `GlobalData+0x138` at
runtime, with no bound anywhere - so ``WeatherTexture = DESERT foo.tga`` works purely from the
table growing. Nothing else in the engine enumerates the weather list.

**What does not come free.** `Sound` and `ViewShake` carry a ``Weather`` field at ``+0x140`` whose
"any weather" value is the sentinel **2** - the stock member count, both as the constructor's
default (``0x005DF616``) and as the test in the condition matcher (``0x005DF6F1``). Leaving those
alone would make ``Weather = DESERT`` on a sound mean "always", silently. The patch moves the
sentinel to 3, which keeps the stock default meaning "any" and makes ``DESERT`` selectable.

**Known unpatched.** ``0x00491F82`` builds a `ModelConditionFlags` carrying ``NIGHT``/``SNOW`` from
the same two globals and asks each draw module which model it would use under them. It feeds asset
preloading, not what is drawn, so a `DESERT` map preloads the non-``SAND`` variant and then loads
the right one on demand. Fixing it means another cave for a stutter; it is recorded rather than
patched.

**Determinism.** `Object+0x10C` is the logic-side mask and part of what the engine CRCs, so every
peer must run the same patched binary - the same constraint `production-condition` documents, and
for the same reason. Nothing in the order stream changes.

**Composition.** Order-independent. The model-condition name table and its ten count bounds are
shared with `production-condition`, and both reach them through
:mod:`sage_patch.patches.utils.model_conditions`, which reads the live table rather than the
stock one; whichever is applied second lands on the next free bit. The weather table, its four
references, the two sentinel immediates and the two hooked blocks are touched by no other
bundled patch.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ..asm import JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils import model_conditions, name_tables

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_CONDITION",
    "DEFAULT_WEATHER",
    "NEW_WEATHER_INDEX",
    "SNOW_BIT",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
]


#: The global weather name table: ``{"NORMAL", "SNOWY", NULL}``. `INI::scanIndexList`
#: (``0x0042B914``) walks it to the terminator with `stricmp`, so its length is the terminator and
#: nothing else - but the next table (`LivingWorldObjectType`) starts at ``0x00DA3A90``, one dword
#: past the NULL, so there is no room to grow it in place.
WEATHER_TABLE_VA = 0x00DA3A84
STOCK_WEATHER_NAMES = ("NORMAL", "SNOWY")

#: The index ``DESERT`` takes, which is also the stock member count.
NEW_WEATHER_INDEX = len(STOCK_WEATHER_NAMES)

#: Every reference to the weather table: two `push imm32` in the two ``WeatherTexture`` field
#: parsers, and two `userData` slots in the INI field descriptors (`GameData.Weather` at
#: `GlobalData+0x138`, and `Sound`/`ViewShake`'s ``Weather`` at ``+0x140``).
WEATHER_TABLE_REF_VAS = (
    0x004CF07B,  # WeatherTexture parser -> push <table>
    0x004CFECE,  # the second WeatherTexture parser
    0x00BF2C08,  # field descriptor: Sound / ViewShake `Weather`, offset 0x140
    0x00BFFA98,  # field descriptor: GameData `Weather`, offset 0x138
)

#: `GlobalData` fields. `TheWritableGlobalData` is the pointer; the two flags gate whether models
#: follow the globals at all.
GLOBAL_DATA_VA = 0x00DE4364
WEATHER_OFFSET = 0x138  # GameData `Weather`
WEATHER_SNOWY = 1

#: `Object`'s `ModelConditionFlags`, and the bit ``SNOW`` already occupies in it.
MASK_OFFSET = model_conditions.MASK_OFFSET
SNOW_BIT = 8

#: `ModelConditionFlags::set(bit, value)` - `thiscall`, `ret 8`, no bound check, plain
#: set-or-clear. The engine calls it for ``NIGHT`` and ``SNOW`` from the site below.
_SET_BIT_VA = 0x0068CC09

#: `Object::onModelConditionFlagsChanged`, called with ecx = the `Object`.
_PROPAGATE_VA = 0x0068B53C


#: The ``ForceModelsToFollowWeather`` arm of ``Drawable::bindToObject``, entered with esi =
#: `TheWritableGlobalData` (already null-checked) and the `ModelConditionFlags` being built at
#: ``[ebp-0x4c]``. Ends at the join point both arms fall through to.
_BIND_SITE_VA = 0x00690FBE
_BIND_RETURN_VA = 0x00690FD5
_BIND_ORIGINAL = bytes.fromhex("33c083be38010000018d4db40f94c0506a08e834bcffff")

#: Where the mask being built lives in ``bindToObject``'s frame.
_BIND_FLAGS_DISP = -0x4C


#: In the update at ``0x0080585F``, the block that re-asserts ``SNOW``/``NIGHT`` after an expiring
#: upgrade's model conditions have been cleared off the object. Entered with esi = the module's
#: `UpdateModule` subobject (`Object*` at ``[esi-8]``) and the just-cleared mask at ``[ebp-0x94]``;
#: taken over from the ``SNOW`` test onwards so the test itself can be duplicated for ``SAND``.
#: The ``NIGHT`` block that follows ``_UPGRADE_RETURN_VA`` is left exactly as it is.
_UPGRADE_SITE_VA = 0x008058F9
_UPGRADE_RETURN_VA = 0x0080592D
_UPGRADE_ORIGINAL = bytes.fromhex(
    "8b856cffffffc1e808a8017427a16443de0083b8380100000175198b4ef88d810c010000"
    "ba00010000851075070910e80f5ce8ff"
)

#: Offsets from that update's own frame and `this`.
_UPGRADE_FLAGS_DISP = -0x94  # [ebp-0x94] -> the ModelConditionFlags just cleared
_UPGRADE_THIS_TO_OBJECT = -0x08  # [esi-0x08] -> Object*


#: `Sound` / `ViewShake` carry ``Weather`` at ``+0x140``, and use the member **count** as the
#: "matches any weather" value: the constructor stores it as the default, and the condition
#: matcher short-circuits on it. Both have to move with the count or ``DESERT`` becomes "always".
_ANY_WEATHER_DEFAULT_VA = 0x005DF616  # mov dword [esi+0x140], 2
_ANY_WEATHER_DEFAULT_PREFIX = bytes.fromhex("c78640010000")
_ANY_WEATHER_TEST_VA = 0x005DF6F1  # cmp esi, 2
_ANY_WEATHER_TEST_PREFIX = bytes.fromhex("83fe")

_SECTION_NAME = ".desertw"

DEFAULT_WEATHER = "DESERT"
DEFAULT_CONDITION = "SAND"


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i32(value: int) -> bytes:
    return struct.pack("<i", value)


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    return off


def _jump_over(data: bytes | bytearray, site_va: int, original: bytes, target_va: int) -> bytes:
    """A `jmp rel32` to ``target_va``, padded with `nop` to the length of the block it replaces."""
    return b"\xe9" + _i32(target_va - (site_va + 5)) + b"\x90" * (len(original) - 5)


def build_bind_code(base_va: int, condition_bit: int, weather: int = NEW_WEATHER_INDEX) -> bytes:
    """The cave for ``Drawable::bindToObject``.

    It is the stock two-instruction idiom twice over: compare the global weather, `sete` the
    result into a byte, and hand `(bit, value)` to `ModelConditionFlags::set`. Using `set` rather
    than an `or` is what makes the *negative* case work - on a ``SNOWY`` map the ``SAND`` call
    clears the bit, so an art set that names both conditions cannot end up wearing both.

    Only eax, ecx and edx are touched: esi holds `TheWritableGlobalData` and edi the `Drawable`,
    and both are still live at the join point. `set` is `thiscall` with `ret 8`, so it cleans its
    own two arguments and the stack is balanced on the way out."""

    def one(bit: int, weather_value: int, push_bit: bytes) -> None:
        a.emit(0x33, 0xC0)  # xor eax, eax
        a.emit(0x83, 0xBE, _u32(WEATHER_OFFSET), weather_value)  # cmp [esi+0x138], <weather>
        a.emit(0x8D, 0x4D, struct.pack("<b", _BIND_FLAGS_DISP))  # lea ecx, [ebp-0x4c]  ; flags
        a.emit(0x0F, 0x94, 0xC0)  # sete al          ; `lea` leaves the flags alone
        a.emit(0x50)  # push eax                     ; value
        a.emit(push_bit)  # push <bit>
        a.call_absolute(_SET_BIT_VA)

    a = Asm(base_va)
    one(SNOW_BIT, WEATHER_SNOWY, bytes([0x6A, SNOW_BIT]))  # the displaced stock pair
    one(condition_bit, weather, b"\x68" + _u32(condition_bit))  # imm32: the bit is over 127
    a.jmp_absolute(_BIND_RETURN_VA)
    return a.finish()


def build_upgrade_code(base_va: int, condition_bit: int, weather: int = NEW_WEATHER_INDEX) -> bytes:
    """The cave for the timed-upgrade expiry update.

    Two copies of the stock shape: *if the mask just cleared off the object contained this bit,
    and the global weather still calls for it, put it back*. The read-before-write guard is the
    engine's own and is kept - without it every expiring upgrade would push the mask to the
    `Drawable` whether or not anything changed.

    eax, ecx and edx are the only registers written; esi (the module) and ebp are still live in
    the ``NIGHT`` block this returns into."""
    a = Asm(base_va)

    def one(bit: int, weather_value: int, done: str) -> None:
        word = (bit // 32) * 4
        mask = 1 << (bit % 32)
        # was this bit part of what the expiring upgrade just cleared?
        a.emit(0xF7, 0x85, _i32(_UPGRADE_FLAGS_DISP + word), _u32(mask))  # test [ebp+disp], mask
        a.jcc(JZ, done)
        a.emit(0xA1, _u32(GLOBAL_DATA_VA))  # mov eax, [TheWritableGlobalData]
        a.emit(0x83, 0xB8, _u32(WEATHER_OFFSET), weather_value)  # cmp [eax+0x138], <weather>
        a.jcc(JNZ, done)
        a.emit(0x8B, 0x4E, struct.pack("<b", _UPGRADE_THIS_TO_OBJECT))  # mov ecx, [esi-8] ; Object
        a.emit(0xF7, 0x81, _u32(MASK_OFFSET + word), _u32(mask))  # test [ecx+off], mask
        a.jcc(JNZ, done)
        a.emit(0x81, 0x89, _u32(MASK_OFFSET + word), _u32(mask))  # or   [ecx+off], mask
        a.call_absolute(_PROPAGATE_VA)  # ecx is still the Object

    one(SNOW_BIT, WEATHER_SNOWY, "sand")
    a.label("sand")
    one(condition_bit, weather, "done")
    a.label("done")
    a.jmp_absolute(_UPGRADE_RETURN_VA)
    return a.finish()


class DesertWeatherPatch(Patch):
    """Add a third global weather and the model condition it drives."""

    name = "desert-weather"
    author = "officialNecro"
    description = (
        "Add a DESERT global weather type that drives a new SAND model condition, the way the "
        "stock SNOWY drives SNOW. A map opts in with weather = 2 in its WorldInfo chunk "
        "(authored by desert-weather-wb, not map.ini), art with a SAND ModelConditionState or "
        "WeatherTexture = DESERT <texture>, and models follow the weather only under GameData's "
        "ForceModelsToFollowWeather"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER, condition: str = DEFAULT_CONDITION):
        self.weather = weather
        self.condition = condition
        model_conditions.validate_name(self.weather)
        model_conditions.validate_name(self.condition)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather} -> {self.condition})"

    def apply(self, data: bytearray) -> None:
        stock_names = self._check_weather_table(data)
        for va, original in (
            (_BIND_SITE_VA, _BIND_ORIGINAL),
            (_UPGRADE_SITE_VA, _UPGRADE_ORIGINAL),
        ):
            off = _offset(data, va)
            if bytes(data[off : off + len(original)]) != original:
                raise ValueError(
                    f"the weather block @0x{va:08x} is not the expected build's - refusing to "
                    "replace code that is not what this patch was derived against"
                )

        extension = model_conditions.extend(
            data,
            _SECTION_NAME,
            [self.condition],
            lambda tail_va, bits: self._tail(tail_va, bits[0], stock_names),
        )
        weather_table_va, bind_va, upgrade_va = self._tail_addresses(extension.tail_va)

        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                _offset(data, va),
                _u32(WEATHER_TABLE_VA),
                _u32(weather_table_va),
                f"weather name table ref @0x{va:08x}",
            )
            for va in WEATHER_TABLE_REF_VAS
        ]
        edits += self._sentinel_edits(data)
        edits.append(
            (
                _offset(data, _BIND_SITE_VA),
                _BIND_ORIGINAL,
                _jump_over(data, _BIND_SITE_VA, _BIND_ORIGINAL, bind_va),
                f"Drawable::bindToObject weather block -> {_SECTION_NAME}",
            )
        )
        edits.append(
            (
                _offset(data, _UPGRADE_SITE_VA),
                _UPGRADE_ORIGINAL,
                _jump_over(data, _UPGRADE_SITE_VA, _UPGRADE_ORIGINAL, upgrade_va),
                f"upgrade-expiry weather block -> {_SECTION_NAME}",
            )
        )
        for file_off, old, new, note in edits:
            apply_byte_patch(data, file_off, old, new, note)

    def ini_surface(self) -> Engine:
        """The two tokens this patch adds: the weather (`GameData.Weather`, and the
        `WeatherTexture` selector that reads the same table) and the model condition it drives.

        The weather's index is fixed - it is appended to a two-entry table nothing else grows -
        while the model condition's bit depends on what else the binary carries, so only the
        first is stated here."""
        return Engine(
            enum_members=(
                EnumDelta("MapWeatherType", self.weather, NEW_WEATHER_INDEX, self.name),
                EnumDelta("ModelCondition", self.condition, None, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch. Everything is re-derived from the
        cave's own contents rather than from the stock constants, so it stays correct whatever
        else has since been applied on top of the shared model-condition table."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return [f"no {_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            table = model_conditions.read(data)
            bit, tail_va = self._read_cave(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {_SECTION_NAME} cave (wrong build?): {exc}"]

        problems: list[str] = []
        if table.index_of(data, self.condition) != bit:
            problems.append(
                f"{self.condition!r} is model condition {table.index_of(data, self.condition)} in "
                f"the live name table, but the cave was built for bit {bit}"
            )

        weather_table_va, bind_va, upgrade_va = self._tail_addresses(tail_va)
        names = self._read_weather_table(data, weather_table_va)
        if names != [*STOCK_WEATHER_NAMES, self.weather]:
            problems.append(
                f"the weather name table in {_SECTION_NAME} reads {names}, expected "
                f"{[*STOCK_WEATHER_NAMES, self.weather]}"
            )
        for va in WEATHER_TABLE_REF_VAS:
            got = struct.unpack_from("<I", data, _offset(data, va))[0]
            if got != weather_table_va:
                problems.append(
                    f"weather name table ref @0x{va:08x} points at 0x{got:08x}, not the "
                    f"patched table at 0x{weather_table_va:08x}"
                )
        for file_off, _old, new, note in self._sentinel_edits(data):
            got_bytes = bytes(data[file_off : file_off + len(new)])
            if got_bytes != new:
                problems.append(f"{note}: expected {new.hex()}, got {got_bytes.hex()}")

        for site_va, original, code_va, build in (
            (_BIND_SITE_VA, _BIND_ORIGINAL, bind_va, build_bind_code),
            (_UPGRADE_SITE_VA, _UPGRADE_ORIGINAL, upgrade_va, build_upgrade_code),
        ):
            off = _offset(data, site_va)
            want_jump = _jump_over(data, site_va, original, code_va)
            if bytes(data[off : off + len(want_jump)]) != want_jump:
                problems.append(f"the block @0x{site_va:08x} does not jump into {_SECTION_NAME}")
                continue
            if not section_va <= code_va < section_va + vsize:
                problems.append(f"0x{site_va:08x} jumps to 0x{code_va:08x}, outside the cave")
                continue
            want = build(code_va, bit)
            code_off = _offset(data, code_va)
            if bytes(data[code_off : code_off + len(want)]) != want:
                problems.append(
                    f"the cave body at 0x{code_va:08x} is not the code for "
                    f"{self.weather} -> {self.condition} = bit {bit}"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DesertWeatherPatch | None:
        """Recognise this patch **and recover both names it was applied with**.

        The default probe only ever recognises ``DESERT -> SAND``, so a binary patched under any
        other pair reads as unpatched. Both names are in the cave: it opens with the
        model-condition table this patch wrote, whose last entry is the condition, and the tail
        that follows opens with the relocated weather table, whose third entry is the weather.
        :meth:`verify` then re-checks the two code blocks against them."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, _vsize = located
        try:
            off = _offset(data, section_va)
            count = 0
            while struct.unpack_from("<I", data, off + count * 4)[0] != 0:
                count += 1
                if count > model_conditions.MASK_DWORDS * 32:
                    return None
            if not count:
                return None
            condition = model_conditions.read_cstring(
                data, struct.unpack_from("<I", data, off + (count - 1) * 4)[0]
            )
            if condition is None:
                return None
            # The tail sits past the table and the name this patch appended; the weather table is
            # the first thing in it, so `_tail_addresses` is not needed to find it.
            name_size = len(condition) + 1
            name_size += -name_size % 4
            tail_va = section_va + (count + 1) * 4 + name_size
            names = cls._read_weather_table(data, tail_va)
            if len(names) != len(STOCK_WEATHER_NAMES) + 1:
                return None
            patch = cls(weather=names[-1], condition=condition)
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--weather",
            default=DEFAULT_WEATHER,
            metavar="NAME",
            help=(
                f"name of the weather token to add (default {DEFAULT_WEATHER}); the value "
                "`GameData Weather =` and `WeatherTexture` then accept"
            ),
        )
        parser.add_argument(
            "--condition",
            default=DEFAULT_CONDITION,
            metavar="NAME",
            help=(
                f"name of the model condition it drives (default {DEFAULT_CONDITION}); uppercase "
                "letters, digits and underscores, and must not already be a model condition"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesertWeatherPatch:
        return cls(weather=args.weather, condition=args.condition)

    def _tail(self, tail_va: int, condition_bit: int, stock_names: tuple[int, ...]) -> bytes:
        """Everything this patch puts in the cave after the model-condition table and its name:
        the relocated weather table, the new weather token, and the two code blocks. The layout is
        a pure function of ``tail_va``, which is what lets :meth:`verify` recover it.

        ``stock_names`` are the two stock name pointers, reused as-is - so ``NORMAL`` and ``SNOWY``
        keep both their indices and their original strings."""
        weather_table_va, bind_va, upgrade_va = self._tail_addresses(tail_va)
        name = self.weather.encode("ascii") + b"\x00"
        name += b"\x00" * (-len(name) % 4)  # keep the code dword-aligned
        name_va = weather_table_va + (len(stock_names) + 2) * 4
        pointers = b"".join(_u32(p) for p in (*stock_names, name_va)) + _u32(0)
        code = build_bind_code(bind_va, condition_bit)
        assert bind_va + len(code) == upgrade_va, "the tail layout and its addresses disagree"
        return pointers + name + code + build_upgrade_code(upgrade_va, condition_bit)

    def _tail_addresses(self, tail_va: int) -> tuple[int, int, int]:
        """``(weather table VA, bind cave VA, upgrade cave VA)`` for a tail based at ``tail_va``.

        Both code blocks are fixed length - every branch in them is `rel32` and every immediate is
        a full dword, so the bit they carry cannot change their size - which is what makes the
        third address computable without assembling anything."""
        table_size = (len(STOCK_WEATHER_NAMES) + 2) * 4  # stock + the new one + NULL
        name_size = len(self.weather) + 1
        name_size += -name_size % 4
        bind_va = tail_va + table_size + name_size
        return tail_va, bind_va, bind_va + len(build_bind_code(bind_va, 0))

    def _check_weather_table(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The stock name pointers, after checking the table is where and what it should be and
        that every reference to it still holds its address."""
        names = self._read_weather_table(data, WEATHER_TABLE_VA)
        if names != list(STOCK_WEATHER_NAMES):
            raise ValueError(
                f"unexpected build: the weather name table at 0x{WEATHER_TABLE_VA:08x} reads "
                f"{names}, expected {list(STOCK_WEATHER_NAMES)}"
            )
        if self.weather in names:
            raise ValueError(f"{self.weather!r} is already weather {names.index(self.weather)}")
        for va in WEATHER_TABLE_REF_VAS:
            got = struct.unpack_from("<I", data, _offset(data, va))[0]
            if got != WEATHER_TABLE_VA:
                raise ValueError(
                    f"weather name table ref @0x{va:08x} holds 0x{got:08x}, not "
                    f"0x{WEATHER_TABLE_VA:08x} - not the expected build, or already patched"
                )
        return struct.unpack_from(
            f"<{len(STOCK_WEATHER_NAMES)}I", data, _offset(data, WEATHER_TABLE_VA)
        )

    @staticmethod
    def _read_weather_table(data: bytes | bytearray, base_va: int, limit: int = 8) -> list[str]:
        """The NULL-terminated table at ``base_va``, as names."""
        names: list[str] = []
        off = _offset(data, base_va)
        for index in range(limit):
            pointer = struct.unpack_from("<I", data, off + index * 4)[0]
            if pointer == 0:
                return names
            name = model_conditions.read_cstring(data, pointer)
            if name is None:
                raise ValueError(f"weather entry {index} points at unmapped 0x{pointer:08x}")
            names.append(name)
        raise ValueError(f"the weather table at 0x{base_va:08x} is not NULL-terminated")

    def _read_cave(self, data: bytes | bytearray, section_va: int) -> tuple[int, int]:
        """``(the bit this cave was built for, its tail VA)``, read out of the cave itself.

        The section starts with the model-condition table this patch wrote, so its terminator says
        how many entries there were and the last of them is this patch's own name. Deriving both
        from the cave rather than from the live table is what keeps :meth:`verify` right when
        another condition-adding patch has since been applied on top."""
        off = _offset(data, section_va)
        count = 0
        while struct.unpack_from("<I", data, off + count * 4)[0] != 0:
            count += 1
            if count > model_conditions.MASK_DWORDS * 32:
                raise ValueError(f"the table in {_SECTION_NAME} is not NULL-terminated")
        bit = count - 1
        pointer = struct.unpack_from("<I", data, off + bit * 4)[0]
        got = model_conditions.read_cstring(data, pointer)
        if got != self.condition:
            raise ValueError(
                f"the last entry of the table in {_SECTION_NAME} is {got!r}, not {self.condition!r}"
            )
        name_size = len(self.condition) + 1
        name_size += -name_size % 4
        return bit, section_va + (count + 1) * 4 + name_size

    def _sentinel_edits(self, data: bytes | bytearray) -> list[tuple[int, bytes, bytes, str]]:
        """The two immediates that carry the "matches any weather" value for `Sound` /
        `ViewShake`, raised from the stock member count to the patched one."""
        stock, patched = NEW_WEATHER_INDEX, NEW_WEATHER_INDEX + 1
        return [
            (
                _offset(data, _ANY_WEATHER_DEFAULT_VA),
                _ANY_WEATHER_DEFAULT_PREFIX + _u32(stock),
                _ANY_WEATHER_DEFAULT_PREFIX + _u32(patched),
                f"Sound/ViewShake any-weather default @0x{_ANY_WEATHER_DEFAULT_VA:08x}",
            ),
            (
                _offset(data, _ANY_WEATHER_TEST_VA),
                _ANY_WEATHER_TEST_PREFIX + bytes([stock]),
                _ANY_WEATHER_TEST_PREFIX + bytes([patched]),
                f"Sound/ViewShake any-weather test @0x{_ANY_WEATHER_TEST_VA:08x}",
            ),
        ]


# The Worldbuilder half: `DESERT` in the map-settings weather dropdown.
#
# A map does not carry its weather as INI. The `WorldInfo` chunk holds an `Integer` property named
# ``weather``, and both binaries copy it straight into `GlobalData+0x138` with no range check
# (`game.dat` at ``0x004AB7E0``, Worldbuilder at ``0x0076E44D``); Worldbuilder writes it back out on
# save through `Dict::setInt` at ``0x0066ECE4``. So the *data* path already accepts a third weather,
# and a map edited by any other means works on a patched `game.dat` with nothing done here.
#
# What does not accept it is the map-settings dialog. Its ``&Weather:`` combo (control ``0x4F5``)
# is filled by a loop with a **hardcoded bound** rather than by walking the table's NULL terminator:
#
#     0056b97e  mov dword [ebp-0x20], 0
#     0056b990  cmp dword [ebp-0x20], 2      ; the stock member count, baked in
#     0056b994  jge done
#     0056b999  mov edx, [ecx*4 + 0x02231FB0]
#     0056b9af  push 0x143                   ; CB_ADDSTRING
#     0056b9c3  done:
#     0056b9dd  push 0x14e                   ; CB_SETCURSEL <- GlobalData+0x138
#
# And leaving it alone is not neutral - it is destructive. `CB_SETCURSEL(2)` on a two-item combo
# returns `CB_ERR` *and clears the selection*, so `CB_GETCURSEL` answers ``-1`` and the OK handler
# stores that unvalidated:
#
#     0056c63e  push 0x147                   ; CB_GETCURSEL
#     0056c66b  mov [TheWritableGlobalData+0x138], eax
#
# which the save path then writes back into the map. Opening the map settings on a `DESERT` map and
# pressing OK silently reverts it. Raising the one immediate is what stops that, and the OK handler
# needs no change - it already stores whatever index the combo reports.
#
# Scope: the dropdown only. Worldbuilder resolves model conditions the way the game does
# (``0x00CEBF4C`` gates on `ForceModelsToFollowWeather`, then ``cmp +0x138, 1`` for bit 8; also
# ``0x00928EC8``, ``0x0092952B``, ``0x0064F953``), so the editor **viewport** keeps drawing the
# non-`SAND` variant until Worldbuilder's own model-condition table is extended too. That is
# cosmetic inside the editor: the map data and the game are unaffected.

#: Worldbuilder's own copy of the weather name table: ``{"NORMAL", "SNOWY", NULL}``. The NULL is at
#: ``0x02231FB8`` and ``0x02231FBC`` is already `ARMY`, the first entry of the
#: `LivingWorldObjectType` table - so there is no room to grow it in place, exactly as in
#: `game.dat`.
WORLDBUILDER_WEATHER_TABLE_VA = 0x02231FB0

#: Every reference to it, as ``(instruction VA, the bytes before its imm32)``. Asserting the
#: encoding as well as the value means a coincidental copy of the address in a different build
#: cannot be mistaken for one of these. The two zero-length prefixes are `userData` slots in INI
#: field descriptors, which are data rather than code.
WORLDBUILDER_TABLE_REF_SITES = (
    (0x0056B999, bytes.fromhex("8b148d")),  # the combo loop: mov edx, [ecx*4 + <table>]
    (0x0090D2EB, bytes.fromhex("68")),  # a WeatherTexture field parser: push <table>
    (0x0095DAFB, bytes.fromhex("68")),  # the second WeatherTexture field parser
    (0x01E70E20, b""),  # field descriptor: FX nugget `Weather`, offset 0x140
    (0x01E86B88, b""),  # field descriptor: `GameData` `Weather`, offset 0x138
)

#: The combo-population loop's bound: ``cmp dword [ebp-0x20], 2``, an `imm8`.
WORLDBUILDER_COMBO_BOUND_VA = 0x0056B990
_WORLDBUILDER_COMBO_BOUND_PREFIX = bytes.fromhex("837de0")

#: Two window messages that pin the loop to the combo box it fills, so the `cmp` above cannot be
#: some other comparison that happens to encode the same way. ``0x143`` is `CB_ADDSTRING` (inside
#: the loop) and ``0x14E`` is `CB_SETCURSEL` (just past it, preselecting the map's weather).
_WORLDBUILDER_DIALOG_FINGERPRINT = {
    0x0056B9AF: bytes.fromhex("6843010000"),  # push 0x143
    0x0056B9DD: bytes.fromhex("684e010000"),  # push 0x14e
}

#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbdsrt"

# CNT_INITIALIZED_DATA | MEM_READ - the cave is a pointer table and a string, and no code, so it
# does not need to be executable.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040


class DesertWeatherWorldbuilderPatch(Patch):
    """Teach Worldbuilder's map-settings weather dropdown a third member.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `desert-weather`; give both binaries the same weather name, since the map stores the index.
    """

    name = "desert-weather-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add DESERT to the map-settings weather dropdown, so a "
        "map can be authored with it and the dialog stops reverting it. Pass the same --weather "
        "name given to game.dat's desert-weather; the editor viewport still draws the non-SAND "
        "variant"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER):
        self.weather = weather
        model_conditions.validate_name(self.weather)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather})"

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        self._check_dialog(data)
        stock = self._check_weather_table(data)

        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base_va: self._table(base_va, stock),
            _WORLDBUILDER_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, _vsize = located

        problems: list[str] = []
        try:
            names = self._read_weather_table(data, section_va)
            edits = self._edits(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {WORLDBUILDER_SECTION_NAME} cave (wrong build?): {exc}"]

        if names != [*STOCK_WEATHER_NAMES, self.weather]:
            problems.append(
                f"the weather table in {WORLDBUILDER_SECTION_NAME} reads {names}, expected "
                f"{[*STOCK_WEATHER_NAMES, self.weather]}"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DesertWeatherWorldbuilderPatch | None:
        """Recognise this patch **and recover its weather name**.

        The default probe only ever recognises the default name, so a Worldbuilder patched under
        any other one reads as unpatched. The cave *is* the relocated weather table, so its third
        entry is the token this patch added; :meth:`verify` then re-checks every repointed site
        against it."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, _vsize = located
        try:
            names = cls._read_weather_table(data, section_va)
            if len(names) != len(STOCK_WEATHER_NAMES) + 1:
                return None
            patch = cls(weather=names[-1])
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--weather",
            default=DEFAULT_WEATHER,
            metavar="NAME",
            help=(
                f"name of the weather token to add (default {DEFAULT_WEATHER}); must match the "
                "one given to the game.dat `desert-weather` patch, since the map stores the index"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesertWeatherWorldbuilderPatch:
        return cls(weather=args.weather)

    def _table(self, base_va: int, stock: tuple[int, ...]) -> bytes:
        """The relocated table: the stock name pointers reused as-is - so ``NORMAL`` and ``SNOWY``
        keep both their indices and their original strings - then the new name, then the NULL.
        The dropdown's order is the table's order, and the *index* is what a map stores, so
        appending rather than inserting is what keeps existing maps meaning what they meant."""
        name = self.weather.encode("ascii") + b"\x00"
        name += b"\x00" * (-len(name) % 4)
        name_va = base_va + (len(stock) + 2) * 4
        return b"".join(_u32(p) for p in (*stock, name_va)) + _u32(0) + name

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """The six ``(file offset, original bytes, patched bytes, note)`` edits: five references
        to the table, and the loop bound that decides how many of its entries reach the dropdown.
        Shared by :meth:`apply` (writes ``patched`` when ``original`` matches) and :meth:`verify`
        (asserts ``patched`` is present)."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            edits.append(
                (
                    _offset(data, va),
                    prefix + _u32(WORLDBUILDER_WEATHER_TABLE_VA),
                    prefix + _u32(section_va),
                    f"Worldbuilder weather name table ref @0x{va:08x}",
                )
            )
        stock, patched = len(STOCK_WEATHER_NAMES), len(STOCK_WEATHER_NAMES) + 1
        edits.append(
            (
                _offset(data, WORLDBUILDER_COMBO_BOUND_VA),
                _WORLDBUILDER_COMBO_BOUND_PREFIX + bytes([stock]),
                _WORLDBUILDER_COMBO_BOUND_PREFIX + bytes([patched]),
                f"map-settings weather combo bound @0x{WORLDBUILDER_COMBO_BOUND_VA:08x}",
            )
        )
        return edits

    @staticmethod
    def _check_dialog(data: bytes | bytearray) -> None:
        """Raise unless the two window messages that bracket the combo-population loop are still
        where they should be. The bound being patched is an ordinary `cmp` against a small
        constant; without this, the same encoding somewhere else in a different build would be
        indistinguishable from it."""
        for va, expected in _WORLDBUILDER_DIALOG_FINGERPRINT.items():
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "the weather combo box is not where this patch expects it"
                )

    def _check_weather_table(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The stock name pointers, after checking the table is what it should be and that every
        reference to it still holds its address with its expected encoding."""
        names = self._read_weather_table(data, WORLDBUILDER_WEATHER_TABLE_VA)
        if names != list(STOCK_WEATHER_NAMES):
            raise ValueError(
                f"unexpected build: the weather name table at "
                f"0x{WORLDBUILDER_WEATHER_TABLE_VA:08x} reads {names}, expected "
                f"{list(STOCK_WEATHER_NAMES)}"
            )
        if self.weather in names:
            raise ValueError(f"{self.weather!r} is already weather {names.index(self.weather)}")
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            off = _offset(data, va)
            got = bytes(data[off : off + len(prefix) + 4])
            want = prefix + _u32(WORLDBUILDER_WEATHER_TABLE_VA)
            if got != want:
                raise ValueError(
                    f"weather name table ref @0x{va:08x} is {got.hex()}, expected {want.hex()} - "
                    "not the expected build, or already patched"
                )
        return struct.unpack_from(
            f"<{len(STOCK_WEATHER_NAMES)}I",
            data,
            _offset(data, WORLDBUILDER_WEATHER_TABLE_VA),
        )

    @staticmethod
    def _read_weather_table(data: bytes | bytearray, base_va: int, limit: int = 8) -> list[str]:
        """The NULL-terminated table at ``base_va``, as names."""
        names: list[str] = []
        off = _offset(data, base_va)
        for index in range(limit):
            pointer = struct.unpack_from("<I", data, off + index * 4)[0]
            if pointer == 0:
                return names
            name = model_conditions.read_cstring(data, pointer)
            if name is None:
                raise ValueError(f"weather entry {index} points at unmapped 0x{pointer:08x}")
            names.append(name)
        raise ValueError(f"the weather table at 0x{base_va:08x} is not NULL-terminated")
