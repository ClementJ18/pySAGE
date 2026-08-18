"""Recover every engine module, its INI fields and their compiled-in defaults.

The engine registers each behaviour/draw/update module through one
`addModule(instanceFactory, moduleDataFactory, ..., &name, interfaceMask)` call.
The ModuleData factory allocates the struct, runs its constructor and hands back a
`buildFieldParse` function, which appends one or more 16-byte-stride INI field
tables of `{const char *name, parseFn, userData, offset}`.

Field names and offsets come from those tables. Defaults come from linear
constant-tracking through the ModuleData constructor: a field whose INI keyword is
absent from a `.ini` block keeps whatever the constructor wrote at its offset.

A field's type is its parse function. Those are identified from their bodies: the
scaling constant a real parser applies, the range the engine checks and complains
about, the lookup array a token parser resolves against, or the keywords a sub-block
parser accepts.

Usage:
    python module_defaults.py <game.dat> [--json out.json] [--markdown out.md]
                                         [--enums out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from typing import Any, Iterator, Optional

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

__all__ = [
    "Image",
    "ModuleInfo",
    "FieldInfo",
    "extract",
    "block_keywords",
    "lookup_table",
    "name_table",
    "field_table_of",
    "ini_blocks",
    "BLOCK_TYPES",
    "NAME_TABLES",
    "PARSE_TYPES",
    "TYPE_TABLES",
]

ADD_MODULE = 0x6570FE
# A block keyword is CamelCase; the field table its parser owns is what really decides.
INI_KEYWORD = re.compile(r"^[A-Z][A-Za-z0-9_]{2,40}$")
INI_BLOCK_MIN_FIELDS = 3
EH_PROLOG = 0xA3CEF0
OPERATOR_NEW = (0x42F6E0, 0x42F6A0)
STR_ASSIGN = (0x4374E0, 0x4050E6, 0x436030, 0x40611E)
HELPERS = set(OPERATOR_NEW) | set(STR_ASSIGN) | {EH_PROLOG, 0x42DBBD, 0x435D50}
# `MultiIniFieldParse::add`, the one call inside a `buildFieldParse` that takes a table
# rather than contributing one. Every other call there is a base class's own.
MULTI_FIELD_ADD = 0x42B8D7
# The deepest chain the engine actually has is four (`CitadelSlaughterHordeContain`);
# the cap is a guard against following a call that is not a base class at all.
MAX_BASE_DEPTH = 8

# Parse functions identified from their bodies and from the fields that use them.
# Anything absent renders as the raw address.
PARSE_TYPES = {
    0x0042E558: "Bool",
    0x0042ED00: "Real",
    0x0073A429: "DurationReal",
    0x0042EE5E: "AsciiString",
    0x0042EC5E: "Int",
    0x0073A302: "FXList",
    0x0042EEFA: "Percent",
    0x0076392F: "KindOfFilter",
    0x0073B217: "AudioEventRTS",
    0x0042E59E: "AsciiStringList",
    0x0042E956: "Enum",
    0x0042EED6: "AsciiStringList",
    0x006564E7: "KindOfFlags",
    0x0073AE79: "WeaponTemplate",
    0x0042F247: "Coord3D",
    0x0066F603: "UpgradeMask",
    0x005DE588: "EvaEvent",
    0x008BDBB5: "FXList",
    0x008BDC21: "ObjectCreationList",
    0x008BDC8C: "ParticleSystem",
    0x0088A4AC: "FXList",
    0x0088A55B: "ObjectCreationList",
    0x0088A60A: "ParticleSystem",
    0x0042ECB2: "Int",
    0x0073A368: "ObjectCreationList",
    0x0042E840: "BitFlags",
    0x007B1E5C: "ObjectStatusFlags",
    0x0073A5C9: "DamageTypeFlags",
    # Reals that scale or range-check what they parse. The constant the parser
    # multiplies by names the conversion (0.0174533 = pi/180, so degrees in and
    # radians out), and where there is no constant the engine's own complaint
    # string names the range it enforces ("expected > 0").
    0x0042EE15: "AngleReal",
    0x0073A2D6: "AngularVelocityReal",
    0x0073A4B6: "VelocityReal",
    0x0073A403: "DurationReal",
    0x0073A429: "Duration",
    0x0042ED1C: "PositiveReal",
    0x0042ED6F: "NonNegativeReal",
    0x0042EDC2: "NonPositiveReal",
    # Integers narrower than a dword: the parser range-checks, then stores through
    # a byte or word move.
    0x0042EB2A: "Int8",
    0x0042EB75: "UInt8",
    0x0042EC11: "UInt16",
    0x0042F2FA: "IntRange",
    # Colours: three or four channels scaled by 1/255 into floats.
    0x0042EF99: "RGBColor",
    0x0042F13E: "RGBAColor",
    0x0042F298: "Coord3D",
    # Tokens resolved against a name array, either the field table's userData
    # (`LookupList`) or a static array owned by the flag type.
    0x0042E9B7: "LookupList",
    0x0073A68A: "DeathTypeFlags",
    0x004B8C21: "ModelConditionFlags",
    0x00869F22: "ModelConditionFlag",
    0x008514ED: "ModelConditionFlag",
    0x006C9951: "WeaponSetFlags",
    0x00866FF0: "ObjectStatusFlags",
    0x008D239B: "SpecialPowerFlags",
    0x00992693: "SpecialPowerAIType",
    0x008E09CE: "EmotionType",
    0x008966F9: "WeatherType",
    # Names looked up in another INI subsystem's template store.
    0x0073AF89: "UpgradeTemplate",
    0x0073B22F: "SpecialPowerTemplate",
    0x0073AFE3: "ScienceType",
    0x0073AECB: "ParticleSystem",
    0x0073B549: "FXList",
    0x0073ACEF: "AudioEventRTS",
    0x0073AD07: "AudioEventRTS",
    # A moment token followed by the thing to play at it. Which moments are on offer
    # differs between modules, so the list is attached per parse function below.
    0x0086158D: "MomentFXList",
    0x008A8A1D: "MomentFXList",
    0x008A818F: "MomentFXList",
    0x008615FE: "MomentOCL",
    0x008A8A82: "MomentOCL",
    0x008A81F2: "MomentOCL",
    0x008A9AC9: "MomentOCL",
    0x00861903: "MomentSound",
    0x00861672: "MomentWeapon",
    0x008A9B2B: "AngleFXList",
    0x008A1700: "DisabledTypeFlags",
    0x008BA71A: "ModelConditionFlagRange",
    0x0086C30A: "MeleeBehavior",
    # `Behavior = <module> <tag>` and its siblings: the keyword that attaches a module
    # to an object, and the geometry primitive an object's shape is built from.
    0x0073F24D: "Module",
    0x00AD4040: "GeometryType",
}

# The lists those types resolve their tokens against, where the array is reached from
# inside the parse function rather than from the field table's userData.
PARSER_TABLES = {
    0x0086158D: 0x00DAE770,
    0x008615FE: 0x00DAE770,
    0x00861903: 0x00DAE770,
    0x00861672: 0x00DAE770,
    0x008A8A1D: 0x00DB0ED0,
    0x008A8A82: 0x00DB0ED0,
    0x008A818F: 0x00DB0E7C,
    0x008A81F2: 0x00DB0E7C,
    0x008A9AC9: 0x00DB0F20,
    0x008A1700: 0x00DAD904,
    0x008BA71A: 0x00D9FAD8,
    0x0086C30A: 0x00DAEB2C,
    0x00AD4040: 0x00DC1C38,
}

# Sub-block parsers shared by more than one keyword, so the block's name cannot be
# taken from the keyword that uses it. Single-user blocks are named automatically.
BLOCK_TYPES = {
    0x00851412: "AnimAndDuration",
    0x00881681: "RiderInfo",
    0x0073A74B: "OpacityEnvelope",
    0x008C3F1F: "DamageCreationList",
    0x004C8840: "AnimationState",
    0x004C800E: "ModelConditionState",
    0x008D07CF: "ModelConditionAudio",
}

# Name arrays the flag and enum types resolve their tokens against: a
# NULL-terminated `const char*[]` reached from a static member rather than from the
# field table, so the address is recorded here and re-read from the binary. Every
# entry is checked against `NAME_TABLE_HEADS` on extraction.
NAME_TABLES = {
    "KindOf": 0x00DA0E68,
    "ObjectStatus": 0x00D8AFF0,
    "ModelCondition": 0x00D9FAD8,
    "WeaponSetFlags": 0x00DA1328,
    "DamageType": 0x00DA3960,
    "DeathType": 0x00DA39E8,
    "SpecialPowerType": 0x00DA5C90,
    "SpecialPowerFlags": 0x00DB4B08,
    "SpecialPowerAIType": 0x00DB84F8,
    "ArmorSetFlags": 0x00D9FA80,
    "EmotionType": 0x00D9FA08,
    "WeatherType": 0x00DB0074,
    "VeterancyLevel": 0x00D9F5E4,
    "SlotTypes": 0x00DA12E4,
    "LocomotorSetType": 0x00DA0530,
    "LivingWorldObjectType": 0x00DA3A90,
    "ParticleSysBonePersist": 0x00D8AF08,
}

# Arrays that run straight into the next one with no NULL between them, so the
# terminator cannot give their length and the members have to: the weather list ends
# at SUNNY, and both health-ratio lists end at ADD_CURRENT_HEALTH_TOO.
TABLE_LENGTHS = {
    0x00DB0074: 5,
    0x00DB05EC: 3,
    0x00DB1FFC: 3,
}

NAME_TABLE_HEADS = {
    "KindOf": "OBSTACLE",
    "ObjectStatus": "DESTROYED",
    "ModelCondition": "TOPPLED",
    "WeaponSetFlags": "VETERAN",
    "DamageType": "FORCE",
    "DeathType": "NORMAL",
    "SpecialPowerType": "SPECIAL_INVALID",
    "SpecialPowerFlags": "TARGETPOS",
    "SpecialPowerAIType": "AI_SPECIAL_POWER_BASIC_SELF_BUFF",
    "ArmorSetFlags": "VETERAN",
    "EmotionType": "TAUNT",
    "WeatherType": "NONE",
    "VeterancyLevel": "REGULAR",
    "SlotTypes": "PRIMARY",
    "LocomotorSetType": "SET_NORMAL",
    "LivingWorldObjectType": "ARMY",
    "ParticleSysBonePersist": "NONE",
}

# The flag and enum types whose members come from a static array rather than from
# the field's own userData.
TYPE_TABLES = {
    "KindOfFlags": "KindOf",
    "KindOfFilter": "KindOf",
    "ObjectStatusFlags": "ObjectStatus",
    "ModelConditionFlags": "ModelCondition",
    "ModelConditionFlag": "ModelCondition",
    "WeaponSetFlags": "WeaponSetFlags",
    "DamageTypeFlags": "DamageType",
    "DeathTypeFlags": "DeathType",
    "SpecialPowerFlags": "SpecialPowerFlags",
    "SpecialPowerAIType": "SpecialPowerAIType",
    "EmotionType": "EmotionType",
    "WeatherType": "WeatherType",
}

FLOATY = {"Real", "Percent", "DurationReal", "AngleReal", "VelocityReal",
          "AngularVelocityReal", "PositiveReal", "NonNegativeReal", "NonPositiveReal"}

# Words a sub-block parser mentions that are not keywords of the block: the
# terminator, the empty-reference token and the C format specifiers.
NOT_KEYWORDS = {"End", "None", "NoSound", "Unknown", "Yes", "No"}

R32 = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")
R8OF = {"al": "eax", "cl": "ecx", "dl": "edx", "bl": "ebx",
        "ah": "eax", "ch": "ecx", "dh": "edx", "bh": "ebx"}
R16OF = {"ax": "eax", "cx": "ecx", "dx": "edx", "bx": "ebx"}


class Image:
    """Minimal read-only view of the 32-bit PE, plus a capstone decoder."""

    def __init__(self, path: str) -> None:
        pe = pefile.PE(path, fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.data = open(path, "rb").read()
        self.sections: list[tuple[str, int, int, int]] = []
        for s in pe.sections:
            name = s.Name.rstrip(b"\x00").decode("latin1")
            size = max(s.Misc_VirtualSize, s.SizeOfRawData)
            self.sections.append((name, self.base + s.VirtualAddress, size,
                                  s.PointerToRawData))
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)
        text = next(s for s in self.sections if s[0] == ".text")
        self.text_va = text[1]
        self.text = self.data[text[3]:text[3] + text[2]]

    def section_of(self, va: int) -> Optional[str]:
        for name, va0, size, _ in self.sections:
            if va0 <= va < va0 + size:
                return name
        return None

    def read(self, va: int, n: int) -> bytes:
        for _, va0, size, fo in self.sections:
            if va0 <= va < va0 + size:
                off = fo + (va - va0)
                return self.data[off:off + n]
        return b""

    def u32(self, va: int) -> int:
        raw = self.read(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else 0

    def cstr(self, va: int, maxlen: int = 96) -> Optional[str]:
        raw = self.read(va, maxlen)
        end = raw.find(b"\x00")
        if end <= 0:
            return None
        try:
            return raw[:end].decode("ascii")
        except UnicodeDecodeError:
            return None

    def is_text(self, va: int) -> bool:
        return self.section_of(va) == ".text"

    def is_str(self, va: int) -> bool:
        return _is_data(self, va) and self.cstr(va) is not None

    def calls_to(self, target: int) -> list[int]:
        out, td = [], self.text
        for i in range(len(td) - 5):
            if td[i] == 0xE8:
                rel = struct.unpack("<i", td[i + 1:i + 5])[0]
                if self.text_va + i + 5 + rel == target:
                    out.append(self.text_va + i)
        return out

    def func_start(self, va: int, back: int = 0x4000) -> Optional[int]:
        """Nearest preceding MSVC prologue: `__EH_prolog` entry or `push ebp; mov ebp,esp`."""
        td, base = self.text, self.text_va
        best = None
        for a in range(max(base, va - back), va):
            i = a - base
            if td[i] == 0xB8 and td[i + 5] == 0xE8:
                rel = struct.unpack("<i", td[i + 6:i + 10])[0]
                if a + 10 + rel == EH_PROLOG:
                    best = a
            elif td[i:i + 3] == b"\x55\x8b\xec":
                best = a
        return best

    def disasm(self, start: int, maxlen: int = 0x9000) -> Iterator[Any]:
        """Linear decode from a function start, stopping at the first `ret`."""
        for ins in self.md.disasm(self.read(start, maxlen), start):
            yield ins
            if ins.mnemonic in ("ret", "retf"):
                return


def name_table(img: Image, va: int, limit: int = 1024) -> list[str]:
    """The NULL-terminated `const char*[]` at `va`, empty if that is not what is there.

    Members are identifiers, so a pointer to something with a space in it - a message,
    a format string - ends the array as surely as the NULL does. Not every array is
    NULL-terminated: where one runs straight into the next, the repeated member name
    is the seam, and the array ends there.
    """
    out: list[str] = []
    for k in range(min(limit, TABLE_LENGTHS.get(va, limit))):
        p = img.u32(va + 4 * k)
        if not p or not _is_data(img, p):
            break
        s = img.cstr(p, 64)
        if not s or not s.isprintable() or " " in s or not 0 < len(s) <= 48:
            break
        if s in out:
            break
        out.append(s)
    return out


def lookup_table(img: Image, va: int, limit: int = 256) -> list[tuple[str, int]]:
    """The `{const char *name, int value}` pairs of a lookup list at `va`."""
    out: list[tuple[str, int]] = []
    for k in range(limit):
        p = img.u32(va + 8 * k)
        if not p or not _is_data(img, p):
            break
        s = img.cstr(p, 64)
        if not s or not s.isprintable() or " " in s or not 0 < len(s) <= 48:
            break
        out.append((s, img.u32(va + 8 * k + 4)))
    return out


def field_table_of(img: Image, fn: int, max_offset: int = 0x4000, limit: int = 200,
                   depth: int = 0, maxdepth: int = 1,
                   seen: Optional[set[int]] = None) -> list[tuple[str, int, int, int]]:
    """The field table a parser hands to the INI reader, if it uses one.

    Every block the engine reads - a module, a nested block, a whole `Object` - is read
    through the same 16-byte-stride table, either pushed directly or fetched from a
    constant-returning accessor. A name array can pass `_looks_like_table`, so a real
    table is told apart by its rows: every parse function is code, and every offset is
    a plausible struct offset.
    """
    seen = seen if seen is not None else set()
    if fn in seen or depth > maxdepth:
        return []
    seen.add(fn)

    def rows_at(addr: int) -> list[tuple[str, int, int, int]]:
        if not _looks_like_table(img, addr):
            return []
        rows = parse_table(img, addr, limit)
        ok = all(img.is_text(r[1]) and r[3] < max_offset for r in rows)
        return rows if len(rows) >= 2 and ok else []

    ins = list(img.disasm(fn, 0x900))
    # the parser's own table first, then the one a helper it calls hands over
    for i in ins:
        if i.mnemonic == "call" and i.op_str.startswith("0x"):
            accessor = const_return(img, int(i.op_str, 16))
            if accessor:
                rows = rows_at(accessor)
                if rows:
                    return rows
        for tok in i.op_str.replace(",", " ").replace("[", " ").replace("]", " ").split():
            if not tok.startswith("0x"):
                continue
            try:
                a = int(tok, 16)
            except ValueError:
                continue
            rows = rows_at(a)
            if rows:
                return rows
    for i in ins:
        if i.mnemonic in ("call", "jmp") and i.op_str.startswith("0x") and len(ins) < 200:
            target = int(i.op_str, 16)
            if img.is_text(target):
                rows = field_table_of(img, target, max_offset, limit, depth + 1,
                                      maxdepth, seen)
                if rows:
                    return rows
    return []


def block_keywords(img: Image, fn: int) -> list[str]:
    """The keywords a sub-block parser compares its tokens against.

    A block parser strcmps the token it read against each keyword it accepts, so the
    identifier-shaped strings it references in order are the block's schema. Engine
    keywords are CamelCase, which separates them from the SHOUTING enum members and
    from the sentences in the error messages.
    """
    out: list[str] = []
    for i in img.disasm(fn, 0x600):
        for tok in i.op_str.replace(",", " ").replace("[", " ").replace("]", " ").split():
            if not tok.startswith("0x"):
                continue
            try:
                va = int(tok, 16)
            except ValueError:
                continue
            if not _is_data(img, va):
                continue
            s = img.cstr(va, 64)
            if (s and s not in out and s not in NOT_KEYWORDS and 1 < len(s) <= 32
                    and s[0].isupper() and s.isalnum() and any(c.islower() for c in s)):
                out.append(s)
    return out


def _memop(op: str) -> Optional[tuple[str, int]]:
    """`[reg + disp]` -> (reg, disp). Indexed forms are rejected."""
    if "[" not in op or "*" in op:
        return None
    inner = op[op.index("[") + 1:op.index("]")]
    parts = [p.strip() for p in inner.replace("-", "+-").split("+")]
    if not parts or parts[0] not in R32:
        return None
    disp = 0
    for p in parts[1:]:
        try:
            disp += int(p, 0)
        except ValueError:
            return None
    return parts[0], disp


_WIDTHS = {"byte": 1, "word": 2, "dword": 4, "qword": 8}


def _width(op: str) -> int:
    """Bytes a memory operand covers, from capstone's `dword ptr [...]` size prefix."""
    return _WIDTHS.get(op.split(" ", 1)[0], 1)


