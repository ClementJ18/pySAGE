"""The global map weather (`NORMAL`/`SNOWY`, `GlobalData+0x138`), and how a patch adds one that
drives a model condition the way `SNOWY` drives `SNOW`.

Targets the ROTWK SAGE-engine `game.dat` build `2.01.2614.37001` and the RotWK
`Worldbuilder.exe` that ships with it. Derived in `../../docs/desert-weather.md`; this module is
the shared owner because **more than one patch adds a map weather** (`desert-weather`,
`ash-weather`) and each one touches the same four resources:

* the weather **name table**, a NULL-terminated `const char*[]` reached from four references
  (five in Worldbuilder), with no room to grow in place;
* the `Sound`/`ViewShake` **"matches any weather" value**, which is the member count and has to
  move with it - left behind, the new weather would parse fine and mean *always*;
* two **code blocks** the patch takes over, `Drawable::bindToObject`'s weather arm and the
  timed-upgrade expiry's re-assert, both of which only know `SNOW`;
* Worldbuilder's **dropdown bound**, the member count again, hardcoded.

Everything is read from the live image, so two such patches compose in either order.

Fixed slots
-----------
A map stores its weather as an **integer** (`weather` in the `WorldInfo` chunk), so the index a
token resolves to has to be the same on every stack of patches, or a map authored on one comes out
as some other weather on another - with nothing to report it. Each patch therefore owns a fixed
slot (`DESERT` is 2, `ASH_RAIN` is 3) rather than taking the next free one. A patch whose slot is
past the end of the live table fills the gap with a placeholder (`RESERVED_WEATHER_<n>`), which a
later patch owning that slot replaces. A placeholder parses and drives nothing.

Chained hooks
-------------
The first patch to reach a hook site finds the engine's own block, replaces it with a `jmp` and
carries the displaced `SNOW` code in its *head* cave: `SNOW`, then its own condition, then a jump
back into the engine. Every later patch finds a `jmp` there instead and builds a *link* cave: its
own condition, then a jump to wherever the site pointed before. The site's `jmp` is repointed at
the link, so the chain runs newest first and ends in the head. Every cave touches only
eax/ecx/edx, so the order they run in does not matter.

`walk` follows a chain from the site, which is how `verify` finds its own cave in it whatever has
been chained in front. A head is told from a link by the weather its first block compares against:
a head starts with the `SNOWY` compare, and a link's weather is never `SNOWY`.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...asm import JNZ, JZ, Asm
from ...utils import allocate_section, apply_byte_patch, file_offset, find_section, i32, u32
from . import model_conditions, name_tables
from .name_tables import read_cstring

__all__ = [
    "BIND_SITE",
    "GLOBAL_DATA_VA",
    "SNOW_BIT",
    "STOCK_WEATHER_NAMES",
    "UPGRADE_SITE",
    "WEATHER_OFFSET",
    "WEATHER_SNOWY",
    "WEATHER_TABLE_REF_VAS",
    "WEATHER_TABLE_VA",
    "WORLDBUILDER_COMBO_BOUND_VA",
    "WORLDBUILDER_DIALOG_FINGERPRINT",
    "WORLDBUILDER_SECTION_CHARACTERISTICS",
    "WORLDBUILDER_TABLE_REF_SITES",
    "WORLDBUILDER_WEATHER_TABLE_VA",
    "Cave",
    "HookSite",
    "apply_byte_patches",
    "apply_game",
    "apply_worldbuilder",
    "build_bind_code",
    "build_bind_link",
    "build_upgrade_code",
    "build_upgrade_link",
    "detect_game",
    "detect_worldbuilder",
    "hook_edit",
    "is_placeholder",
    "live_weather_names",
    "placeholder_name",
    "read_cave",
    "read_table",
    "sentinel_edits",
    "sentinel_problems",
    "string_area_size",
    "table_layout",
    "verify_game",
    "verify_worldbuilder",
    "walk",
    "weather_table_edits",
    "worldbuilder_check_dialog",
    "worldbuilder_edits",
    "worldbuilder_live_names",
    "worldbuilder_problems",
]


#: The stock global weather name table: `{"NORMAL", "SNOWY", NULL}`. `INI::scanIndexList`
#: (`0x0042B914`) walks it to the terminator with `stricmp`, so its length is the terminator and
#: nothing else - but the next table (`LivingWorldObjectType`) starts at `0x00DA3A90`, one dword
#: past the NULL, so there is no room to grow it in place.
WEATHER_TABLE_VA = 0x00DA3A84
STOCK_WEATHER_NAMES = ("NORMAL", "SNOWY")

#: Every reference to the weather table: two `push imm32` in the two `WeatherTexture` field
#: parsers, and two `userData` slots in the INI field descriptors (`GameData.Weather` at
#: `GlobalData+0x138`, and `Sound`/`ViewShake`'s `Weather` at `+0x140`).
WEATHER_TABLE_REF_VAS = (
    0x004CF07B,  # WeatherTexture parser -> push <table>
    0x004CFECE,  # the second WeatherTexture parser
    0x00BF2C08,  # field descriptor: Sound / ViewShake `Weather`, offset 0x140
    0x00BFFA98,  # field descriptor: GameData `Weather`, offset 0x138
)

#: `GlobalData` fields. `TheWritableGlobalData` is the pointer.
GLOBAL_DATA_VA = 0x00DE4364
WEATHER_OFFSET = 0x138  # GameData `Weather`
WEATHER_SNOWY = 1

#: The bit `SNOW` occupies in `ModelConditionFlags`.
SNOW_BIT = 8

#: `ModelConditionFlags::set(bit, value)` - `thiscall`, `ret 8`, no bound check, plain
#: set-or-clear.
_SET_BIT_VA = 0x0068CC09

#: `Object::onModelConditionFlagsChanged`, called with ecx = the `Object`.
_PROPAGATE_VA = 0x0068B53C

#: Where the mask being built lives in `bindToObject`'s frame.
_BIND_FLAGS_DISP = -0x4C

#: In the timed-upgrade expiry update: the just-cleared mask in the frame, and `Object*` off
#: the module's `UpdateModule` subobject.
_UPGRADE_FLAGS_DISP = -0x94
_UPGRADE_THIS_TO_OBJECT = -0x08

#: `Sound` / `ViewShake` carry `Weather` at `+0x140`, and use the member **count** as the
#: "matches any weather" value: the constructor stores it as the default, and the condition
#: matcher short-circuits on it.
_ANY_WEATHER_DEFAULT_VA = 0x005DF616  # mov dword [esi+0x140], <count>
_ANY_WEATHER_DEFAULT_PREFIX = bytes.fromhex("c78640010000")
_ANY_WEATHER_TEST_VA = 0x005DF6F1  # cmp esi, <count>
_ANY_WEATHER_TEST_PREFIX = bytes.fromhex("83fe")

#: What a slot past the live table holds until the patch that owns it is applied.
_PLACEHOLDER_PREFIX = "RESERVED_WEATHER_"
_PLACEHOLDER_PATTERN = re.compile(rf"^{_PLACEHOLDER_PREFIX}\d+$")

#: How many caves a chain may hold before `walk` gives up on it as corrupt.
_MAX_CHAIN = 16


def placeholder_name(index: int) -> str:
    """The token that holds slot `index` until the patch owning it fills it."""
    return f"{_PLACEHOLDER_PREFIX}{index}"


def is_placeholder(name: str) -> bool:
    return bool(_PLACEHOLDER_PATTERN.match(name))


def read_table(data: bytes | bytearray, base_va: int, limit: int = 32) -> tuple[int, ...]:
    """The name pointers of the weather table at `base_va`, terminator excluded."""
    return name_tables.read_terminated(data, base_va, "weather name table", limit)


def _names(data: bytes | bytearray, pointers: Sequence[int]) -> list[str]:
    names: list[str] = []
    for index, pointer in enumerate(pointers):
        name = read_cstring(data, pointer)
        if name is None:
            raise ValueError(f"weather entry {index} points at unmapped 0x{pointer:08x}")
        names.append(name)
    return names


def _check_stock_prefix(names: Sequence[str], where: int) -> None:
    if list(names[: len(STOCK_WEATHER_NAMES)]) != list(STOCK_WEATHER_NAMES):
        raise ValueError(
            f"unexpected build: the weather name table at 0x{where:08x} reads {list(names)}, "
            f"expected it to start {list(STOCK_WEATHER_NAMES)}"
        )


def live_weather_names(data: bytes | bytearray) -> tuple[int, tuple[int, ...], list[str]]:
    """`(base VA, pointers, names)` of the table `game.dat`'s references currently point at."""
    try:
        base_va = name_tables.resolve_base(data, WEATHER_TABLE_REF_VAS, "weather name table")
    except ValueError as exc:
        raise ValueError(f"{exc} - not the expected build, or half-patched") from exc
    pointers = read_table(data, base_va)
    names = _names(data, pointers)
    _check_stock_prefix(names, base_va)
    return base_va, pointers, names


