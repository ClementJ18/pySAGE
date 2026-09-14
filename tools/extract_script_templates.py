"""Extract the script action and condition templates from `worldbuilder.exe` into
`sage_worldbuilder/script_templates.json`.

A template is what the script editor offers under "New action" / "New condition": an internal
name (`MOVE_NAMED_UNIT_TO`, the name a map stores), the UI tree path, the sentence fragments shown
between the parameters, and each parameter's type. WorldBuilder fills two fixed tables of `0x80`-
byte records in two functions, one for actions (`WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT`) and
one for conditions (`WORLDBUILDER_SCRIPT_CONDITION_TEMPLATES_INIT`). Both are debug-build code
that loads every value from an immediate, so a small symbolic evaluation over registers and
`ebp` stack slots recovers each write without running anything. See
`sage_patch/docs/worldbuilder-script-templates.md` for the layout and the evidence.

The output is the table as written, last write winning. A count field and the slots actually
written can disagree (the editor's own source has a few such slips); those slots are recorded as
`null` rather than guessed.

    python tools/extract_script_templates.py [path/to/worldbuilder.exe] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_EAX, X86_REG_EBP, X86_REG_ECX

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sage_patch import addresses  # noqa: E402

__all__ = ["extract_templates", "render_templates"]

DEFAULT_EXE = REPO_ROOT / "worldbuilder.exe"
OUTPUT = REPO_ROOT / "sage_worldbuilder" / "script_templates.json"

# Where record 0 starts inside the table owner, the record size, and how many records are actions
# (the engine's `ScriptActions::executeAction` switch is bounded at 600 cases).
TABLE_BASE = 0x20
RECORD_SIZE = 0x80
ACTION_COUNT = 600

FLAGS = 0x00
UI_NAME = 0x04
INTERNAL_NAME = 0x0C
UI_STRING_COUNT = 0x14
UI_STRINGS = 0x18
MAX_UI_STRINGS = 12
PARAMETER_COUNT = 0x48
PARAMETERS = 0x4C
MAX_PARAMETERS = 13

PARAMETER_TYPE_COUNT = 78
# Enum parameter types whose `getUiText` case looks the value's name up, either through a nested
# jump table (one `push "name"` per entry) or by indexing an array of string pointers.
_TABLE_VALUE_TYPES = (6, 20, 27, 30, 36, 37, 38, 57, 63, 68)
# The two enum types `getUiText` names by comparing the value instead: Boolean (case 0x00AAD5B7)
# and near/far (case 0x00AADA03), listed in value order.
_COMPARED_VALUES = {8: ["FALSE", "TRUE"], 56: ["near", "far"]}

_STRING_SETTERS = frozenset(
    {
        addresses.WORLDBUILDER_ASCIISTRING_SET,
        addresses.WORLDBUILDER_ASCIISTRING_SET_2,
        addresses.WORLDBUILDER_ASCIISTRING_SET_LENGTH,
    }
)
# Calls whose result is not a template value; anything else stops the extraction.
_IGNORED_CALLS = frozenset({addresses.WORLDBUILDER_STRLEN})

Value = tuple[str, int]  # ("this", offset) or ("const", value)


class ExtractionError(RuntimeError):
    """The code no longer matches the model: a new instruction shape or an unresolved write."""


@dataclass
class _State:
    registers: dict[int, Value | None] = field(default_factory=dict)
    slots: dict[int, Value | None] = field(default_factory=dict)
    pushes: list[Value | None] = field(default_factory=list)


class _Image:
    def __init__(self, exe: Path) -> None:
        pe = pefile.PE(str(exe), fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.data = pe.get_memory_mapped_image()

    def cstring(self, va: int) -> str:
        offset = va - self.base
        return self.data[offset : self.data.find(b"\0", offset)].decode("latin-1")


def _record_writes(image: _Image, start: int) -> dict[int, tuple[Any, int]]:
    """Evaluate one table-filling function from `start` to its `ret`: every write into the table
    owner (`this`, passed in `ecx`), keyed by offset, as `(value, instruction address)`."""
    disassembler = Cs(CS_ARCH_X86, CS_MODE_32)
    disassembler.detail = True
    state = _State(registers={X86_REG_ECX: ("this", 0)})
    writes: dict[int, tuple[Any, int]] = {}

    def value_of(operand: Any) -> Value | None:
        if operand.type == X86_OP_IMM:
            return ("const", operand.imm)
        if operand.type == X86_OP_REG:
            return state.registers.get(operand.reg)
        if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_EBP:
            return state.slots.get(operand.mem.disp)
        return None

    code = image.data[start - image.base :]
    for insn in disassembler.disasm(code, start):
        mnemonic, operands = insn.mnemonic, insn.operands
        if mnemonic == "ret":
            return writes
        if mnemonic == "mov":
            target, source = operands
            if target.type == X86_OP_REG:
                state.registers[target.reg] = value_of(source)
            elif target.type == X86_OP_MEM and target.mem.base == X86_REG_EBP:
                state.slots[target.mem.disp] = value_of(source)
            elif target.type == X86_OP_MEM:
                owner, value = state.registers.get(target.mem.base), value_of(source)
                if owner is None or owner[0] != "this" or value is None or value[0] != "const":
                    raise ExtractionError(f"unresolved write at {insn.address:#x}: {insn.op_str}")
                writes[owner[1] + target.mem.disp] = (value[1], insn.address)
        elif mnemonic in ("add", "or") and operands[0].type == X86_OP_REG:
            current, operand = state.registers.get(operands[0].reg), value_of(operands[1])
            if current is None or operand is None or operand[0] != "const":
                state.registers[operands[0].reg] = None
            elif mnemonic == "add":
                state.registers[operands[0].reg] = (current[0], current[1] + operand[1])
            elif current[0] == "const":
                state.registers[operands[0].reg] = ("const", current[1] | operand[1])
            else:
                state.registers[operands[0].reg] = None
        elif mnemonic == "push":
            state.pushes.append(value_of(operands[0]))
        elif mnemonic == "call":
            called = operands[0].imm if operands[0].type == X86_OP_IMM else None
            if called in _STRING_SETTERS:
                owner = state.registers.get(X86_REG_ECX)
                text = state.pushes[-1] if state.pushes else None
                if owner is None or owner[0] != "this" or text is None or text[0] != "const":
                    raise ExtractionError(f"unresolved string set at {insn.address:#x}")
                writes[owner[1]] = (image.cstring(text[1]), insn.address)
                state.registers[X86_REG_EAX] = None
            elif called == addresses.WORLDBUILDER_SCRIPT_TEMPLATE_FLAGS_OR:
                first, second = state.pushes[-1], state.pushes[-2]
                if first is None or second is None:
                    raise ExtractionError(f"unresolved flags at {insn.address:#x}")
                state.registers[X86_REG_EAX] = ("const", first[1] | second[1])
            elif called in _IGNORED_CALLS:
                state.registers[X86_REG_EAX] = None
            else:
                raise ExtractionError(f"unexpected call at {insn.address:#x}: {insn.op_str}")
            state.pushes.clear()
        elif mnemonic not in ("test", "je", "jmp", "sub", "pop", "leave"):
            raise ExtractionError(f"unmodelled instruction at {insn.address:#x}: {mnemonic}")
    raise ExtractionError(f"no ret after {start:#x}")


def _pushed_string(image: _Image, disassembler: Cs, start: int) -> str:
    for insn in disassembler.disasm(image.data[start - image.base :], start):
        if insn.mnemonic == "push" and insn.operands[0].type == X86_OP_IMM:
            return image.cstring(insn.operands[0].imm)
        if insn.address - start > 0x20:
            break
    raise ExtractionError(f"no pushed string at {start:#x}")


def _case_value_names(image: _Image, disassembler: Cs, case: int) -> list[str]:
    """The value names one `getUiText` case prints: from the last non-zero bound it compares the
    value against, and the jump table or string array it then indexes."""
    bound = None
    for insn in disassembler.disasm(image.data[case - image.base :], case):
        if insn.mnemonic == "cmp" and insn.operands[1].type == X86_OP_IMM and insn.operands[1].imm:
            bound = insn.operands[1].imm
        table = next(
            (
                operand.mem.disp & 0xFFFFFFFF
                for operand in insn.operands
                if operand.type == X86_OP_MEM and operand.mem.scale == 4 and operand.mem.disp
            ),
            None,
        )
        if table is not None and bound is not None:
            if insn.mnemonic == "jmp":  # `cmp value, last; ja default; jmp [value*4 + table]`
                count = bound + 1
                entries = struct.unpack_from(f"<{count}I", image.data, table - image.base)
                return [_pushed_string(image, disassembler, entry) for entry in entries]
            pointers = struct.unpack_from(f"<{bound}I", image.data, table - image.base)
            return [image.cstring(pointer) for pointer in pointers]
        if insn.mnemonic == "ret" or insn.address - case > 0x200:
            break
    raise ExtractionError(f"no value table in the getUiText case at {case:#x}")


def extract_parameter_values(image: _Image) -> dict[str, list[str]]:
    disassembler = Cs(CS_ARCH_X86, CS_MODE_32)
    disassembler.detail = True
    switch = addresses.WORLDBUILDER_PARAMETER_UI_TEXT_SWITCH - image.base
    cases = struct.unpack_from(f"<{PARAMETER_TYPE_COUNT}I", image.data, switch)
    values = {
        kind: _case_value_names(image, disassembler, cases[kind]) for kind in _TABLE_VALUE_TYPES
    }
    values.update(_COMPARED_VALUES)
    return {str(kind): values[kind] for kind in sorted(values)}


def _slots(record: dict[int, Any], first: int, count: int) -> list[Any]:
    return [record.get(first + 4 * index) for index in range(count)]


def extract_templates(exe: Path) -> dict[str, Any]:
    image = _Image(exe)
    writes: dict[int, tuple[Any, int]] = {}
    for start in (
        addresses.WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT,
        addresses.WORLDBUILDER_SCRIPT_CONDITION_TEMPLATES_INIT,
    ):
        writes.update(_record_writes(image, start))

    records: dict[int, dict[int, Any]] = {}
    for offset, (value, _address) in writes.items():
        index, field_offset = divmod(offset - TABLE_BASE, RECORD_SIZE)
        if index < 0:
            raise ExtractionError(f"write below the table at offset {offset:#x}")
        records.setdefault(index, {})[field_offset] = value

    templates = []
    for index in sorted(records):
        record = records[index]
        ui_string_count = record.get(UI_STRING_COUNT, 0)
        parameter_count = record.get(PARAMETER_COUNT, 0)
        if ui_string_count > MAX_UI_STRINGS or parameter_count > MAX_PARAMETERS:
            raise ExtractionError(f"record {index} has out-of-range counts")
        is_action = index < ACTION_COUNT
        templates.append(
            {
                "kind": "action" if is_action else "condition",
                "id": index if is_action else index - ACTION_COUNT,
                "internal_name": record.get(INTERNAL_NAME),
                "ui_name": record.get(UI_NAME),
                "flags": record.get(FLAGS, 0),
                "ui_strings": _slots(record, UI_STRINGS, ui_string_count),
                "parameters": _slots(record, PARAMETERS, parameter_count),
            }
        )
    return {
        "source": {"file": exe.name, "sha1": hashlib.sha1(exe.read_bytes()).hexdigest()},
        "templates": templates,
        "parameter_values": extract_parameter_values(image),
    }


def render_templates(catalogue: dict[str, Any]) -> str:
    return json.dumps(catalogue, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", nargs="?", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="fail if the file on disk is out of date"
    )
    args = parser.parse_args(argv)

    rendered = render_templates(extract_templates(args.exe))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if current != rendered:
            print(f"{args.out} is out of date", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
