"""Read-only queries against the ROTWK `game.dat` image, for exploring the engine.

Every RE session in this repo starts with the same five questions - where does this string live,
who references that address, what is the code there, what is in this table, and do we already know
this address - and each one used to be answered by writing another throwaway capstone script (see
the hardcoded-path leftovers in `sage_patch/scripts/`). They are answered here instead, so a
session spends its budget on reading disassembly rather than on re-deriving how to obtain it.

Nothing here writes: patching is `sage_patch.patcher`'s job, and keeping this side read-only is
what makes it safe to point at a live install's binary.

Addresses are **virtual addresses** everywhere (ImageBase `0x400000`), because that is what the
docs, `sage_patch.addresses` and Ghidra all speak; `--offset` prints the file offset when a byte
edit needs one. Accepts `0x9cdf23`, `9cdf23`, or a `game.dat+0x5cdf23` as Cheat Engine reports it.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

REPO_ROOT = Path(__file__).resolve().parents[3]
# Run by path from anywhere, so the repo is not necessarily on sys.path the way `cd repo && python
# -c` puts it there.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sage_patch import addresses as known  # noqa: E402
from sage_patch.pe import Section, image_sections  # noqa: E402
from sage_patch.utils import image_base, va_to_offset  # noqa: E402

_md = Cs(CS_ARCH_X86, CS_MODE_32)
_md.detail = True


@dataclass(frozen=True)
class Image:
    """One `game.dat`, addressed by VA."""

    path: Path
    data: bytes
    base: int
    sections: list[Section]

    @classmethod
    def load(cls, path: Path) -> Image:
        data = path.read_bytes()
        return cls(path, data, image_base(data), image_sections(data))

    def offset(self, va: int) -> int | None:
        return va_to_offset(self.data, va)

    def section_of(self, va: int) -> Section | None:
        return next((s for s in self.sections if s.contains(va)), None)

    def read(self, va: int, size: int) -> bytes:
        off = self.offset(va)
        return b"" if off is None else self.data[off : off + size]

    def dword(self, va: int) -> int | None:
        raw = self.read(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    def cstring(self, va: int, limit: int = 200) -> str | None:
        """The NUL-terminated string at `va`, or None when it is not printable text."""
        raw = self.read(va, limit)
        end = raw.find(b"\x00")
        if end <= 0:
            return None
        text = raw[:end]
        if any(b < 0x09 or 0x0E <= b < 0x20 or b >= 0x7F for b in text):
            return None
        return text.decode("latin-1")

    def to_va(self, offset: int) -> int | None:
        for section in self.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                return section.virtual_address + (offset - section.raw_offset)
        return None


def parse_va(text: str) -> int:
    """`0x9cdf23`, `9cdf23`, or Cheat Engine's `game.dat+0x5cdf23` (an RVA)."""
    text = text.strip()
    if "+" in text:
        _, _, rva = text.partition("+")
        return 0x400000 + int(rva, 16)
    return int(text, 16)


def _describe(image: Image, va: int) -> str:
    """What a dword value looks like it is: a string, a known name, or where it points."""
    parts = []
    names = _known_names(va)
    if names:
        parts.append(" = ".join(names))
    text = image.cstring(va, 64)
    if text:
        parts.append(f'"{text}"')
    section = image.section_of(va)
    if section and not parts:
        parts.append(section.name)
    return "  ; " + " ".join(parts) if parts else ""


def _hex(value: int) -> str:
    """Constants include negative frame offsets (`EBP-0x20`), which `%08x` renders as nonsense."""
    return f"-0x{-value:x}" if value < 0 else f"0x{value:08x}"


def _known_names(va: int) -> list[str]:
    """Names `sage_patch.addresses` gives this exact address - the repo's own symbol table."""
    return sorted(
        name
        for name, value in vars(known).items()
        if name.isupper() and isinstance(value, int) and value == va
    )


