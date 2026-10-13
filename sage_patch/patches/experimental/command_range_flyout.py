"""Opt-in, single-selection command flyout using the Palantir stance flyout.

Author: Ostkannit. Derivation: `../../docs/command-range-flyout.md`.
Both explicit CommandRange fields opt in; external stance updates cannot change the icon.
"""

from __future__ import annotations

from ... import addresses as addr
from ...asm import JA, JAE, JB, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, call_rel32, find_section, u32, va_to_offset
from ..utils.field_tables import read_field_table, resolve_table

__all__ = [
    "CommandRangeFlyoutPatch",
    "build_code",
    "ANCHORS",
    "HOOKS",
    "FIXED_PATCHES",
    "SUPPORTED_COMMANDS",
]

# Only these dispatcher cases have been inspected for a window-independent execution path.
# Target selection is supported for weapon/special-power commands through InGameUI itself.
SUPPORTED_COMMANDS = {
    14: "STOP",
    17: "EVACUATE",
    18: "EVACUATE_CONTESTED",
    23: "FIRE_WEAPON",
    24: "SPECIAL_POWER",
    27: "SWITCH_WEAPON",
    35: "TOGGLE_WEAPON",
    36: "HORDE_TOGGLE_FORMATION",
    37: "SPECIAL_POWER_TOGGLE",
    40: "CREW_EVACUATE",
    42: "CLOSE_GATE",
    43: "OPEN_GATE",
    44: "TOGGLE_GATE",
    45: "TOGGLE_WEAPONSET",
    48: "TOGGLE_NO_AUTO_ACQUIRE",
    49: "WAKE_AUTO_PICKUP",
    51: "START_SELF_REPAIR",
    52: "HORDE_SET_FORMATION",
    59: "START_NEIGHBORHOOD_REPAIR",
    60: "CANCEL_NEIGHBORHOOD",
}
_SECTION = ".cmdfly"
# CALL hooks have one callee-cleaned argument; parser table entries are absolute pointers.
HOOKS = {
    addr.STANCE_FLYOUT_CLICK_CALL: call_rel32(
        addr.STANCE_FLYOUT_CLICK_CALL, addr.STANCE_FLYOUT_SELECT
    ),
    addr.STANCE_HOTKEY_SELECT_CALL: call_rel32(
        addr.STANCE_HOTKEY_SELECT_CALL, addr.STANCE_FLYOUT_SELECT
    ),
    addr.STANCE_FLYOUT_STATE_CALL: call_rel32(addr.STANCE_FLYOUT_STATE_CALL, addr.FLYOUT_SET_STATE),
}

for _site in (addr.STANCE_OWNER_NOTIFY_INDEX_CALL, addr.STANCE_OWNER_INITIAL_INDEX_CALL):
    HOOKS[_site] = call_rel32(_site, addr.COMMAND_BUTTON_SET_STANCE_INDEX)
for _site in (addr.COMMAND_BUTTON_RANGE_START_FIELD + 4, addr.COMMAND_BUTTON_RANGE_COUNT_FIELD + 4):
    HOOKS[_site] = u32(addr.COMMAND_BUTTON_INI_INTEGER_PARSER)

# Widen only the boolean's initialization/copy into its three alignment bytes.
# The existing boolean value and the following +0x13C object are unchanged.
FIXED_PATCHES = {
    addr.COMMAND_BUTTON_RANGE_FLAGS_INIT: (
        bytes.fromhex("889e38010000"),
        bytes.fromhex("899e38010000"),
    ),
    addr.COMMAND_BUTTON_RANGE_FLAGS_COPY: (
        bytes.fromhex("8a85380100006a13888338010000"),
        bytes.fromhex("8b85380100006a13898338010000"),
    ),
}
ANCHORS = dict(addr.COMMAND_RANGE_FLYOUT_ANCHORS)
# These rows contain the two relocated parser pointers, verified through HOOKS instead.
_range_rows = ANCHORS.pop(addr.COMMAND_BUTTON_RANGE_START_FIELD)
for _offset, _size in ((0, 4), (8, 12), (24, 8)):
    ANCHORS[addr.COMMAND_BUTTON_RANGE_START_FIELD + _offset] = _range_rows[
        _offset : _offset + _size
    ]


def _replacement(site: int, target: int) -> bytes:
    return u32(target) if len(HOOKS[site]) == 4 else call_rel32(site, target)