class FieldInfo(dict):
    """One INI keyword: name, struct offset, parse function, type, default."""


class ModuleInfo(dict):
    """One registered module: name, sizeof(ModuleData), and its fields."""


def registrations(img: Image) -> list[tuple[Optional[str], Optional[int], Optional[int], Optional[str]]]:
    """(name, instanceFactory, moduleDataFactory, interfaceMask) per addModule call."""
    sites = img.calls_to(ADD_MODULE)
    starts = sorted({s for s in (img.func_start(v) for v in sites) if s})
    out = []
    for start in starts:
        ins = list(img.disasm(start))
        name: Optional[str] = None
        pushes: list[str] = []
        for k, i in enumerate(ins):
            # `push <string> ; lea ecx, [ebp-N]` is the module-name assign, whichever
            # AsciiString helper follows it
            if (i.mnemonic == "push" and i.op_str.startswith("0x")
                    and img.is_str(int(i.op_str, 16))
                    and k + 1 < len(ins) and ins[k + 1].mnemonic == "lea"
                    and ins[k + 1].op_str.startswith("ecx, [ebp -")):
                name = img.cstr(int(i.op_str, 16))
                pushes = []
            elif i.mnemonic == "push":
                pushes.append(i.op_str)
            elif i.mnemonic == "call" and i.op_str.startswith("0x"):
                if int(i.op_str, 16) == ADD_MODULE:
                    fns = [int(p, 16) for p in pushes
                           if p.startswith("0x") and img.is_text(int(p, 16))]
                    mask = pushes[-6] if len(pushes) >= 6 else None
                    out.append((name, fns[-1] if fns else None,
                                fns[-2] if len(fns) > 1 else None, mask))
                    name, pushes = None, []
                else:
                    pushes = []
    return out