# --- commands ---------------------------------------------------------------------------------


def cmd_sections(image: Image, args: argparse.Namespace) -> int:
    print(f"{image.path}  {len(image.data)} bytes  ImageBase 0x{image.base:08x}")
    for section in image.sections:
        end = section.virtual_address + section.mapped_size
        print(
            f"  {section.name:<9} VA {section.virtual_address:08x}-{end:08x}"
            f"  file 0x{section.raw_offset:06x}+0x{section.raw_size:x}"
        )
    return 0


def cmd_dis(image: Image, args: argparse.Namespace) -> int:
    va = parse_va(args.va)
    code = image.read(va, args.count * 16 + 16)
    if not code:
        print(f"0x{va:08x} is not mapped", file=sys.stderr)
        return 1
    for n, ins in enumerate(_md.disasm(code, va)):
        if n >= args.count:
            break
        target = _branch_target(ins)
        note = _describe(image, target) if target is not None else ""
        print(f"  {ins.address:08x}  {ins.bytes.hex():<20} {ins.mnemonic:<7} {ins.op_str}{note}")
    return 0


def _branch_target(ins) -> int | None:
    """The VA a `call`/`jmp`/`jcc` names directly, for annotating the listing."""
    if ins.mnemonic.startswith(("call", "j")) and ins.op_str.startswith("0x"):
        return int(ins.op_str, 16)
    return None


def cmd_fn(image: Image, args: argparse.Namespace) -> int:
    """Disassemble from `va` to the `ret` no internal branch jumps past.

    A linear sweep that stops at the first `ret` truncates any function with an early return, and
    one that never stops runs into the next function. Tracking the furthest internal branch target
    is the cheap approximation: the body is over when a terminator is reached and nothing inside
    it wanted to go further.
    """
    va = parse_va(args.va)
    furthest = va
    printed = 0
    while printed < args.max:
        code = image.read(va, 4096)
        if not code:
            break
        for ins in _md.disasm(code, va):
            target = _branch_target(ins)
            note = _describe(image, target) if target is not None else ""
            print(
                f"  {ins.address:08x}  {ins.bytes.hex():<20} {ins.mnemonic:<7} {ins.op_str}{note}"
            )
            printed += 1
            va = ins.address + ins.size
            if target is not None and ins.address < target < ins.address + 0x2000:
                furthest = max(furthest, target)
            if ins.mnemonic.startswith("ret") and va > furthest:
                return 0
            if printed >= args.max:
                print(f"  ... stopped at {args.max} instructions (--max to go further)")
                return 0
        else:
            continue
        break
    return 0


def cmd_xref(image: Image, args: argparse.Namespace) -> int:
    """Every reference to a VA: dword pointers to it anywhere, and direct branches at it."""
    va = parse_va(args.va)
    needle = struct.pack("<I", va)
    pointers: list[tuple[int, str]] = []
    start = 0
    while (hit := image.data.find(needle, start)) >= 0:
        start = hit + 1
        ref_va = image.to_va(hit)
        if ref_va is None:
            continue
        section = image.section_of(ref_va)
        pointers.append((ref_va, section.name if section else "?"))
    branches = _direct_branches(image, va)

    print(f"references to 0x{va:08x}{_describe(image, va)}")
    print(f"  {len(pointers)} dword references (immediates and pointer tables)")
    for ref_va, name in pointers[: args.max]:
        context = _context(image, ref_va) if name == ".text" else ""
        print(f"    {ref_va:08x}  {name}{context}")
    if len(pointers) > args.max:
        print(f"    ... {len(pointers) - args.max} more (--max)")
    print(f"  {len(branches)} direct branches (call/jmp rel32, rel8)")
    for ref_va, mnemonic in branches[: args.max]:
        print(f"    {ref_va:08x}  {mnemonic}")
    if len(branches) > args.max:
        print(f"    ... {len(branches) - args.max} more (--max)")
    return 0