def table_layout(
    live: Sequence[int],
    live_names: Sequence[str],
    index: int,
    weather: str,
    base_va: int,
) -> bytes:
    """The rebuilt weather table at `base_va`: pointer array, NULL, then the strings this patch
    owns - its own name first, then a placeholder for each slot between the live end and its own.

    Raises unless `weather` can take slot `index`: the name must not already be in the table, and
    the slot must be past the end or hold a placeholder."""
    for at, name in enumerate(live_names):
        if name == weather:
            raise ValueError(f"{weather!r} is already weather {at}")
    if index < len(live_names) and not is_placeholder(live_names[index]):
        raise ValueError(
            f"weather slot {index} is already {live_names[index]!r} - another patch owns it"
        )
    count = max(len(live), index + 1)
    table_size = (count + 1) * 4

    strings = bytearray()
    owned: dict[int, int] = {}
    for slot in [index, *range(len(live), index)]:
        text = weather if slot == index else placeholder_name(slot)
        owned[slot] = base_va + table_size + len(strings)
        strings += text.encode("ascii") + b"\x00"
        strings += b"\x00" * (-len(strings) % 4)

    pointers = [owned[slot] if slot in owned else live[slot] for slot in range(count)]
    return b"".join(u32(p) for p in pointers) + u32(0) + bytes(strings)


