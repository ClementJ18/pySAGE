"""Execute the emitted x86 against synthetic engine objects and stdcall Windows APIs."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import SlavedUpdateIdlePatch, TextEntryClipboardPatch
from sage_patch.addresses import (
    GET_PROC_ADDRESS_IAT,
    TEXT_ENTRY_CLIPBOARD_ANCHORS,
    TEXT_ENTRY_CLIPBOARD_BYTES,
    TEXT_ENTRY_CLIPBOARD_HOOK,
    TEXT_ENTRY_CLIPBOARD_RESUME,
    TEXT_ENTRY_INPUT,
    TEXT_ENTRY_SET_CURSOR,
    UNICODE_STRING_DTOR,
)
from sage_patch.patches.text_entry_clipboard import APIS, CODE_OFFSET, SECTION_NAME, build_code
from sage_patch.registry import PATCHES
from sage_patch.utils import allocate_section, file_offset, find_section, read_bytes
from tests.sage_patch.test_patching import _tiny_pe


def image() -> bytearray:
    b = _tiny_pe()
    size = 0xA00000
    b.extend(bytes(size))
    struct.pack_into("<IIII", b, 0x178 + 8, size, 0x1000, size, 0x200)
    struct.pack_into("<I", b, 0x98 + 56, size + 0x1000)
    for va, old in (
        TEXT_ENTRY_CLIPBOARD_ANCHORS | {TEXT_ENTRY_CLIPBOARD_HOOK: TEXT_ENTRY_CLIPBOARD_BYTES}
    ).items():
        off = file_offset(b, va)
        b[off : off + len(old)] = old
    struct.pack_into("<II", b, 0x98 + 104, 0x1000, 60)
    for index, (name, slot) in enumerate(
        ((b"GetModuleHandleA", 0xBD0134), (b"GetProcAddress", GET_PROC_ADDRESS_IAT))
    ):
        off = file_offset(b, 0x401000 + 20 * index)
        struct.pack_into("<5I", b, off, 0x1100 + 8 * index, 0, 0, 0x1200, slot - 0x400000)
        struct.pack_into("<II", b, file_offset(b, 0x401100 + 8 * index), 0x1300 + 64 * index, 0)
        off = file_offset(b, 0x401300 + 64 * index)
        b[off : off + len(name) + 3] = b"\0\0" + name + b"\0"
    off = file_offset(b, 0x401200)
    b[off : off + 13] = b"kernel32.dll\0"
    return b


def test_registry_apply_verify_detect_and_only_hook_changes() -> None:
    b = image()
    p = TextEntryClipboardPatch()
    assert PATCHES[p.name] is type(p)
    assert p.detect(b) is None
    original = bytes(b)
    allocate_section(b, ".before", lambda _: b"other patch", 0x40000040)
    p.apply(b)
    assert p.verify(b) == [] and isinstance(p.detect(b), type(p))
    base, _, _ = find_section(b, SECTION_NAME)
    hook = read_bytes(b, TEXT_ENTRY_CLIPBOARD_HOOK, 8)
    assert hook[0] == 0xE9 and hook[5:] == b"\x90" * 3
    assert (
        TEXT_ENTRY_CLIPBOARD_HOOK + 5 + struct.unpack_from("<i", hook, 1)[0] == base + CODE_OFFSET
    )
    assert TEXT_ENTRY_CLIPBOARD_HOOK - 0x400000 == 0x322A8A
    # Original section contents change at exactly these eight bytes; PE headers change too.
    off = file_offset(b, TEXT_ENTRY_CLIPBOARD_HOOK)
    assert b[0x200:off] == original[0x200:off]
    assert b[off + 8 : len(original)] == original[off + 8 :]
    before = bytes(b)
    with pytest.raises(ValueError, match="already patched"):
        p.apply(b)
    assert b == before
    b[find_section(b, SECTION_NAME)[1] + CODE_OFFSET] ^= 1
    assert p.verify(b) and p.detect(b) is None


@pytest.mark.parametrize("va", [*TEXT_ENTRY_CLIPBOARD_ANCHORS, TEXT_ENTRY_CLIPBOARD_HOOK, 0x401342])
def test_wrong_contract_is_atomic(va: int) -> None:
    b = image()
    b[file_offset(b, va)] ^= 1
    before = bytes(b)
    with pytest.raises(ValueError):
        TextEntryClipboardPatch().apply(b)
    assert b == before


@pytest.mark.parametrize(
    "offset,value,width",
    [
        (0x98 + 28, 0x500000, 4),
        (0x84, 0x8664, 2),
        (0x98, 0x20B, 2),
        (0x98 + 70, 0x40, 2),
        (0x98 + 60, 0x1A0, 4),
    ],
)
def test_wrong_pe_or_full_headers_is_atomic(offset: int, value: int, width: int) -> None:
    b = image()
    struct.pack_into("<I" if width == 4 else "<H", b, offset, value)
    before = bytes(b)
    with pytest.raises(ValueError):
        TextEntryClipboardPatch().apply(b)
    assert b == before


class World:
    def __init__(self, text: str = "Äbcö", base: int = 0xF00000) -> None:
        uc = pytest.importorskip("unicorn")
        self.r = pytest.importorskip("unicorn.x86_const")
        self.u = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        for va, size in (
            (0x436000, 0x1000),
            (0x500000, 0x1000),
            (0x722000, 0x1000),
            (0xBD0000, 0x1000),
            (base, 0x1000),
            (0x10000000, 0x20000),
            (0x20000000, 0x10000),
        ):
            self.u.mem_map(va, size)
        self.base = base
        self.u.mem_write(base, build_code(base))
        self.entry = 0x10000000
        self.frame = 0x20008000
        self.backing = 0x10002000
        self.output = 0x10004000
        self.clip = 0x10008000
        self.display = 0x10001000
        self.text = text.encode("utf-16le")
        self.cliptext = "Üx\t\r\n😀y".encode("utf-16le") + b"\0\0"
        self.write(self.entry, self.display)
        self.write(self.display, self.display + 0x100)
        self.write(self.display + 0x108, 0x500A00)
        self.write(self.display + 0x10C, 0x500A10)
        self.write(self.backing, 1)
        self.u.mem_write(self.backing + 4, struct.pack("<H", len(self.text) // 2))
        self.u.mem_write(self.backing + 8, self.text + b"\0\0")
        self.u.mem_write(self.clip, self.cliptext)
        self.selection(1, 3)
        self.write(0xBD0134, 0x500000)
        self.write(GET_PROC_ADDRESS_IAT, 0x500100)
        self.fail = ""
        self.missing = ""
        self.null_string = False
        self.length = len(self.text) // 2
        self.clip_size = len(self.cliptext)
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.inserted: list[int] = []
        self.deleted = 0
        self.released = 0
        self.freed = 0
        self.owned = False
        self.open = False
        self.locked = False
        self.module_absent = False
        self.u.hook_add(uc.UC_HOOK_CODE, self.on_code)

    def write(self, address: int, value: int) -> None:
        self.u.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.u.mem_read(address, 4))[0]

    def selection(self, start: int, end: int) -> None:
        self.u.mem_write(self.entry + 0x1C, struct.pack("<HH", start, end))

    def string(self, address: int) -> str:
        return bytes(self.u.mem_read(address, 64)).split(b"\0", 1)[0].decode("ascii")

    def ret(self, value: int, count: int = 0) -> None:
        esp = self.u.reg_read(self.r.UC_X86_REG_ESP)
        self.u.reg_write(self.r.UC_X86_REG_EIP, self.read(esp))
        self.u.reg_write(self.r.UC_X86_REG_ESP, esp + 4 + 4 * count)
        self.u.reg_write(self.r.UC_X86_REG_EAX, value)
        self.u.reg_write(self.r.UC_X86_REG_ECX, 0xBADCC)
        self.u.reg_write(self.r.UC_X86_REG_EDX, 0xBADDD)

    def args(self, count: int) -> tuple[int, ...]:
        esp = self.u.reg_read(self.r.UC_X86_REG_ESP)
        return tuple(self.read(esp + 4 + 4 * i) for i in range(count))

    def on_code(self, u: object, address: int, size: int, user: object) -> None:
        if address == TEXT_ENTRY_CLIPBOARD_RESUME:
            self.u.emu_stop()
        elif address == 0x500000:
            assert self.string(self.args(1)[0]) in ("kernel32.dll", "user32.dll")
            self.ret(
                0
                if self.module_absent
                else (1 if self.string(self.args(1)[0]) == "user32.dll" else 2),
                1,
            )
        elif address == 0x500100:
            module, ptr = self.args(2)
            name = self.string(ptr)
            assert module == (1 if name in APIS[:6] else 2)
            self.ret(0 if name == self.missing else 0x500200 + 16 * APIS.index(name), 2)
        elif 0x500200 <= address < 0x500200 + 16 * len(APIS):
            name = APIS[(address - 0x500200) // 16]
            count = {
                "OpenClipboard": 1,
                "GetClipboardData": 1,
                "SetClipboardData": 2,
                "GlobalAlloc": 2,
                "GlobalFree": 1,
                "GlobalLock": 1,
                "GlobalUnlock": 1,
                "GlobalSize": 1,
            }.get(name, 0)
            args = self.args(count)
            self.calls.append((name, args))
            value = 1
            if name == self.fail:
                value = 0
            elif name == "GetForegroundWindow":
                value = 0x1234
            elif name == "OpenClipboard":
                assert not self.open
                self.open = True
            elif name == "CloseClipboard":
                assert self.open and not self.locked
                self.open = False
            elif name == "GetClipboardData":
                assert self.open and args == (13,)
                value = 0xBBBB
            elif name == "GlobalSize":
                value = self.clip_size
            elif name == "GlobalAlloc":
                assert args[0] == 2
                self.alloc_size = args[1]
                value = 0xAAAA
            elif name == "GlobalLock":
                assert not self.locked
                self.locked = True
                value = self.output if args[0] == 0xAAAA else self.clip
            elif name == "GlobalUnlock":
                assert self.locked
                self.locked = False
                value = 0  # zero can mean successful final unlock
            elif name == "EmptyClipboard":
                assert self.open and not self.locked
            elif name == "SetClipboardData":
                assert self.open and not self.locked and args == (13, 0xAAAA)
                self.owned = True
                value = 0xAAAA
            elif name == "GlobalFree":
                assert not self.owned and not self.locked
                self.freed += 1
            self.ret(value, count)
        elif address == 0x500A10:
            assert self.u.reg_read(self.r.UC_X86_REG_ECX) == self.display
            self.ret(self.length)
        elif address == 0x500A00:
            assert self.u.reg_read(self.r.UC_X86_REG_ECX) == self.display
            self.write(self.args(1)[0], 0 if self.null_string else self.backing)
            if not self.null_string:
                self.write(self.backing, self.read(self.backing) + 1)
            self.ret(self.args(1)[0], 1)
        elif address == UNICODE_STRING_DTOR:
            ptr = self.u.reg_read(self.r.UC_X86_REG_ECX)
            if self.read(ptr):
                assert self.read(ptr) == self.backing
                self.write(self.backing, self.read(self.backing) - 1)
                self.write(ptr, 0)
                self.released += 1
            self.ret(0)
        elif address == TEXT_ENTRY_SET_CURSOR:
            window, pos = self.args(2)
            assert window == 0x12345678
            self.u.mem_write(self.entry + 0x1C, struct.pack("<H", pos))
            self.ret(0)
        elif address == TEXT_ENTRY_INPUT:
            window, message, key, state = self.args(4)
            assert window == 0x12345678
            if message == 0x19:
                assert state == 0
                self.inserted.append(key)
            else:
                assert (message, key, state) == (0x15, 0xD3, 2)
                assert self.owned and not self.open
                self.deleted += 1
            self.ret(1)

    def run(self, key: int, modifier: int = 0xE) -> int:
        regs = ("EAX", "EBX", "ECX", "EDX", "ESI", "EDI", "EBP", "ESP")
        values = (0x111, 2, 0x333, 0, self.entry, 0x666, self.frame, 0x2000F000)
        for name, value in zip(regs, values, strict=True):
            self.u.reg_write(getattr(self.r, "UC_X86_REG_" + name), value)
        self.u.reg_write(self.r.UC_X86_REG_EFLAGS, 0x602)
        for offset, value in ((8, 0x12345678), (12, 0x15), (16, key), (20, modifier)):
            self.write(self.frame + offset, value)
        self.u.emu_start(self.base + CODE_OFFSET, TEXT_ENTRY_CLIPBOARD_RESUME, count=150000)
        assert self.u.reg_read(self.r.UC_X86_REG_EIP) == TEXT_ENTRY_CLIPBOARD_RESUME
        for name, value in zip(regs, values, strict=True):
            assert self.u.reg_read(getattr(self.r, "UC_X86_REG_" + name)) == value, name
        assert self.u.reg_read(self.r.UC_X86_REG_EFLAGS) == 0x602
        assert not self.open and not self.locked
        assert self.read(self.backing) == 1
        return self.read(self.frame + 12)


@pytest.mark.parametrize("key", [0x1E, 0x2E, 0x2D, 0x2F])
@pytest.mark.parametrize("modifier", [0, 2, 12, 0xCE, 0x8E])
def test_unrecognized_modifiers_preserve_original(key: int, modifier: int) -> None:
    w = World()
    assert w.run(key, modifier) == 0
    assert not w.calls and not w.inserted and not w.deleted


@pytest.mark.parametrize("key", [0xCB, 0xCD, 0xD3, 0x10, 0x30])
def test_other_scancodes_preserve_original(key: int) -> None:
    assert World().run(key) == 0


def test_select_all() -> None:
    w = World()
    assert w.run(0x1E) == 1
    assert bytes(w.u.mem_read(w.entry + 0x1C, 4)) == struct.pack("<HH", 4, 0)
    assert not w.calls


@pytest.mark.parametrize("key", [0x2E, 0x2D])
@pytest.mark.parametrize(
    "start,end,expected",
    [
        (1, 3, "bc"),
        (3, 1, "bc"),
        (0, 4, "Äbcö"),
        (1, 50, "bcö"),
        (50, 1, "bcö"),
        (0, 0, ""),
        (4, 4, ""),
        (50, 60, ""),
    ],
)
def test_copy_cut_selection_and_ownership(key: int, start: int, end: int, expected: str) -> None:
    w = World()
    w.selection(start, end)
    assert w.run(key) == 1
    assert w.deleted == int(key == 0x2D and bool(expected))
    assert w.owned == bool(expected)
    assert w.freed == 0
    if expected:
        encoded = expected.encode("utf-16le") + b"\0\0"
        assert w.alloc_size == len(encoded)
        assert bytes(w.u.mem_read(w.output, len(encoded))) == encoded
        assert w.released == 1


@pytest.mark.parametrize("key", [0x2E, 0x2D])
def test_secret_copy_cut_noop(key: int) -> None:
    w = World()
    w.u.mem_write(w.entry + 0x12, b"\1")
    assert w.run(key) == 1
    assert not w.calls and not w.deleted and not w.released


@pytest.mark.parametrize(
    "failure,freed",
    [
        ("GlobalAlloc", 0),
        ("GlobalLock", 1),
        ("GetForegroundWindow", 1),
        ("OpenClipboard", 1),
        ("EmptyClipboard", 1),
        ("SetClipboardData", 1),
    ],
)
def test_copy_failure_never_cuts_and_cleans_up(failure: str, freed: int) -> None:
    w = World()
    w.fail = failure
    assert w.run(0x2D) == 1
    assert not w.deleted and not w.owned
    assert w.freed == freed and w.released == 1


def test_null_string_and_backing_length_disagreement() -> None:
    w = World()
    w.null_string = True
    w.run(0x2D)
    assert not w.calls and not w.deleted
    w = World()
    w.length = 100
    w.selection(5, 80)
    w.run(0x2D)
    assert not w.calls and not w.deleted and w.released == 1


def test_paste_filters_and_reuses_original_input() -> None:
    w = World()
    assert w.run(0x2F) == 1
    assert w.inserted == [ord(c) for c in "Üxy"]
    assert not w.deleted and not w.owned and not w.freed


def test_surrogate_boundaries_preserve_neighboring_bmp_characters() -> None:
    w = World()
    units = (0xD7FF, 0xD800, 0xDBFF, 0xDC00, 0xDFFF, 0xE000, 0x00DF, 0)
    w.u.mem_write(w.clip, struct.pack("<8H", *units))
    w.clip_size = 16
    w.run(0x2F)
    assert w.inserted == [0xD7FF, 0xE000, 0x00DF]


@pytest.mark.parametrize("control", [4, 8, 12])
def test_both_ctrl_keys_and_shift_allow_shortcuts(control: int) -> None:
    w = World()
    assert w.run(0x2E, control | 2 | 0x0430) == 1
    assert w.owned


@pytest.mark.parametrize(
    "failure", ["OpenClipboard", "GetClipboardData", "GlobalLock", "GlobalSize"]
)
def test_paste_failures(failure: str) -> None:
    w = World()
    w.fail = failure
    assert w.run(0x2F) == 1
    assert not w.inserted and not w.freed


@pytest.mark.parametrize(
    "units,allocation,expected", [(5000, 10000, 4096), (3, 4, 2), (3, 5, 2), (3, 1, 0), (0, 2, 0)]
)
def test_paste_limit_and_unterminated_allocation(
    units: int, allocation: int, expected: int
) -> None:
    w = World()
    w.u.mem_write(w.clip, b"a\0" * units + b"\0\0")
    w.clip_size = allocation
    w.run(0x2F)
    assert w.inserted == [ord("a")] * expected


@pytest.mark.parametrize("name", APIS)
def test_missing_exports_are_noop(name: str) -> None:
    w = World()
    w.missing = name
    assert w.run(0x2D) == 1
    assert not w.calls and not w.deleted


def test_missing_module_is_noop() -> None:
    w = World()
    w.module_absent = True
    assert w.run(0x2F) == 1
    assert not w.calls


@pytest.mark.parametrize("base", [0xF00000, 0x1800000])
def test_disassembly_and_different_cave_locations(base: int) -> None:
    cs = pytest.importorskip("capstone")
    code = build_code(base)[CODE_OFFSET:]
    insns = list(cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_32).disasm(code, base + CODE_OFFSET))
    assert sum(i.size for i in insns) == len(code)
    starts = {i.address for i in insns}
    targets = {
        int(i.op_str, 16)
        for i in insns
        if i.mnemonic.startswith(("j", "call")) and i.op_str.startswith("0x")
    }
    assert targets - starts == {
        TEXT_ENTRY_CLIPBOARD_RESUME,
        TEXT_ENTRY_SET_CURSOR,
        TEXT_ENTRY_INPUT,
        UNICODE_STRING_DTOR,
    }
    w = World(base=base)
    assert w.run(0x2D) == 1 and w.deleted == 1


@pytest.mark.full
def test_real_rotwk_application_and_composition(tmp_path: Path) -> None:
    source = Path("tools/BFME-FILES/game.dat.backup")
    if not source.exists():
        pytest.skip("original RotWK 2.01 binary unavailable")
    original = source.read_bytes()
    for patches in (
        (TextEntryClipboardPatch(), SlavedUpdateIdlePatch()),
        (SlavedUpdateIdlePatch(), TextEntryClipboardPatch()),
    ):
        b = bytearray(original)
        for p in patches:
            p.apply(b)
        for p in patches:
            assert p.verify(b) == []
        (tmp_path / "clipboard.dat").write_bytes(b)