def _context(image: Image, va: int) -> str:
    """The instruction whose immediate sits at `va`, decoded from a few bytes before it.

    Printed with its own address, which is the one to hand to `dis`/`fn` - the reference address
    is where the four bytes sit, a byte or more into the instruction that carries them.

    An imm32 is the tail of its instruction, so the opcode is 1..6 bytes earlier; the shortest
    decode that ends exactly at the immediate's end is the one that owns it.
    """
    for back in range(1, 8):
        for ins in _md.disasm(image.read(va - back, 16), va - back):
            if ins.size == back + 4:
                return f"  {ins.address:08x}: {ins.mnemonic} {ins.op_str}"
            break
    return ""


def _direct_branches(image: Image, target: int) -> list[tuple[int, str]]:
    """Superset scan of `.text` for a direct branch landing on `target`.

    Decoding at every byte offset rather than sweeping linearly: a sweep desyncs on inlined data
    and silently drops call sites, which is a false negative you cannot see. This yields false
    positives instead, which the listing makes obvious.
    """
    section = next((s for s in image.sections if s.name == ".text"), None)
    if section is None:
        return []
    code = image.data[section.raw_offset : section.raw_offset + section.raw_size]
    base = section.virtual_address
    out: list[tuple[int, str]] = []
    for off in range(len(code) - 6):
        byte = code[off]
        va = base + off
        if byte in (0xE8, 0xE9):
            if va + 5 + struct.unpack_from("<i", code, off + 1)[0] == target:
                out.append((va, "call" if byte == 0xE8 else "jmp"))
        elif byte == 0xEB or 0x70 <= byte <= 0x7F:
            if va + 2 + struct.unpack_from("<b", code, off + 1)[0] == target:
                out.append((va, "jmp short" if byte == 0xEB else "jcc short"))
        elif byte == 0x0F and 0x80 <= code[off + 1] <= 0x8F:
            if va + 6 + struct.unpack_from("<i", code, off + 2)[0] == target:
                out.append((va, "jcc"))
    return out


def cmd_str(image: Image, args: argparse.Namespace) -> int:
    """Literal strings matching a pattern, with their VAs - the way into a stripped image."""
    pattern = re.compile(args.pattern.encode("latin-1"), 0 if args.case else re.IGNORECASE)
    found = 0
    for section in image.sections:
        if args.section and section.name != args.section:
            continue
        blob = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        for match in re.finditer(rb"[\x20-\x7e]{%d,}\x00" % args.min, blob):
            text = match.group()[:-1]
            if not pattern.search(text):
                continue
            va = image.to_va(section.raw_offset + match.start())
            print(f"  {va:08x}  {section.name:<8} {text.decode('latin-1')!r}")
            found += 1
            if found >= args.max:
                print(f"  ... stopped at {args.max} matches (--max)")
                return 0
    if not found:
        print("  no match")
    return 0


def cmd_table(image: Image, args: argparse.Namespace) -> int:
    """A NULL-terminated INI field-parse table: {char *name, ParseFn, void *userData, offset}."""
    va = parse_va(args.va)
    for index in range(args.max):
        entry = image.read(va + index * 16, 16)
        if len(entry) < 16:
            break
        name_ptr, parse_fn, userdata, offset = struct.unpack("<IIII", entry)
        if name_ptr == 0:
            size = index * 16 + 16
            print(f"  [{index:2}] (terminator)  {index} entries, 0x{size:x} bytes with it")
            return 0
        name = image.cstring(name_ptr, 64)
        print(
            f"  [{index:2}] {name!r:<28} parse=0x{parse_fn:08x} userData=0x{userdata:08x}"
            f" offset=0x{offset:x} ({offset})"
        )
    return 0


def _data_sections(image: Image):
    return [s for s in image.sections if s.name in (".rdata", ".data")]