def string_area_size(data: bytes | bytearray, base_va: int, pointers: Sequence[int]) -> int:
    """How many bytes of strings follow the table at `base_va`: those its own entries point into.

    `table_layout` places them contiguously right after the terminator, each padded to a dword, so
    the strings this table owns are exactly the pointers at or past that point."""
    start = base_va + (len(pointers) + 1) * 4
    size = 0
    for pointer in sorted(p for p in pointers if p >= start):
        if pointer != start + size:
            raise ValueError(f"the weather table at 0x{base_va:08x} has a gap in its strings")
        name = read_cstring(data, pointer)
        if name is None:
            raise ValueError(f"weather string at 0x{pointer:08x} is not terminated")
        size += len(name) + 1
        size += -size % 4
    return size


def weather_table_edits(
    data: bytes | bytearray, old_base_va: int, new_base_va: int
) -> list[tuple[int, bytes, bytes, str]]:
    return name_tables.ref_edits(
        data, WEATHER_TABLE_REF_VAS, old_base_va, new_base_va, "weather name table"
    )


def sentinel_edits(
    data: bytes | bytearray, old_count: int, new_count: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The two immediates carrying the `Sound`/`ViewShake` "matches any weather" value, moved
    from the live member count to the new one. `apply_byte_patch` refuses them if the image does
    not hold `old_count`, which is what catches a table and sentinel that have drifted apart."""
    return [
        (
            file_offset(data, _ANY_WEATHER_DEFAULT_VA),
            _ANY_WEATHER_DEFAULT_PREFIX + u32(old_count),
            _ANY_WEATHER_DEFAULT_PREFIX + u32(new_count),
            f"Sound/ViewShake any-weather default @0x{_ANY_WEATHER_DEFAULT_VA:08x}",
        ),
        (
            file_offset(data, _ANY_WEATHER_TEST_VA),
            _ANY_WEATHER_TEST_PREFIX + bytes([old_count]),
            _ANY_WEATHER_TEST_PREFIX + bytes([new_count]),
            f"Sound/ViewShake any-weather test @0x{_ANY_WEATHER_TEST_VA:08x}",
        ),
    ]


def sentinel_problems(data: bytes | bytearray, count: int) -> list[str]:
    """What is wrong with the two "matches any weather" immediates, for a table of `count`."""
    return [
        f"{note}: expected {new.hex()}, got {bytes(data[off : off + len(new)]).hex()}"
        for off, _old, new, note in sentinel_edits(data, count, count)
        if bytes(data[off : off + len(new)]) != new
    ]


def _bind_pair(a: Asm, bit: int, weather: int) -> None:
    """`set(bit, [esi+0x138] == weather)` on the mask `bindToObject` is building. `set` rather
    than `or` is what makes the negative case work: on any other weather the bit is cleared."""
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x83, 0xBE, u32(WEATHER_OFFSET), weather)  # cmp [esi+0x138], <weather>
    a.emit(0x8D, 0x4D, struct.pack("<b", _BIND_FLAGS_DISP))  # lea ecx, [ebp-0x4c] ; flags
    a.emit(0x0F, 0x94, 0xC0)  # sete al          ; `lea` leaves the flags alone
    a.emit(0x50)  # push eax                     ; value
    # `push imm8` for the stock SNOW bit, which keeps the displaced block exactly as the engine
    # wrote it; `push imm32` for an added bit, which is over 127.
    a.emit(bytes([0x6A, bit]) if bit == SNOW_BIT else b"\x68" + u32(bit))
    a.call_absolute(_SET_BIT_VA)


def build_bind_code(base_va: int, condition_bit: int, weather: int) -> bytes:
    """The head cave for `Drawable::bindToObject`: the displaced `SNOW` pair, this patch's pair,
    and the jump back to the engine.

    Only eax, ecx and edx are touched: esi holds `TheWritableGlobalData` and edi the `Drawable`,
    and both are still live at the join point. `set` is `thiscall` with `ret 8`, so it cleans its
    own two arguments and the stack is balanced on the way out."""
    a = Asm(base_va)
    _bind_pair(a, SNOW_BIT, WEATHER_SNOWY)
    _bind_pair(a, condition_bit, weather)
    a.jmp_absolute(BIND_SITE.return_va)
    return a.finish()


def build_bind_link(base_va: int, condition_bit: int, weather: int, next_va: int) -> bytes:
    """A link cave for `Drawable::bindToObject`: this patch's pair, then on down the chain."""
    a = Asm(base_va)
    _bind_pair(a, condition_bit, weather)
    a.jmp_absolute(next_va)
    return a.finish()


def _upgrade_block(a: Asm, bit: int, weather: int, done: str) -> None:
    """*If the mask just cleared off the object contained this bit, and the global weather still
    calls for it, put it back.* The read-before-write guard is the engine's own - without it every
    expiring upgrade would push the mask to the `Drawable` whether or not anything changed."""
    word = (bit // 32) * 4
    mask = 1 << (bit % 32)
    a.emit(0xF7, 0x85, i32(_UPGRADE_FLAGS_DISP + word), u32(mask))  # test [ebp+disp], mask
    a.jcc(JZ, done)
    a.emit(0xA1, u32(GLOBAL_DATA_VA))  # mov eax, [TheWritableGlobalData]
    a.emit(0x83, 0xB8, u32(WEATHER_OFFSET), weather)  # cmp [eax+0x138], <weather>
    a.jcc(JNZ, done)
    a.emit(0x8B, 0x4E, struct.pack("<b", _UPGRADE_THIS_TO_OBJECT))  # mov ecx, [esi-8] ; Object
    a.emit(0xF7, 0x81, u32(model_conditions.MASK_OFFSET + word), u32(mask))  # test [ecx+off]
    a.jcc(JNZ, done)
    a.emit(0x81, 0x89, u32(model_conditions.MASK_OFFSET + word), u32(mask))  # or [ecx+off]
    a.call_absolute(_PROPAGATE_VA)  # ecx is still the Object


def build_upgrade_code(base_va: int, condition_bit: int, weather: int) -> bytes:
    """The head cave for the timed-upgrade expiry update: the displaced `SNOW` re-assert, this
    patch's, and the jump back into the `NIGHT` block that follows.

    eax, ecx and edx are the only registers written; esi (the module) and ebp are still live in
    the `NIGHT` block this returns into."""
    a = Asm(base_va)
    _upgrade_block(a, SNOW_BIT, WEATHER_SNOWY, "own")
    a.label("own")
    _upgrade_block(a, condition_bit, weather, "done")
    a.label("done")
    a.jmp_absolute(UPGRADE_SITE.return_va)
    return a.finish()


def build_upgrade_link(base_va: int, condition_bit: int, weather: int, next_va: int) -> bytes:
    """A link cave for the timed-upgrade expiry update: this patch's re-assert, then on down the
    chain."""
    a = Asm(base_va)
    _upgrade_block(a, condition_bit, weather, "done")
    a.label("done")
    a.jmp_absolute(next_va)
    return a.finish()


@dataclass(frozen=True, slots=True)
class HookSite:
    """One engine block the weather patches take over, and how their caves for it are built."""

    what: str
    site_va: int
    #: The engine's bytes there, replaced as a whole by the first patch to arrive.
    original: bytes
    return_va: int
    head: Callable[[int, int, int], bytes]
    link: Callable[[int, int, int, int], bytes]
    #: Offset, in a cave, of the weather `imm8` its first block compares against.
    weather_byte: int

    @property
    def link_body(self) -> int:
        """Bytes before a link cave's closing `jmp`. Every branch and immediate is full width, so
        neither the bit nor the weather changes it."""
        return len(self.link(0, 0, 0, 0)) - 5

    def is_head(self, data: bytes | bytearray, cave_va: int) -> bool:
        return data[file_offset(data, cave_va) + self.weather_byte] == WEATHER_SNOWY

    def cave_size(self, head: bool) -> int:
        return len(self.head(0, 0, 0)) if head else len(self.link(0, 0, 0, 0))

    def build(self, cave: Cave, bit: int, weather: int) -> bytes:
        if cave.next_va is None:
            return self.head(cave.va, bit, weather)
        return self.link(cave.va, bit, weather, cave.next_va)


@dataclass(frozen=True, slots=True)
class Cave:
    """One cave in a hook site's chain. `next_va` is where a link jumps on to; a head has none."""

    va: int
    next_va: int | None


#: `Drawable::bindToObject`'s `ForceModelsToFollowWeather` arm (`0x00690F02`), entered with esi =
#: `TheWritableGlobalData` (already null-checked) and the mask being built at `[ebp-0x4c]`.
#: Nothing branches into the replaced range.
BIND_SITE = HookSite(
    what="Drawable::bindToObject weather block",
    site_va=0x00690FBE,
    original=bytes.fromhex("33c083be38010000018d4db40f94c0506a08e834bcffff"),
    return_va=0x00690FD5,
    head=build_bind_code,
    link=build_bind_link,
    weather_byte=8,  # xor eax,eax (2) + 83 be disp32 (6)
)

#: The timed-upgrade expiry update (`0x0080585F`), from its `SNOW` test onwards, entered with esi
#: = the module's `UpdateModule` subobject and the just-cleared mask at `[ebp-0x94]`. The `NIGHT`
#: block after `return_va` is left exactly as it is.
UPGRADE_SITE = HookSite(
    what="upgrade-expiry weather block",
    site_va=0x008058F9,
    original=bytes.fromhex(
        "8b856cffffffc1e808a8017427a16443de0083b8380100000175198b4ef88d810c010000"
        "ba00010000851075070910e80f5ce8ff"
    ),
    return_va=0x0080592D,
    head=build_upgrade_code,
    link=build_upgrade_link,
    weather_byte=27,  # test (10) + jz rel32 (6) + mov eax (5) + 83 b8 disp32 (6)
)


def _jmp_target(data: bytes | bytearray, va: int) -> int | None:
    off = file_offset(data, va)
    if data[off] != 0xE9:
        return None
    return (va + 5 + struct.unpack_from("<i", data, off + 1)[0]) & 0xFFFFFFFF


def walk(data: bytes | bytearray, site: HookSite) -> list[Cave]:
    """The chain of caves hooked at `site`, newest first and ending in the head. Empty if the
    site still holds the engine's own block. Raises if it holds anything else."""
    off = file_offset(data, site.site_va)
    if bytes(data[off : off + len(site.original)]) == site.original:
        return []
    target = _jmp_target(data, site.site_va)
    if target is None:
        raise ValueError(
            f"the {site.what} @0x{site.site_va:08x} is neither the engine's code nor a weather "
            "patch's jump - not the expected build"
        )
    caves: list[Cave] = []
    for _ in range(_MAX_CHAIN):
        if site.is_head(data, target):
            caves.append(Cave(target, None))
            if _jmp_target(data, target + site.cave_size(True) - 5) != site.return_va:
                raise ValueError(f"the {site.what} chain's head at 0x{target:08x} is corrupt")
            return caves
        next_va = _jmp_target(data, target + site.link_body)
        if next_va is None:
            raise ValueError(f"the {site.what} chain's link at 0x{target:08x} is corrupt")
        caves.append(Cave(target, next_va))
        target = next_va
    raise ValueError(f"the {site.what} chain is longer than {_MAX_CHAIN} caves")


def hook_edit(
    data: bytes | bytearray, site: HookSite, chain: Sequence[Cave], cave_va: int
) -> tuple[int, bytes, bytes, str]:
    """The edit that points `site` at a new cave: over the engine's block on a fresh site, over
    the previous `jmp` on a chained one. Either way the rest of the replaced range stays `nop`."""
    off = file_offset(data, site.site_va)
    jump = b"\xe9" + i32(cave_va - (site.site_va + 5))
    if not chain:
        return (
            off,
            site.original,
            jump + b"\x90" * (len(site.original) - 5),
            f"{site.what} -> 0x{cave_va:08x}",
        )
    return off, bytes(data[off : off + 5]), jump, f"{site.what} -> 0x{cave_va:08x} (chained)"


# The Worldbuilder half: the map-settings weather dropdown.
#
# Worldbuilder links the same engine code and carries its own copy of the table, whose length the
# `&Weather:` combo (control 0x4F5) reads from a hardcoded loop bound rather than the terminator.
# Leaving the bound alone is destructive: `CB_SETCURSEL` past the end clears the selection, and the
# OK handler stores the resulting -1 unvalidated, which the save path writes into the map.

#: Worldbuilder's stock weather name table. `0x02231FBC` is already the next table.
WORLDBUILDER_WEATHER_TABLE_VA = 0x02231FB0

#: Every reference to it, as `(VA, the bytes before its imm32)`. The two zero-length prefixes are
#: `userData` slots in INI field descriptors, which are data rather than code.
WORLDBUILDER_TABLE_REF_SITES = (
    (0x0056B999, bytes.fromhex("8b148d")),  # the combo loop: mov edx, [ecx*4 + <table>]
    (0x0090D2EB, bytes.fromhex("68")),  # a WeatherTexture field parser: push <table>
    (0x0095DAFB, bytes.fromhex("68")),  # the second WeatherTexture field parser
    (0x01E70E20, b""),  # field descriptor: FX nugget `Weather`, offset 0x140
    (0x01E86B88, b""),  # field descriptor: `GameData` `Weather`, offset 0x138
)

#: The combo-population loop's bound: `cmp dword [ebp-0x20], <count>`, an `imm8`.
WORLDBUILDER_COMBO_BOUND_VA = 0x0056B990
_WORLDBUILDER_COMBO_BOUND_PREFIX = bytes.fromhex("837de0")

#: Two window messages that pin the loop to the combo box it fills: `CB_ADDSTRING` inside it and
#: `CB_SETCURSEL` just past it.
WORLDBUILDER_DIALOG_FINGERPRINT = {
    0x0056B9AF: bytes.fromhex("6843010000"),  # push 0x143
    0x0056B9DD: bytes.fromhex("684e010000"),  # push 0x14e
}

# CNT_INITIALIZED_DATA | MEM_READ - the cave is a pointer table and strings, no code.
WORLDBUILDER_SECTION_CHARACTERISTICS = 0x40000040


def worldbuilder_check_dialog(data: bytes | bytearray) -> None:
    """Raise unless the two window messages bracketing the combo loop are where they should be."""
    for va, expected in WORLDBUILDER_DIALOG_FINGERPRINT.items():
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                "the weather combo box is not where this patch expects it"
            )


def worldbuilder_live_names(data: bytes | bytearray) -> tuple[int, tuple[int, ...], list[str]]:
    """`(base VA, pointers, names)` of the table Worldbuilder's references currently point at,
    after checking every reference keeps its encoding and they all agree."""
    bases: set[int] = set()
    for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(prefix)])
        if got != prefix:
            raise ValueError(
                f"weather name table ref @0x{va:08x} is encoded {got.hex()}, expected "
                f"{prefix.hex()} - not the expected build"
            )
        bases.add(struct.unpack_from("<I", data, off + len(prefix))[0])
    if len(bases) != 1:
        found = ", ".join(f"0x{base:08x}" for base in sorted(bases))
        raise ValueError(
            f"the Worldbuilder weather name table refs disagree ({found}) - not the expected "
            "build, or half-patched"
        )
    base_va = next(iter(bases))
    pointers = read_table(data, base_va)
    names = _names(data, pointers)
    _check_stock_prefix(names, base_va)
    return base_va, pointers, names