def build_code(base_va: int) -> tuple[bytes, dict[int, int]]:
    """Emit thiscall-compatible wrappers and a shared fail-closed resolver.

    Resolver input: ECX owner, EDX stance value. EAX is -1 for an ordinary stance,
    zero for an unavailable range entry, or the target button with EDX = ControlBar.
    It preserves EBX/ESI/EDI/EBP. The wrappers preserve all integer registers.
    """
    a = Asm(base_va)
    entries = {addr.STANCE_FLYOUT_CLICK_CALL: a.va}
    a.emit(b"\x60\x8b\x54\x24\x24")  # pushad; edx = original stack argument
    a.call("resolve")
    a.emit(b"\x83\xf8\xff")
    a.jcc(JE, "vanilla_click")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "click_done")
    a.emit(
        b"\x6a\x00\x6a\x01\x50\x8b\xca"
    )  # native button, left-click, no queued-production modifier
    a.call_absolute(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "click_done")
    # Change presentation only after a successful child command, without a stance message.
    a.emit(b"\x8b\x74\x24\x18\x8b\x7e\x14\xff\x74\x24\x24")
    a.call_absolute(addr.STANCE_FIND_INDEX)
    a.emit(b"\x59\x50\x8b\xcf")
    a.call_absolute(addr.COMMAND_BUTTON_SET_STANCE_INDEX)
    a.emit(b"\x8b\x4e\x14")
    a.call_absolute(addr.COMMAND_BUTTON_STANCE_GUI_DATA)
    a.emit(b"\x50\xff\x76\x10")
    a.call_absolute(addr.STANCE_GUI_VALUES_SET)
    a.emit(b"\x83\xc4\x08")
    a.emit(b"\x8b\x4c\x24\x18\x8b\x49\x0c\x85\xc9")  # saved owner -> manager
    a.jcc(JE, "click_done")
    a.emit(b"\x8b\x01\xff\x50\x10\x85\xc0")
    a.jcc(JE, "click_done")
    a.emit(b"\x8b\xf8\x8b\xc8")
    a.call_absolute(addr.FLYOUT_IS_ACTIVE)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "click_done")
    a.emit(b"\x8b\xcf")
    a.call_absolute(addr.FLYOUT_REQUEST_CLOSE)
    a.label("click_done")
    a.emit(b"\x61\xc2\x04\x00")  # popad; ret 4, resumes at 0x0096f868
    a.label("vanilla_click")
    a.emit(0x61)
    a.jmp_absolute(addr.STANCE_FLYOUT_SELECT)

    entries[addr.STANCE_FLYOUT_STATE_CALL] = a.va
    a.emit(b"\x60\x8b\x51\x0c\x8b\x49\x08")  # GUI interface -> stance and owner
    a.call("resolve")
    a.emit(b"\x83\xf8\xff")
    a.jcc(JE, "state_done")
    a.emit(b"\xc7\x44\x24\x24\x01\x00\x00\x00\x85\xc0")
    a.jcc(JE, "state_done")
    a.emit(b"\xc7\x44\x24\x24\x06\x00\x00\x00")
    a.label("state_done")
    a.emit(0x61)
    a.jmp_absolute(addr.FLYOUT_SET_STATE)

    # Hotkeys invoke the selector directly, not the flyout click or stance observer.
    # Preserve the actual stance order, but do not choose/close a range entry or emit
    # its misleading stance feedback. Normal stance owners keep the full selector.
    entries[addr.STANCE_HOTKEY_SELECT_CALL] = a.va
    a.emit(0x60)
    a.call("is_range_owner")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "vanilla_hotkey")
    a.emit(b"\x8b\x54\x24\x24\x83\xfa\x01")
    a.jcc(JB, "hotkey_done")
    a.emit(b"\x83\xfa\x03")
    a.jcc(JA, "hotkey_done")
    a.emit(b"\x8b\x0d", u32(addr.THE_MESSAGE_STREAM))
    a.emit(b"\x85\xc9")
    a.jcc(JE, "hotkey_done")
    a.emit(b"\x8b\x01\x68\x68\x04\x00\x00\xff\x50\x48\x85\xc0")
    a.jcc(JE, "hotkey_done")
    a.emit(b"\xff\x74\x24\x24\x8b\xc8")
    a.call_absolute(addr.GAME_MESSAGE_APPEND_INTEGER)
    a.label("hotkey_done")
    a.emit(b"\x61\xc2\x04\x00")
    a.label("vanilla_hotkey")
    a.emit(0x61)
    a.jmp_absolute(addr.STANCE_FLYOUT_SELECT)

    # Both engine sites carry the owner in ESI, parent in ECX, index on the stack.
    for site in (addr.STANCE_OWNER_NOTIFY_INDEX_CALL, addr.STANCE_OWNER_INITIAL_INDEX_CALL):
        entries[site] = a.va
        a.emit(b"\x60\x8b\xce")
        a.call("is_range_owner")
        a.emit(b"\x85\xc0")
        a.jcc(JE, f"original_index_{site}")
        a.emit(b"\x61\xc2\x04\x00")
        a.label(f"original_index_{site}")
        a.emit(0x61)
        a.jmp_absolute(addr.COMMAND_BUTTON_SET_STANCE_INDEX)

    # INI parsers use four cdecl arguments. The field pointer determines the base,
    # so Command may appear before or after the range fields. Keep native integers.
    for row, offset, flag in (
        (addr.COMMAND_BUTTON_RANGE_START_FIELD, 0x22C, 1),
        (addr.COMMAND_BUTTON_RANGE_COUNT_FIELD, 0x230, 2),
    ):
        entries[row + 4] = a.va
        a.emit(b"\x8b\x44\x24\x0c\x80\x88", u32(0x139 - offset), flag)
        a.jmp_absolute(addr.COMMAND_BUTTON_INI_INTEGER_PARSER)

    # EAX is boolean; ECX and all nonvolatile registers are preserved.
    a.label("is_range_owner")
    a.emit(b"\x33\xc0\x85\xc9")
    a.jcc(JE, "not_range")
    a.emit(b"\x8b\x41\x14\x85\xc0")
    a.jcc(JE, "not_range")
    a.emit(b"\x83\x78\x14\x39")
    a.jcc(JNE, "not_range")
    a.emit(b"\x80\xb8\x39\x01\x00\x00\x03")
    a.jcc(JNE, "not_range")
    a.emit(b"\x8b\x41\x0c\x85\xc0")
    a.jcc(JE, "not_range")
    a.emit(b"\x81\x38", u32(addr.PALANTIR_STANCE_FACTORY_VTABLE))
    a.jcc(JNE, "not_range")
    a.emit(b"\x8b\x40\x10\x85\xc0")
    a.jcc(JE, "not_range")
    a.emit(b"\x8b\x00\x85\xc0")
    a.jcc(JE, "not_range")
    a.emit(b"\x81\x38", u32(addr.PALANTIR_FLYOUT_WRAPPER_VTABLE))
    a.jcc(JNE, "not_range")
    a.emit(b"\x6a\x01\x58\xc3")
    a.label("not_range")
    a.emit(b"\x33\xc0\xc3")

    a.label("resolve")
    a.emit(b"\x55\x8b\xec\x83\xec\x24\x53\x56\x57")
    a.emit(b"\x89\x4d\xfc\x89\x55\xf8")
    a.call("is_range_owner")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "ordinary")
    a.emit(b"\x8b\x79\x14\x89\x7d\xec")
    a.emit(b"\x0f\xbe\x05", u32(addr.COMMAND_SET_CAPACITY_IMMEDIATE))
    a.emit(b"\x83\xf8\x21")
    a.jcc(JB, "disabled")
    a.emit(b"\x83\xf8\x7f")
    a.jcc(JA, "disabled")
    a.emit(b"\x89\x45\xe0\x8b\x97\x2c\x02\x00\x00\x3b\xd0")
    a.jcc(JAE, "disabled")  # unsigned rejects negative starts
    a.emit(b"\x2b\xc2\x8b\x8f\x30\x02\x00\x00\x85\xc9")
    a.jcc(JE, "disabled")
    a.emit(b"\x83\xf9\x03")
    a.jcc(JA, "disabled")
    a.emit(b"\x3b\xc8")
    a.jcc(JA, "disabled")
    a.emit(b"\xff\x75\xf8")
    a.call_absolute(addr.STANCE_FIND_INDEX)  # EDI = opener; caller cleans the argument
    a.emit(b"\x59\x3b\x87\x30\x02\x00\x00")
    a.jcc(JAE, "disabled")
    a.emit(b"\x03\x87\x2c\x02\x00\x00\x89\x45\xe4")
    a.emit(b"\x8b\x1d", u32(addr.THE_COMMAND_SET_STORE))
    a.emit(b"\x85\xdb")
    a.jcc(JE, "disabled")
    a.emit(b"\x83\x7b\x70\x07")  # merged selection has different CommandSet semantics
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\x73\x6c\x85\xf6")
    a.jcc(JE, "disabled")
    # Require exactly the selected drawable, not just a surviving +0x6c from a prior selection.
    a.emit(b"\x8b\x0d", u32(addr.THE_IN_GAME_UI))
    a.emit(b"\x85\xc9")
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\x01\xff\x90\x24\x01\x00\x00\x85\xc0")
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\x10\x85\xd2")
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\x02\x3b\xc2")
    a.jcc(JE, "disabled")
    a.emit(b"\x39\x10")  # first->next == head
    a.jcc(JNE, "disabled")
    a.emit(b"\x39\x70\x08")
    a.jcc(JNE, "disabled")
    a.emit(b"\x8b\xb6\xfc\x00\x00\x00\x85\xf6")
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\x45\xfc\x8b\x48\x08\x85\xc9")
    a.jcc(JE, "disabled")
    a.call_absolute(addr.COMMAND_UI_GET_OBJECT_ID)
    a.emit(b"\x8b\x0d", u32(addr.THE_GAME_LOGIC))
    a.emit(b"\x85\xc9")
    a.jcc(JE, "disabled")
    a.emit(0x50)
    a.call_absolute(addr.GAME_LOGIC_FIND_OBJECT_BY_ID)
    a.emit(b"\x3b\xc6")
    a.jcc(JNE, "disabled")
    a.emit(b"\x8b\x0d", u32(addr.THE_PLAYER_LIST))
    a.emit(b"\x85\xc9")
    a.jcc(JE, "disabled")
    a.call_absolute(addr.PLAYER_LIST_LOCAL_IS_NOT_ACTIVE)
    a.emit(b"\x84\xc0")
    a.jcc(JNE, "disabled")
    a.emit(b"\x8b\xce")
    a.call_absolute(addr.OBJECT_GET_COMMAND_SET_STRING)
    a.emit(b"\x50\x8b\xcb")
    a.call_absolute(addr.COMMAND_SET_STORE_FIND_COMMAND_SET)
    a.emit(b"\x89\x45\xe8\x8b\xce")
    a.call_absolute(addr.OBJECT_GET_ALTERNATE_COMMAND_SET_OBJECT)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "have_set")
    a.emit(b"\x83\xc0\x70\x50\x8b\xcb")
    a.call_absolute(addr.COMMAND_SET_STORE_FIND_COMMAND_SET)
    a.emit(b"\x89\x45\xe8")
    a.label("have_set")
    a.emit(b"\x83\x7d\xe8\x00")
    a.jcc(JE, "disabled")
    # The opener must still belong to this effective set. No cached button survives a set switch.
    a.emit(b"\x33\xff")
    a.label("find_opener")
    a.emit(b"\x57\x8b\x4d\xe8")
    a.call_absolute(addr.COMMAND_SET_GET_COMMAND_BUTTON)
    a.emit(b"\x3b\x45\xec")
    a.jcc(JE, "get_target")
    a.emit(b"\x47\x3b\x7d\xe0")
    a.jcc(JB, "find_opener")
    a.jmp("disabled")
    a.label("get_target")
    a.emit(b"\xff\x75\xe4\x8b\x4d\xe8")
    a.call_absolute(addr.COMMAND_SET_GET_COMMAND_BUTTON)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "disabled")
    a.emit(b"\x8b\xf8\x8b\x47\x14")
    for command in SUPPORTED_COMMANDS:
        a.emit(b"\x83\xf8", command)
        a.jcc(JE, "supported_command")
    a.jmp("disabled")
    a.label("supported_command")
    # Passive, script-only, autocast and cancelable commands need separate UI contracts.
    a.emit(b"\xf7\x47\x1c\x00\x00\x08\xb0")
    a.jcc(JNE, "disabled")
    for command in (23, 24, 37):
        a.emit(b"\x83\xf8", command)
        a.jcc(JE, "power_or_weapon")
    a.emit(b"\xf7\x47\x1c\x27\x02\x00\x00")
    a.jcc(JNE, "disabled")
    a.jmp("check_enabled")
    a.label("power_or_weapon")
    a.emit(b"\x83\xf8\x17")
    a.jcc(JE, "check_enabled")
    a.emit(b"\x83\x7f\x44\x00")  # native special-power paths dereference the template
    a.jcc(JE, "disabled")
    a.label("check_enabled")
    a.emit(b"\x80\xbf\x0c\x01\x00\x00\x00")
    a.jcc(JNE, "disabled")
    a.emit(b"\x80\xbf\x05\x01\x00\x00\x00")
    a.jcc(JE, "disabled")
    a.emit(b"\x6a\x00\x8d\x45\xdc\x50\x56\x6a\x00\x57\x8b\xcb")
    a.call_absolute(addr.CONTROL_BAR_GET_COMMAND_AVAILABILITY)
    a.emit(b"\x48\x83\xf8\x01")  # only availability 1 and 2 map to GUI _up
    a.jcc(JA, "disabled")
    a.emit(b"\x8b\xc7\x8b\xd3")
    a.jmp("return")
    a.label("ordinary")
    a.emit(b"\x83\xc8\xff")
    a.jmp("return")
    a.label("disabled")
    a.emit(b"\x33\xc0")
    a.label("return")
    a.emit(b"\x5f\x5e\x5b\xc9\xc3")
    return a.finish(), entries