def _string_vas(image: Image, text: str) -> list[int]:
    """Every VA in a data section holding exactly `text` as a NUL-terminated string."""
    needle = b"\x00" + text.encode("latin-1") + b"\x00"
    out = []
    for section in _data_sections(image):
        blob = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        start = 0
        while True:
            at = blob.find(needle, start)
            if at < 0:
                break
            out.append(section.virtual_address + at + 1)
            start = at + 1
    return out


def _dword_refs(image: Image, target: int) -> list[int]:
    """Every 4-aligned data slot holding `target` - a table row's `name` field, among others."""
    needle = struct.pack("<I", target)
    out = []
    for section in _data_sections(image):
        blob = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        start = 0
        while True:
            at = blob.find(needle, start)
            if at < 0:
                break
            if at % 4 == 0:
                out.append(section.virtual_address + at)
            start = at + 1
    return out


def _row_ok(image: Image, va: int) -> bool:
    """Whether the 16 bytes at `va` read as a plausible `{name, parseFn, userData, offset}` row."""
    raw = image.read(va, 16)
    if len(raw) < 16:
        return False
    name_ptr, parse_fn, _userdata, offset = struct.unpack("<IIII", raw)
    if not name_ptr or offset >= 0x4000:
        return False
    section = image.section_of(parse_fn)
    if section is None or section.name != ".text":
        return False
    name = image.cstring(name_ptr, 64)
    return bool(name) and len(name) >= 2 and name[0].isalpha()


def cmd_keyword(image: Image, args: argparse.Namespace) -> int:
    """The field-parse table(s) an INI keyword is a row of, each dumped in full.

    A row starts with the keyword's string pointer, so a data slot holding that pointer *is* a
    row: walk back to the table's first row and forward to its terminator. This reaches a block
    the recovered JSON does not cover, and it names the parse function - the field's type.
    """
    seen: set[int] = set()
    for string_va in _string_vas(image, args.name):
        for row_va in _dword_refs(image, string_va):
            if not _row_ok(image, row_va):
                continue
            first = row_va
            while _row_ok(image, first - 16):
                first -= 16
            if first in seen:
                continue
            seen.add(first)
            print(f"  table 0x{first:08x} ({args.name} is row {(row_va - first) // 16})")
            cmd_table(image, argparse.Namespace(va=hex(first), max=args.max))
    if not seen:
        print(f"  {args.name!r} is in no field-parse table (not an INI keyword of this build)")
    return 0


def cmd_ptrs(image: Image, args: argparse.Namespace) -> int:
    """A run of dwords - a vtable, a jump table, a descriptor array - each one described."""
    va = parse_va(args.va)
    for index in range(args.count):
        at = va + index * 4
        value = image.dword(at)
        if value is None:
            break
        print(f"  [{index:2}] {at:08x}: 0x{value:08x}{_describe(image, value)}")
    return 0


def cmd_hex(image: Image, args: argparse.Namespace) -> int:
    va = parse_va(args.va)
    raw = image.read(va, args.count)
    if not raw:
        # The PE headers are the common case: they are mapped at ImageBase but belong to no section.
        print(f"0x{va:08x} is in no section (headers, or past the image)", file=sys.stderr)
        return 1
    for row in range(0, len(raw), 16):
        chunk = raw[row : row + 16]
        text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        print(f"  {va + row:08x}  {chunk.hex(' '):<47}  {text}")
    return 0


# --- the recovered INI surface ------------------------------------------------------------------
#
# `scripts/module_defaults.py` already read the engine's own tables out of a `game.dat` and wrote
# them down; these commands read that JSON back rather than re-deriving it. Regenerate after a
# patch changes a table (the command is in sage_patch/README.md, "Module reference").

INI_TYPES = REPO_ROOT / "sage_patch" / "docs" / "ini-types.json"
MODULE_REFERENCE = REPO_ROOT / "sage_patch" / "docs" / "module-reference.json"