def worldbuilder_edits(
    data: bytes | bytearray, old_base_va: int, new_base_va: int, old_count: int, new_count: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The five reference edits and the dropdown bound, from the live table to the new one."""
    edits: list[tuple[int, bytes, bytes, str]] = []
    for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
        edits.append(
            (
                file_offset(data, va),
                prefix + u32(old_base_va),
                prefix + u32(new_base_va),
                f"Worldbuilder weather name table ref @0x{va:08x}",
            )
        )
    edits.append(
        (
            file_offset(data, WORLDBUILDER_COMBO_BOUND_VA),
            _WORLDBUILDER_COMBO_BOUND_PREFIX + bytes([old_count]),
            _WORLDBUILDER_COMBO_BOUND_PREFIX + bytes([new_count]),
            f"map-settings weather combo bound @0x{WORLDBUILDER_COMBO_BOUND_VA:08x}",
        )
    )
    return edits


def worldbuilder_problems(data: bytes | bytearray, index: int, weather: str) -> list[str]:
    """What is wrong with the live Worldbuilder state for a patch owning slot `index`: the name
    must be there, and the dropdown must show the whole table."""
    try:
        base_va, _pointers, names = worldbuilder_live_names(data)
    except (ValueError, struct.error) as exc:
        return [f"cannot read Worldbuilder's live weather table: {exc}"]
    problems: list[str] = []
    if index >= len(names) or names[index] != weather:
        problems.append(
            f"Worldbuilder's weather table at 0x{base_va:08x} reads {names}, expected "
            f"{weather!r} at {index}"
        )
    off = file_offset(data, WORLDBUILDER_COMBO_BOUND_VA)
    want = _WORLDBUILDER_COMBO_BOUND_PREFIX + bytes([len(names)])
    got = bytes(data[off : off + len(want)])
    if got != want:
        problems.append(
            f"map-settings weather combo bound: expected {want.hex()}, got {got.hex()} - the "
            "dropdown does not list the whole table"
        )
    return problems


def apply_byte_patches(data: bytearray, edits: Sequence[tuple[int, bytes, bytes, str]]) -> None:
    for file_off, old, new, note in edits:
        apply_byte_patch(data, file_off, old, new, note)


def read_cave(data: bytes | bytearray, section_va: int) -> tuple[int, str, int]:
    """`(the bit, the condition, the tail VA)` a game-side weather cave was built for.

    The section opens with the model-condition table its patch wrote, so the terminator says how
    many entries there were and the last of them is the patch's own condition. Reading both out of
    the cave rather than the live table is what keeps them right once another condition-adding
    patch has been applied on top."""
    off = file_offset(data, section_va)
    count = 0
    while struct.unpack_from("<I", data, off + count * 4)[0] != 0:
        count += 1
        if count > model_conditions.MASK_DWORDS * 32:
            raise ValueError(f"the model-condition table at 0x{section_va:08x} is not terminated")
    if not count:
        raise ValueError(f"the model-condition table at 0x{section_va:08x} is empty")
    pointer = struct.unpack_from("<I", data, off + (count - 1) * 4)[0]
    condition = read_cstring(data, pointer)
    if condition is None:
        raise ValueError(f"the last model condition at 0x{section_va:08x} is unreadable")
    name_size = len(condition) + 1
    name_size += -name_size % 4
    return count - 1, condition, section_va + (count + 1) * 4 + name_size


def _code_va(data: bytes | bytearray, table_va: int) -> int:
    """Where a game-side cave's code starts: past its weather table and the strings it owns."""
    pointers = read_table(data, table_va)
    return table_va + (len(pointers) + 1) * 4 + string_area_size(data, table_va, pointers)


def apply_game(
    data: bytearray, section_name: str, index: int, weather: str, condition: str
) -> None:
    """Add `weather` at slot `index` of `game.dat`'s map weather, driving a new model condition
    `condition`, in a cave called `section_name`. Raises before writing anything if the image is
    not the expected build or the slot or either name is taken."""
    live_base, live, live_names = live_weather_names(data)
    table_layout(live, live_names, index, weather, 0)  # raise on a taken name or slot now
    chains = {site: walk(data, site) for site in (BIND_SITE, UPGRADE_SITE)}
    new_count = max(len(live), index + 1)

    def caves(tail_va: int) -> tuple[bytes, Cave, Cave]:
        table = table_layout(live, live_names, index, weather, tail_va)
        bind_va = tail_va + len(table)
        bind = Cave(bind_va, chains[BIND_SITE][0].va if chains[BIND_SITE] else None)
        upgrade_va = bind_va + BIND_SITE.cave_size(bind.next_va is None)
        upgrade = Cave(upgrade_va, chains[UPGRADE_SITE][0].va if chains[UPGRADE_SITE] else None)
        return table, bind, upgrade

    def tail(tail_va: int, bits: tuple[int, ...]) -> bytes:
        table, bind, upgrade = caves(tail_va)
        return (
            table
            + BIND_SITE.build(bind, bits[0], index)
            + UPGRADE_SITE.build(upgrade, bits[0], index)
        )

    extension = model_conditions.extend(data, section_name, [condition], tail)
    _table, bind, upgrade = caves(extension.tail_va)
    edits = weather_table_edits(data, live_base, extension.tail_va)
    edits += sentinel_edits(data, len(live), new_count)
    edits.append(hook_edit(data, BIND_SITE, chains[BIND_SITE], bind.va))
    edits.append(hook_edit(data, UPGRADE_SITE, chains[UPGRADE_SITE], upgrade.va))
    apply_byte_patches(data, edits)


def verify_game(
    data: bytes | bytearray, section_name: str, index: int, weather: str, condition: str
) -> list[str]:
    """Structural check that `data` carries the patch `apply_game` would have written, whatever
    else has since been chained in front of it or appended to the shared tables."""
    located = find_section(data, section_name)
    if located is None:
        return [f"no {section_name} section: the file does not carry this patch"]
    try:
        bit, got_condition, tail_va = read_cave(data, located[0])
        own_names = _names(data, read_table(data, tail_va))
        code_va = _code_va(data, tail_va)
        live_base, _live, live_names = live_weather_names(data)
        live_bit = model_conditions.read(data).index_of(data, condition)
    except (ValueError, struct.error) as exc:
        return [f"cannot read back the {section_name} cave (wrong build?): {exc}"]

    problems: list[str] = []
    if got_condition != condition:
        problems.append(f"the {section_name} cave adds {got_condition!r}, not {condition!r}")
    if live_bit != bit:
        problems.append(
            f"{condition!r} is model condition {live_bit} in the live name table, but the cave "
            f"was built for bit {bit}"
        )
    if index >= len(own_names) or own_names[index] != weather:
        problems.append(
            f"the weather table in {section_name} reads {own_names}, expected {weather!r} at "
            f"{index}"
        )
    if index >= len(live_names) or live_names[index] != weather:
        problems.append(
            f"the live weather table at 0x{live_base:08x} reads {live_names}, expected "
            f"{weather!r} at {index}"
        )
    problems += sentinel_problems(data, len(live_names))

    cave_va = code_va
    for site in (BIND_SITE, UPGRADE_SITE):
        try:
            chain = walk(data, site)
        except ValueError as exc:
            problems.append(str(exc))
            break
        cave = next((c for c in chain if c.va == cave_va), None)
        if cave is None:
            problems.append(f"the {site.what} does not reach {section_name} at 0x{cave_va:08x}")
            break
        want = site.build(cave, bit, index)
        off = file_offset(data, cave.va)
        if bytes(data[off : off + len(want)]) != want:
            problems.append(
                f"the {site.what} cave at 0x{cave.va:08x} is not the code for {weather} -> "
                f"{condition} = bit {bit}"
            )
        cave_va += len(want)
    return problems


def detect_game(data: bytes | bytearray, section_name: str, index: int) -> tuple[str, str] | None:
    """`(weather, condition)` a game-side cave was built with, read out of the cave, or None."""
    located = find_section(data, section_name)
    if located is None:
        return None
    try:
        _bit, condition, tail_va = read_cave(data, located[0])
        names = _names(data, read_table(data, tail_va))
    except (ValueError, IndexError, struct.error):
        return None
    if index >= len(names) or is_placeholder(names[index]):
        return None
    return names[index], condition


def apply_worldbuilder(data: bytearray, section_name: str, index: int, weather: str) -> None:
    """Add `weather` at slot `index` of Worldbuilder's map-settings dropdown."""
    name_tables.check_not_rebased(data)
    worldbuilder_check_dialog(data)
    live_base, live, live_names = worldbuilder_live_names(data)
    table_layout(live, live_names, index, weather, 0)
    section_va = allocate_section(
        data,
        section_name,
        lambda base_va: table_layout(live, live_names, index, weather, base_va),
        WORLDBUILDER_SECTION_CHARACTERISTICS,
    )
    new_count = max(len(live), index + 1)
    apply_byte_patches(data, worldbuilder_edits(data, live_base, section_va, len(live), new_count))


def verify_worldbuilder(
    data: bytes | bytearray, section_name: str, index: int, weather: str
) -> list[str]:
    located = find_section(data, section_name)
    if located is None:
        return [f"no {section_name} section: the file does not carry this patch"]
    try:
        own_names = _names(data, read_table(data, located[0]))
    except (ValueError, struct.error) as exc:
        return [f"cannot read back the {section_name} cave (wrong build?): {exc}"]
    problems: list[str] = []
    if index >= len(own_names) or own_names[index] != weather:
        problems.append(
            f"the weather table in {section_name} reads {own_names}, expected {weather!r} at "
            f"{index}"
        )
    return problems + worldbuilder_problems(data, index, weather)


def detect_worldbuilder(data: bytes | bytearray, section_name: str, index: int) -> str | None:
    located = find_section(data, section_name)
    if located is None:
        return None
    try:
        names = _names(data, read_table(data, located[0]))
    except (ValueError, IndexError, struct.error):
        return None
    if index >= len(names) or is_placeholder(names[index]):
        return None
    return names[index]