def _problems(data: bytes | bytearray, expected: dict[int, bytes]) -> list[str]:
    problems = []
    for va, blob in expected.items():
        off = va_to_offset(data, va)
        if off is None or bytes(data[off : off + len(blob)]) != blob:
            problems.append(f"{va:#010x}: expected {blob.hex()}")
    return problems


class CommandRangeFlyoutPatch(Patch):
    """A bounded command flyout; ordinary stance owners tail-call the original code."""

    name = "command-range-flyout"
    author = "Ostkannit"
    experimental = True
    description = (
        "Palantir command flyout (powers, weapons, formations, gates, evacuation, repair): "
        "TOGGLE_STANCE with explicit CommandRangeStart and "
        "CommandRangeCount (at most three); single selection only"
    )

    def apply(self, data: bytearray) -> None:
        problems = _problems(data, ANCHORS | HOOKS | {k: v[0] for k, v in FIXED_PATCHES.items()})
        if problems:
            raise ValueError("CommandRange flyout signature mismatch: " + "; ".join(problems))
        # Field-adding patches keep prior table copies for their own verification. Update
        # every exact stock row pair, including the live table and those retained copies.
        live = resolve_table(
            data,
            addr.COMMAND_BUTTON_FIELD_TABLE_REFS,
            addr.COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
            "CommandButton",
        )
        rows = read_field_table(data, live)
        expected_rows = tuple(
            tuple(int.from_bytes(_range_rows[i + j : i + j + 4], "little") for j in range(0, 16, 4))
            for i in (0, 16)
        )
        if not any(rows[i : i + 2] == expected_rows for i in range(len(rows) - 1)):
            raise ValueError("CommandRange flyout: live range parser rows differ")
        va = allocate_section(data, _SECTION, lambda base: build_code(base)[0], 0x60000020)
        _, entries = build_code(va)
        for site, target in entries.items():
            off = va_to_offset(data, site)
            assert off is not None
            apply_byte_patch(data, off, HOOKS[site], _replacement(site, target), self.name)
        replacement_rows = bytearray(_range_rows)
        for row_offset in (0, 16):
            site = addr.COMMAND_BUTTON_RANGE_START_FIELD + row_offset + 4
            replacement_rows[row_offset + 4 : row_offset + 8] = u32(entries[site])
        offset = data.find(_range_rows)
        while offset != -1:
            data[offset : offset + len(_range_rows)] = replacement_rows
            offset = data.find(_range_rows, offset + len(_range_rows))
        for site, (old, new) in FIXED_PATCHES.items():
            off = va_to_offset(data, site)
            assert off is not None
            apply_byte_patch(data, off, old, new, self.name)

    def verify(self, data: bytes | bytearray) -> list[str]:
        section = find_section(data, _SECTION)
        if section is None:
            return [f"{_SECTION} section is absent"]
        va, off, _ = section
        code, entries = build_code(va)
        problems = _problems(
            data,
            ANCHORS
            | {site: _replacement(site, target) for site, target in entries.items()}
            | {k: v[1] for k, v in FIXED_PATCHES.items()},
        )
        try:
            live = resolve_table(
                data,
                addr.COMMAND_BUTTON_FIELD_TABLE_REFS,
                addr.COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
                "CommandButton",
            )
            rows = read_field_table(data, live)
            for row_offset in (0, 16):
                name = int.from_bytes(_range_rows[row_offset : row_offset + 4], "little")
                site = addr.COMMAND_BUTTON_RANGE_START_FIELD + row_offset + 4
                expected = (name, entries[site], 0, 0x22C + row_offset // 4)
                if expected not in rows:
                    problems.append("live CommandRange parser does not point to the cave")
        except ValueError as exc:
            problems.append(str(exc))
        if bytes(data[off : off + len(code)]) != code:
            problems.append("CommandRange flyout cave differs")
        return problems