def _load(path: Path):
    if not path.is_file():
        print(f"missing {path} - regenerate with scripts/module_defaults.py", file=sys.stderr)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_enum(image: Image, args: argparse.Namespace) -> int:
    """An engine name table: the tokens INI accepts, in the order the engine stores them.

    Order is the whole point - a flag's index is its bit, so an enum member is what a mask test
    like `test byte [tmpl+0x109], 5` is really naming.
    """
    types = _load(INI_TYPES)
    if types is None:
        return 2
    tables = {**types["types"], **types["enums"]}
    name = next((k for k in tables if k.lower() == args.name.lower()), None)
    if name is None:
        try:
            va_key = f"0x{parse_va(args.name):08x}"
        except ValueError:
            va_key = None
        if va_key not in types["name_tables"]:
            print("known enums: " + ", ".join(sorted(tables)))
            return 1
        members, name = types["name_tables"][va_key], va_key
    else:
        members = types["name_tables"][tables[name]]
        va_key = tables[name]
    print(f"{name}  table {va_key}  {len(members)} members")
    for index, member in enumerate(members):
        print(f"  [{index:3}] bit 0x{1 << (index % 8):02x} of byte +0x{index // 8:x}  {member}")
    return 0


def cmd_block(image: Image, args: argparse.Namespace) -> int:
    """An INI block or module as the engine parses it: parse function, field offsets, defaults."""
    types = _load(INI_TYPES)
    modules = _load(MODULE_REFERENCE)
    if types is None or modules is None:
        return 2
    wanted = args.name.lower()
    for source, entries in (("ini_blocks", types["ini_blocks"]), ("blocks", types["blocks"])):
        name = next((k for k in entries if k.lower() == wanted), None)
        if name:
            entry = entries[name]
            print(f"{name}  ({source})  parse_fn=0x{entry['parse_fn']:08x}", end="")
            if entry.get("moduledata_ctor"):
                print(f"  moduledata_ctor=0x{entry['moduledata_ctor']:08x}", end="")
            print()
            for keyword in entry.get("keywords", []):
                print(f"  sub-block: {keyword}")
            _print_fields(entry.get("fields", []))
            break
    module = next((m for m in modules if m["name"].lower() == wanted), None)
    if module:
        print(
            f"{module['name']}  (module-reference)  moduledata {module['moduledata_size']} bytes"
            f"  ctor=0x{module['moduledata_ctor']:08x}  interface mask {module['interface_mask']}"
        )
        _print_fields(module["fields"], own_only=args.own)
        return 0
    matches = [k for k in {**types["ini_blocks"], **types["blocks"]} if wanted in k.lower()]
    matches += [m["name"] for m in modules if wanted in m["name"].lower()]
    if not matches:
        print(f"no block, ini block or module named like {args.name!r}")
        return 1
    return 0


def _print_fields(fields: list[dict], own_only: bool = False) -> None:
    for field in fields:
        if own_only and field.get("inherited"):
            continue
        inherited = f"  <- {field['inherited_from']}" if field.get("inherited") else ""
        default = "" if field.get("default") is None else f"  default={field['default']}"
        print(
            f"  +0x{field['offset']:<4x} {field['name']:<34} {field['type']:<18}"
            f"{default}{inherited}"
        )