def moduledata_info(img: Image, fn: Optional[int]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(sizeof, constructor, buildFieldParse) from a ModuleData factory thunk."""
    if not fn:
        return None, None, None
    size = ctor = bfp = None
    pending: Optional[int] = None
    for i in img.disasm(fn, 0x200):
        if i.mnemonic == "push" and i.op_str.startswith("0x"):
            v = int(i.op_str, 16)
            if img.is_text(v):
                bfp = v
            elif 4 <= v <= 0x8000:
                pending = v
        elif i.mnemonic == "call" and i.op_str.startswith("0x"):
            t = int(i.op_str, 16)
            if t in OPERATOR_NEW and size is None:
                size = pending
            elif t not in HELPERS and ctor is None and size is not None:
                ctor = t
    return size, ctor, bfp


def _is_data(img: Image, va: int) -> bool:
    """Mapped, and not in the code section - `.rdata`/`.data`, or a patch's appended cave.

    Naming the two stock sections outright would refuse a table a patch has relocated: a rebuilt
    field table lives in the section that patch appended, which is where a patched `game.dat`
    keeps it and where the engine reads it from. What discriminates a table is its shape, checked
    below, not which section it happens to sit in."""
    section = img.section_of(va)
    return section is not None and section != ".text"


def _looks_like_table(img: Image, a: int) -> bool:
    if not _is_data(img, a):
        return False
    first = img.u32(a)
    return bool(first and _is_data(img, first) and img.cstr(first))


def const_return(img: Image, fn: int) -> Optional[int]:
    """`mov eax, imm32 ; ret` accessors return a base class's field table."""
    ins = list(img.disasm(fn, 0x10))
    if (len(ins) >= 2 and ins[0].mnemonic == "mov"
            and ins[0].op_str.startswith("eax, 0x") and ins[1].mnemonic == "ret"):
        return int(ins[0].op_str.split(", ")[1], 16)
    return None


def field_tables(img: Image, bfp: Optional[int], depth: int = 0,
                 seen: Optional[set[int]] = None) -> list[tuple[int, int]]:
    """(field table, the `buildFieldParse` that appended it) for one module.

    A table is either pushed directly, fetched from a base class through a trivial
    constant-returning accessor and then pushed from `eax`, or appended by the base
    class's own `buildFieldParse`, which a derived one calls before adding its own.
    That call is where inheritance lives: `OCLSpecialPower` declares five keywords
    itself and takes the other thirty-five from `SpecialPowerModule` through it, so a
    walk that does not follow it reports a module as accepting a fraction of what it
    really accepts. Following it in place keeps the engine's own order, in which the
    base's table is searched first and therefore wins a keyword declared in both.

    The second element of each pair names the class the table belongs to, which is
    what lets an inherited field say where it came from.
    """
    tabs: list[tuple[int, int]] = []
    if not bfp or depth > MAX_BASE_DEPTH:
        return tabs
    seen = seen if seen is not None else set()
    if bfp in seen:
        return tabs
    seen.add(bfp)
    for i in img.disasm(bfp, 0x120):
        if i.mnemonic == "push" and i.op_str.startswith("0x"):
            a = int(i.op_str, 16)
            if _looks_like_table(img, a):
                tabs.append((a, bfp))
        elif i.mnemonic == "call" and i.op_str.startswith("0x"):
            target = int(i.op_str, 16)
            a = const_return(img, target)
            if a is not None and _looks_like_table(img, a):
                tabs.append((a, bfp))
            elif target not in HELPERS and target != MULTI_FIELD_ADD and img.is_text(target):
                tabs.extend(field_tables(img, target, depth + 1, seen))
    return tabs


def parse_table(img: Image, tab: int, limit: int = 200) -> list[tuple[str, int, int, int]]:
    """(keyword, parseFn, userData, offset) rows of a 16-byte-stride field table."""
    out = []
    for k in range(limit):
        e = tab + k * 16
        namep = img.u32(e)
        if not namep or not _is_data(img, namep):
            break
        nm = img.cstr(namep)
        if not nm or not nm.isprintable() or len(nm) > 64:
            break
        out.append((nm, img.u32(e + 4), img.u32(e + 8), img.u32(e + 12)))
    return out


def ctor_defaults(img: Image, ctor: Optional[int], depth: int = 0, maxdepth: int = 5) -> dict[int, Any]:
    """{offset: value} written by a ModuleData constructor, by constant tracking.

    Handles the MSVC idioms the engine actually uses: immediate stores, stores of a
    zeroed or constant-loaded register, `movss` from an .rdata float, `xorps`,
    `or dword [x], -1`, `and dword [x], 0`, and AsciiString initialisation. A base
    class constructor invoked with `ecx == this` is followed one level down.
    """
    if not ctor or depth > maxdepth:
        return {}
    out: dict[int, Any] = {}
    ireg: dict[str, int] = {}
    freg: dict[str, float] = {}
    pushes: list[str] = []
    lea_off: Optional[int] = None
    this = {"ecx"}
    for i in img.disasm(ctor, 0x1200):
        m, o = i.mnemonic, i.op_str
        dst, _, src = o.partition(", ")
        if m == "push":
            pushes.append(o)
            continue
        if m == "xor" and dst == src and dst in R32:
            ireg[dst] = 0
            this.discard(dst)
        elif m == "xorps" and dst == src:
            freg[dst] = 0.0
        elif m == "mov" and dst in R32:
            if src in this:
                this.add(dst)
            elif src.startswith("0x") or src.lstrip("-").isdigit():
                ireg[dst] = int(src, 0)
                this.discard(dst)
            else:
                ireg.pop(dst, None)
                this.discard(dst)
        elif m == "movss" and dst.startswith("xmm"):
            if src.startswith("dword ptr [0x"):
                a = int(src[src.index("[") + 1:src.index("]")], 16)
                raw = img.read(a, 4)
                if len(raw) == 4:
                    freg[dst] = struct.unpack("<f", raw)[0]
                else:
                    freg.pop(dst, None)
            else:
                freg.pop(dst, None)
        elif m in ("mov", "movss", "or", "and") and "[" in dst:
            mm = _memop(dst)
            if not mm or mm[0] not in this:
                continue
            off = mm[1]
            if m == "movss":
                if src in freg:
                    out[off] = freg[src]
            elif m == "or" and src == "0xffffffff":
                out[off] = 0xFFFFFFFF
            elif m == "and" and src == "0":
                # `and dword [this+off], 0` is the engine's idiom for zeroing a member, and it
                # zeroes all four bytes - so a narrower field sharing the dword is defaulted by
                # it too, unless a later store overwrites that byte (this walk is linear, so a
                # later `out[off]` wins). Without this a `Bool` packed beside an `Int` reads as
                # having no compiled-in default when it plainly has one.
                for k in range(_width(dst)):
                    out[off + k] = 0
            elif m == "mov":
                if src.startswith("0x") or src.lstrip("-").isdigit():
                    out[off] = int(src, 0)
                elif src in ireg:
                    out[off] = ireg[src]
                elif src in R8OF and R8OF[src] in ireg:
                    out[off] = ireg[R8OF[src]] & 0xFF
                elif src in R16OF and R16OF[src] in ireg:
                    out[off] = ireg[R16OF[src]] & 0xFFFF
        elif m == "lea" and dst in R32:
            mm = _memop(src)
            if mm and mm[0] in this and mm[1] == 0:
                this.add(dst)
            elif dst == "ecx":
                lea_off = mm[1] if mm and mm[0] in this else None
            else:
                this.discard(dst)
        elif m == "call" and o.startswith("0x"):
            t = int(o, 16)
            if t in STR_ASSIGN and lea_off is not None:
                text = ""
                for p in reversed(pushes[-3:]):
                    if p.startswith("0x") and img.is_str(int(p, 16)):
                        text = img.cstr(int(p, 16)) or ""
                        break
                out[lea_off] = '"%s"' % text
            elif t not in HELPERS and lea_off is None and "ecx" in this:
                # base class constructor sharing `this`
                for k, v in ctor_defaults(img, t, depth + 1, maxdepth).items():
                    out.setdefault(k, v)
            elif t not in HELPERS and lea_off is not None:
                # embedded sub-object constructor; its writes rebase onto our layout
                for k, v in ctor_defaults(img, t, depth + 1, maxdepth).items():
                    out.setdefault(k + lea_off, v)
            lea_off = None
            pushes = []
    return out


def render_default(img: Image, kind: str, raw: Any) -> Optional[str]:
    """Format a recovered default according to the field's parsed type.

    A value that lands inside a mapped section is a pointer that leaked through the
    tracker (a vtable, a string, a default object), not a field value; report it as
    unresolved rather than as a wrong number.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, float):
        return "%g" % raw
    if raw == 0xFFFFFFFF:
        return "-1"
    if raw >= 0x400000 and img.section_of(raw):
        return None
    if kind in FLOATY and raw > 0x10000000:
        return "%g" % struct.unpack("<f", struct.pack("<I", raw))[0]
    if kind == "Bool":
        return "Yes" if raw else "No"
    return str(raw)


def field_type(img: Image, keyword: str, parse: int,
               blocks: dict[str, dict[str, Any]]) -> str:
    """The type name for a field, registering the sub-block schema behind it.

    An unidentified parse function that reads a nested block is a sub-block type;
    unless it is shared between keywords, the keyword that takes it names it. The
    block's own schema comes from its field table where it has one, and from the
    keywords it compares tokens against where it parses by hand.
    """
    if parse in PARSE_TYPES:
        return PARSE_TYPES[parse]
    name = BLOCK_TYPES.get(parse, keyword)
    if name in blocks:
        return name if blocks[name]["parse_fn"] == parse else "0x%08x" % parse
    rows = field_table_of(img, parse)
    fields = [{"name": kw, "type": PARSE_TYPES.get(fn, "0x%08x" % fn),
               "parse_fn": fn, "offset": off}
              for kw, fn, _ud, off in rows]
    words = [f["name"] for f in fields] or block_keywords(img, parse)
    if len(words) < 2 and parse not in BLOCK_TYPES:
        return "0x%08x" % parse
    blocks[name] = {"parse_fn": parse, "keywords": words, "fields": fields}
    return name


class Catalogue:
    """The shared side-tables an extraction fills in: enums, lookups, sub-blocks."""

    def __init__(self) -> None:
        self.blocks: dict[str, dict[str, Any]] = {}
        self.tables: dict[str, list[str]] = {}
        self.lookups: dict[str, list[tuple[str, int]]] = {}

    def field(self, img: Image, row: tuple[str, int, int, int],
              defaults: dict[int, Any]) -> FieldInfo:
        """One field-table row as a typed field, registering what it points at."""
        keyword, parse, ud, off = row
        kind = field_type(img, keyword, parse, self.blocks)
        ud = ud or PARSER_TABLES.get(parse, 0)
        members = name_table(img, ud) if ud else []
        pairs = lookup_table(img, ud) if kind == "LookupList" and ud else []
        if len(members) > 1 and kind != "LookupList":
            self.tables.setdefault("0x%08x" % ud, members)
        elif len(pairs) > 1:
            self.lookups.setdefault("0x%08x" % ud, pairs)
        else:
            ud = 0
        return FieldInfo(
            name=keyword,
            offset=off,
            type=kind,
            parse_fn=parse,
            userdata="0x%08x" % ud if ud else None,
            default=render_default(img, kind, defaults.get(off)),
        )


def alloc_ctor(img: Image, fn: int) -> Optional[int]:
    """The constructor a block parser runs on the instance it allocates, if it does.

    Some block types are allocated and constructed right there in the parser, which
    puts their defaults within reach of the same constant tracking modules use. The
    ones built through a factory elsewhere are not, and get no defaults.
    """
    size: Optional[int] = None
    pending: Optional[int] = None
    for i in img.disasm(fn, 0x600):
        if i.mnemonic == "push" and i.op_str.startswith("0x"):
            value = int(i.op_str, 16)
            if 4 <= value <= 0x8000:
                pending = value
        elif i.mnemonic == "call" and i.op_str.startswith("0x"):
            target = int(i.op_str, 16)
            if target in OPERATOR_NEW and size is None:
                size = pending
            elif target not in HELPERS and size is not None:
                return target
    return None


def ini_blocks(img: Image, cat: Catalogue) -> dict[str, dict[str, Any]]:
    """Every INI block keyword whose parser owns a field table.

    The loader dispatches a block on `{keyword, parser}` pairs sitting in the data
    sections. Rather than trust the pairs - a string next to a function pointer is a
    common enough accident - each candidate is kept only if its parser really does
    hand a field table to the INI reader, which is what makes it a block type at all.
    """
    candidates: dict[str, set[int]] = {}
    for name, va0, size, _fo in img.sections:
        if name not in (".rdata", ".data"):
            continue
        for va in range(va0, va0 + size - 8, 4):
            strp, fn = img.u32(va), img.u32(va + 4)
            if not strp or not fn or not img.is_text(fn):
                continue
            if not _is_data(img, strp):
                continue
            keyword = img.cstr(strp, 48)
            if keyword and INI_KEYWORD.match(keyword):
                candidates.setdefault(keyword, set()).add(fn)

    # A field-table row is a keyword next to a parse function too, so a keyword often
    # has several candidates: the block parser that owns its whole schema, and the leaf
    # parsers of same-named fields elsewhere. The fullest table is the block's.
    rows_of: dict[int, list[tuple[str, int, int, int]]] = {}
    out: dict[str, dict[str, Any]] = {}
    for keyword, fns in sorted(candidates.items()):
        best: list[tuple[str, int, int, int]] = []
        chosen = 0
        for fn in sorted(fns):
            if fn not in rows_of:
                rows_of[fn] = field_table_of(img, fn, max_offset=0x10000, limit=500,
                                             maxdepth=2)
            if len(rows_of[fn]) > len(best):
                best, chosen = rows_of[fn], fn
        if len(best) < INI_BLOCK_MIN_FIELDS:
            continue
        ctor = alloc_ctor(img, chosen)
        defaults = ctor_defaults(img, ctor) if ctor else {}
        fields = [cat.field(img, row, defaults) for row in best]
        out[keyword] = {
            "parse_fn": chosen,
            "moduledata_ctor": ctor,
            "fields": sorted(fields, key=lambda f: f["name"].lower()),
        }
    return dict(sorted(out.items()))


def extract(img: Image) -> tuple[list[ModuleInfo], dict[str, Any]]:
    """Every registered module with its fields, plus the types those fields use.

    The second return value carries what a field's type alone cannot: the member
    names behind every enum and flag type, the keywords of every sub-block, and the
    INI block types that are read the same way modules are.
    """
    mods: list[ModuleInfo] = []
    cat = Catalogue()
    blocks, tables, lookups = cat.blocks, cat.tables, cat.lookups
    reg = [(name, mask) + moduledata_info(img, md)
           for name, inst, md, mask in registrations(img)]
    # A base class is usually a registered module in its own right, which is what lets
    # an inherited field name where it came from. Two things stop that being exact: the
    # purely abstract bases (`DockUpdate`, `SpecialPowerUpdate`) are never registered,
    # and several keywords can share one ModuleData class (`ActiveBody` is also
    # `ImmortalBody`), in which case the first registered wins the name.
    declared_by: dict[int, str] = {}
    for name, _mask, _size, _ctor, bfp in reg:
        if bfp and name:
            declared_by.setdefault(bfp, name)
    for name, mask, size, ctor, bfp in reg:
        defaults = ctor_defaults(img, ctor)
        fields: list[FieldInfo] = []
        seen: set[str] = set()
        for tab, source in field_tables(img, bfp):
            for row in parse_table(img, tab):
                if row[0] in seen:
                    continue
                seen.add(row[0])
                field = cat.field(img, row, defaults)
                if source != bfp:
                    field["inherited"] = True
                    if source in declared_by:
                        field["inherited_from"] = declared_by[source]
                fields.append(field)
        mods.append(ModuleInfo(
            name=name,
            interface_mask=mask,
            moduledata_size=size,
            moduledata_ctor=ctor,
            fields=sorted(fields, key=lambda f: f["name"].lower()),
        ))
    enums: dict[str, str] = {}
    types: dict[str, str] = {}
    for enum, va in NAME_TABLES.items():
        members = name_table(img, va)
        if not members or members[0] != NAME_TABLE_HEADS[enum]:
            raise ValueError("%s: no name array at 0x%08x (found %r)"
                             % (enum, va, members[:1]))
        tables["0x%08x" % va] = members
        enums[enum] = "0x%08x" % va
        for type_name, target in TYPE_TABLES.items():
            if target == enum:
                types[type_name] = "0x%08x" % va
    ini = ini_blocks(img, cat)
    return (sorted(mods, key=lambda m: (m["name"] or "").lower()),
            {"name_tables": tables, "lookup_tables": lookups, "enums": enums,
             "types": types, "blocks": dict(sorted(blocks.items())),
             "ini_blocks": ini})


def to_markdown(mods: list[ModuleInfo]) -> str:
    total = sum(len(m["fields"]) for m in mods)
    known = sum(1 for m in mods for f in m["fields"] if f["default"] is not None)
    unlabelled = sum(1 for m in mods for f in m["fields"] if f["type"].startswith("0x"))
    lines = [
        "# Engine module reference - fields and compiled-in defaults",
        "",
        "Generated from `game.dat` by [`../scripts/module_defaults.py`](../scripts/module_defaults.py);",
        "regenerate rather than edit. **%d modules, %d fields, %d with a recovered "
        "default (%.0f%%).**"
        % (len(mods), total, known, 100.0 * known / total if total else 0),
        "",
        "A listed default is what the ModuleData constructor writes, so it is the value in",
        "force whenever an INI block omits that keyword. Field names and offsets come from",
        "the engine's own 16-byte-stride INI field-parse tables; defaults come from linear",
        "constant-tracking through each constructor.",
        "",
        "## Reading this",
        "",
        "- `-` in the default column means the constructor's write was not resolvable by",
        "  constant-tracking - typically a container or string built by a member",
        "  constructor, which is to say \"empty\". It does not mean the field is unset.",
        "- `type` is derived from the field's parse function. %d fields (%.0f%%) use a"
        % (unlabelled, 100.0 * unlabelled / total if total else 0),
        "  parse function that has not been identified and show its raw address instead.",
        "- Offsets are into ModuleData, not into the module instance.",
        "- Types are checked for internal consistency: no `Bool` resolves to a non-boolean.",
        "  Two float fields carry implausible magnitudes - `AimWeaponBehavior.AimFarDistance`",
        "  is a genuine `FLT_MAX`, `SlowDeathBehavior.FadeDelay` is a mis-tracked value.",
        "",
    ]
    for m in mods:
        if not m["fields"]:
            continue
        size = "0x%x" % m["moduledata_size"] if m["moduledata_size"] else "?"
        lines += ["## %s" % m["name"],
                  "",
                  "`sizeof(ModuleData)` = %s, %d field%s"
                  % (size, len(m["fields"]), "" if len(m["fields"]) == 1 else "s"),
                  "",
                  "| field | type | offset | default |",
                  "|---|---|---|---|"]
        for f in m["fields"]:
            lines.append("| `%s` | %s | `0x%x` | %s |"
                         % (f["name"], f["type"], f["offset"],
                            "`%s`" % f["default"] if f["default"] is not None else "-"))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary", help="path to game.dat")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--markdown", dest="md_out")
    ap.add_argument("--enums", dest="enum_out",
                    help="write the enum, lookup, sub-block and INI block schemas here")
    args = ap.parse_args()

    img = Image(args.binary)
    mods, types = extract(img)
    total = sum(len(m["fields"]) for m in mods)
    known = sum(1 for m in mods for f in m["fields"] if f["default"] is not None)
    print("modules: %d  fields: %d  defaults recovered: %d (%.0f%%)"
          % (len(mods), total, known, 100.0 * known / total if total else 0))
    print("enums: %d  lookups: %d  sub-blocks: %d  INI block types: %d"
          % (len(types["name_tables"]), len(types["lookup_tables"]), len(types["blocks"]),
             len(types["ini_blocks"])))

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(mods, fh, indent=1)
        print("wrote %s" % args.json_out)
    if args.md_out:
        with open(args.md_out, "w") as fh:
            fh.write(to_markdown(mods))
        print("wrote %s" % args.md_out)
    if args.enum_out:
        with open(args.enum_out, "w") as fh:
            json.dump(types, fh, indent=1)
        print("wrote %s" % args.enum_out)


if __name__ == "__main__":
    main()