def cmd_known(image: Image, args: argparse.Namespace) -> int:
    """What this repo already knows - `sage_patch.addresses` by address or by name.

    Always the first move on an address. The repo carries 400-odd named addresses for this build
    and 80-odd RE write-ups; re-deriving one of them by hand is the most common way to waste a
    session.
    """
    query = args.query
    print(f"build: {known.BUILD}")
    try:
        va = parse_va(query)
    except ValueError:
        va = None
    if va is None:
        needle = query.upper()
        for name, value in sorted(vars(known).items()):
            if name.isupper() and isinstance(value, int) and needle in name:
                print(f"  {name} = {_hex(value)}")
        return 0

    exact = _known_names(va)
    for name in exact:
        print(f"  0x{va:08x} is {name}")
    # Only a *near* neighbour is evidence of anything: the constants are scattered across the
    # image, so the nearest one to an arbitrary address is usually an unrelated function.
    near = [
        (value, name)
        for name, value in vars(known).items()
        if name.isupper() and isinstance(value, int) and 0 <= va - value <= 0x400
    ]
    if near and not exact:
        for value, name in sorted(near, reverse=True):
            print(f"  inside/near {name} = 0x{value:08x}  (+0x{va - value:x})")
    offset = image.offset(va)
    section = image.section_of(va)
    where = f"{section.name} " if section else "unmapped "
    print(f"  {where}file offset 0x{offset:x}" if offset is not None else f"  {where}")
    print(f"  grep the write-ups: grep -rin '{va:x}' sage_patch/docs sage_patch/patches")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--game",
        type=Path,
        default=REPO_ROOT / "game.dat",
        help="the game.dat to read (default: the repo root's)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sections", help="section table and ImageBase").set_defaults(fn=cmd_sections)

    p = sub.add_parser("known", help="what sage_patch.addresses names (VA or name substring)")
    p.add_argument("query")
    p.set_defaults(fn=cmd_known)

    p = sub.add_parser("dis", help="disassemble at a VA")
    p.add_argument("va")
    p.add_argument("--count", type=int, default=24)
    p.set_defaults(fn=cmd_dis)

    p = sub.add_parser("fn", help="disassemble a whole function")
    p.add_argument("va")
    p.add_argument("--max", type=int, default=400)
    p.set_defaults(fn=cmd_fn)

    p = sub.add_parser("xref", help="pointers to a VA, and direct branches at it")
    p.add_argument("va")
    p.add_argument("--max", type=int, default=40)
    p.set_defaults(fn=cmd_xref)

    p = sub.add_parser("str", help="literal strings matching a regex")
    p.add_argument("pattern")
    p.add_argument("--section", help="restrict to one section, e.g. .rdata")
    p.add_argument("--min", type=int, default=4, help="minimum string length")
    p.add_argument("--case", action="store_true", help="case-sensitive")
    p.add_argument("--max", type=int, default=60)
    p.set_defaults(fn=cmd_str)

    p = sub.add_parser("table", help="dump an INI field-parse table")
    p.add_argument("va")
    p.add_argument("--max", type=int, default=200)
    p.set_defaults(fn=cmd_table)

    p = sub.add_parser("keyword", help="find the field-parse table(s) an INI keyword is a row of")
    p.add_argument("name")
    p.add_argument("--max", type=int, default=200)
    p.set_defaults(fn=cmd_keyword)

    p = sub.add_parser("ptrs", help="dump a run of dwords (vtable, jump table, descriptors)")
    p.add_argument("va")
    p.add_argument("--count", type=int, default=16)
    p.set_defaults(fn=cmd_ptrs)

    p = sub.add_parser("enum", help="an engine name table (KindOf, ModelCondition, ...)")
    p.add_argument("name")
    p.set_defaults(fn=cmd_enum)

    p = sub.add_parser("block", help="an INI block or module: field offsets, types, defaults")
    p.add_argument("name")
    p.add_argument("--own", action="store_true", help="hide fields inherited from a base module")
    p.set_defaults(fn=cmd_block)

    p = sub.add_parser("hex", help="hexdump at a VA")
    p.add_argument("va")
    p.add_argument("--count", type=int, default=64)
    p.set_defaults(fn=cmd_hex)

    args = parser.parse_args(argv)
    if not args.game.is_file():
        print(f"no game.dat at {args.game} (pass --game)", file=sys.stderr)
        return 2
    return args.fn(Image.load(args.game), args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:  # piping a long listing into `head`
        sys.stderr.close()
