"""Tests for the multi-contain patch.

Ten sites lose a load of `Object+0x258` (or, at the two `onExit`s, a single release call) to a
`call` into the cave. What could be wrong without raising is the cave itself: which contain `pick`
settles on, that every other register comes back, and that each stand-in hands the site the
register it used to load. So `pick`, `release` and every stand-in are run under emulation over a
fake object whose contain modules answer as scripted.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch import MultiContainPatch
from sage_patch.addresses import (
    AI_ENTER_ON_EXIT_RELEASE_BYTES,
    AI_GROUP_ENTER_FILTER_MEMBER_TEST,
    AI_GROUP_ENTER_FILTER_TARGET,
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CAN_ENTER_OBJECT_CONTAIN_LOAD,
    CONTAIN_IS_SLAUGHTER_SLOT,
    CONTAIN_IS_VALID_CONTAINER_FOR_SLOT,
    CONTAIN_RIDER_INTENT_RELEASE,
    CONTAIN_RIDER_INTENT_SLOT,
    DRAWABLE_OBJECT,
    ENTER_HINT_CONTAIN_LOAD,
    ENTER_HINT_SLAUGHTER_TEST_BYTES,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_CONTAIN,
    OBJECT_MODULE_LIST,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
)
from sage_patch.patches.multi_contain import (
    ANCHORS,
    EAX,
    EBP,
    EBX,
    ECX,
    EDI,
    EDX,
    ESI,
    LOAD_SITES,
    RELEASE_SITES,
    SECTION_NAME,
    build_code,
    hooks,
    stock_windows,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import multi_contain_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return multi_contain_image()


@pytest.fixture
def patched() -> bytearray:
    data = multi_contain_image()
    MultiContainPatch().apply(data)
    return data


class TestStructure:
    def test_every_load_site_is_the_contain_field(self) -> None:
        """Each rewritten load is `mov r32, [r32+0x258]` naming the destination and the target
        the cave was told about."""
        for va, (stock, dst, target, _rider) in LOAD_SITES.items():
            assert stock[0] == 0x8B, f"{va:#x}"
            assert stock[1] == 0x80 | (dst << 3) | target, f"{va:#x}"
            assert struct.unpack_from("<I", stock, 2)[0] == OBJECT_CONTAIN, f"{va:#x}"
        hint = _read(multi_contain_image(), ENTER_HINT_CONTAIN_LOAD, 6)
        assert hint == bytes([0x8B, 0x80 | (EBX << 3) | EDI]) + struct.pack("<I", OBJECT_CONTAIN)

    def test_the_release_is_the_intent_slot_with_the_release_phase(self) -> None:
        tail = bytes([0x6A, CONTAIN_RIDER_INTENT_RELEASE, 0x53, 0xFF, 0x50])
        assert AI_ENTER_ON_EXIT_RELEASE_BYTES.endswith(tail + bytes([CONTAIN_RIDER_INTENT_SLOT]))
        assert set(RELEASE_SITES.values()) == {AI_ENTER_ON_EXIT_RELEASE_BYTES}

    def test_the_hint_and_the_cave_ask_the_same_slaughter_slot(self) -> None:
        assert ENTER_HINT_SLAUGHTER_TEST_BYTES[4:7] == bytes(
            [0xFF, 0x50, CONTAIN_IS_SLAUGHTER_SLOT]
        )

    def test_the_group_test_is_the_valid_slot(self) -> None:
        stock = _read(multi_contain_image(), AI_GROUP_ENTER_FILTER_MEMBER_TEST, 15)
        assert stock[9:11] == b"\xff\x90"
        assert struct.unpack_from("<I", stock, 11)[0] == CONTAIN_IS_VALID_CONTAINER_FOR_SLOT

    def test_each_site_now_calls_its_own_entry(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        edits = hooks(_cave_va(patched))
        assert len(edits) == 10
        targets = set()
        for va, (stock, want) in edits.items():
            got = _read(patched, va, len(stock))
            assert got == want
            listing = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(got, va)]
            calls = [line for line in listing if line.startswith("call")]
            assert len(calls) == 1 and all(
                line == "nop" for line in listing[listing.index(calls[0]) + 1 :]
            )
            targets.add(calls[0])
        # the two releases share one routine; every other site has its own
        assert len(targets) == 9

    def test_nothing_past_a_rewrite_moves(self, patched: bytearray) -> None:
        edits = hooks(_cave_va(patched))
        for va, stock in stock_windows().items():
            width = len(edits[va][0]) if va in edits else 0
            assert _read(patched, va + width, len(stock) - width) == stock[width:], f"{va:#x}"


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert MultiContainPatch().verify(patched) == []
        assert isinstance(MultiContainPatch.detect(patched), MultiContainPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert MultiContainPatch().verify(image) != []
        assert MultiContainPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            MultiContainPatch().apply(patched)

    @pytest.mark.parametrize("va", sorted(stock_windows()), ids=lambda va: f"{va:08x}")
    def test_any_stock_window_differing_refuses_before_writing(
        self, image: bytearray, va: int
    ) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="not the expected build"):
            MultiContainPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["multi-contain"] is MultiContainPatch
        assert not MultiContainPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_REGS = {
    EAX: UC_X86_REG_EAX,
    ECX: UC_X86_REG_ECX,
    EDX: UC_X86_REG_EDX,
    EBX: UC_X86_REG_EBX,
    EBP: UC_X86_REG_EBP,
    ESI: UC_X86_REG_ESI,
    EDI: UC_X86_REG_EDI,
}

_PAGE = 0x1000
_CAVE = 0x01200000
_STACK = 0x30000000
_STUBS = 0x40000000
_TARGET = 0x20000000
_MODULE_LIST = _TARGET + 0x800
_RIDER = 0x21000000
_RIDER_TEMPLATE = _RIDER + 0x800
_DRAWABLE = 0x22000000
_SELECTION = 0x23000000
_COMMAND = 0x24000000
_RETURN = 0x50000000  # where an emulated routine returns to; never mapped

#: The `__thiscall` stubs a contain's slots point at; the hook below answers each one.
_GET_CONTAIN, _IS_SLAUGHTER, _IS_VALID, _INTENT = (_STUBS + k for k in (0, 0x10, 0x20, 0x30))
_STUB_CODE = {
    _GET_CONTAIN: b"\xc3",  # ret
    _IS_SLAUGHTER: b"\xc3",  # ret
    _IS_VALID: b"\xc2\x0c\x00",  # ret 0xc
    _INTENT: b"\xc2\x08\x00",  # ret 8
}


def _module_va(index: int) -> int:
    return _TARGET + _PAGE * (1 + index)


class _Target:
    """A target object whose module list is `modules`, each `(name, slaughter, accepts)` or
    `None` for a module that is not a contain. The contain at `OBJECT_CONTAIN` is the module
    named `primary`, or none."""

    def __init__(self, modules: list[tuple[str, bool, bool] | None], primary: str | None) -> None:
        self.modules = modules
        self.primary = primary

    def contain_va(self, name: str) -> int:
        for index, module in enumerate(self.modules):
            if module is not None and module[0] == name:
                return _module_va(index) + 0x20
        raise KeyError(name)


def _machine(
    data: bytes | bytearray, target: _Target, rider_flags: tuple[bool, bool] = (False, False)
):
    """An emulator holding the cave, the target and a rider. `rider_flags` is
    `(KindOf HORDE, status HORDE_MEMBER)`. Returns the machine, the call log and the names by
    contain address."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave_va = _cave_va(data)
    pages = {cave_va & ~0xFFF, (cave_va & ~0xFFF) + _PAGE, _STACK, _STUBS, _TARGET}
    pages |= {_RIDER, _DRAWABLE, _SELECTION, _COMMAND}
    pages |= {_module_va(i) for i in range(len(target.modules))}
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    code = build_code(cave_va)
    uc.mem_write(cave_va, _read(data, cave_va, len(code)))
    for va, body in _STUB_CODE.items():
        uc.mem_write(va, body)

    names: dict[int, str] = {}
    answers: dict[int, tuple[bool, bool]] = {}
    uc.mem_write(_TARGET + OBJECT_MODULE_LIST, struct.pack("<I", _MODULE_LIST))
    for index, module in enumerate(target.modules):
        base = _module_va(index)
        behavior, behavior_vt, contain_vt = (
            base + BEHAVIOR_MODULE_INTERFACE,
            base + 0x100,
            base + 0x200,
        )
        uc.mem_write(behavior, struct.pack("<I", behavior_vt))
        uc.mem_write(behavior_vt + BEHAVIOR_GET_CONTAIN_SLOT, struct.pack("<I", _GET_CONTAIN))
        if module is not None:
            name, slaughter, accepts = module
            contain = base + 0x20
            names[contain] = name
            answers[contain] = (slaughter, accepts)
            uc.mem_write(contain, struct.pack("<I", contain_vt))
            uc.mem_write(contain_vt + CONTAIN_IS_SLAUGHTER_SLOT, struct.pack("<I", _IS_SLAUGHTER))
            uc.mem_write(
                contain_vt + CONTAIN_IS_VALID_CONTAINER_FOR_SLOT, struct.pack("<I", _IS_VALID)
            )
            uc.mem_write(contain_vt + CONTAIN_RIDER_INTENT_SLOT, struct.pack("<I", _INTENT))
        uc.mem_write(_MODULE_LIST + 4 * index, struct.pack("<I", base))
    uc.mem_write(_MODULE_LIST + 4 * len(target.modules), bytes(4))
    primary = target.contain_va(target.primary) if target.primary else 0
    uc.mem_write(_TARGET + OBJECT_CONTAIN, struct.pack("<I", primary))

    horde, member = rider_flags
    uc.mem_write(_RIDER + 4, struct.pack("<I", _RIDER_TEMPLATE))
    uc.mem_write(_RIDER_TEMPLATE + KINDOF_HORDE_BYTE, bytes([KINDOF_HORDE_BIT if horde else 0]))
    member_byte = OBJECT_STATUS + OBJECT_STATUS_HORDE_MEMBER // 8
    member_bit = 1 << (OBJECT_STATUS_HORDE_MEMBER % 8)
    uc.mem_write(_RIDER + member_byte, bytes([member_bit if member else 0]))

    calls: list[tuple[str, str, tuple[int, ...]]] = []

    def on_stub(uc: Uc, address: int, _size: int, _data: object) -> None:
        ecx = uc.reg_read(UC_X86_REG_ECX)
        esp = uc.reg_read(UC_X86_REG_ESP)
        if address == _GET_CONTAIN:
            # `this` is the behaviour interface at module+0xC; contain modules answer module+0x20
            module = ecx - BEHAVIOR_MODULE_INTERFACE
            contain = module + 0x20
            uc.reg_write(UC_X86_REG_EAX, contain if contain in names else 0)
        elif address == _IS_SLAUGHTER:
            calls.append(("slaughter", names[ecx], ()))
            uc.reg_write(UC_X86_REG_EAX, int(answers[ecx][0]))
        elif address == _IS_VALID:
            args = struct.unpack("<3I", bytes(uc.mem_read(esp + 4, 12)))
            calls.append(("valid", names[ecx], args))
            uc.reg_write(UC_X86_REG_EAX, 0xAAAAAA00 | int(answers[ecx][1]))
        elif address == _INTENT:
            args = struct.unpack("<2I", bytes(uc.mem_read(esp + 4, 8)))
            calls.append(("intent", names[ecx], args))

    uc.hook_add(UC_HOOK_CODE, on_stub, begin=_STUBS, end=_STUBS + 0x40)
    return uc, calls, names


def _run(uc: Uc, entry: int, regs: dict[int, int], args: tuple[int, ...] = ()) -> dict[int, int]:
    """Call `entry` with `regs` set and `args` pushed (cdecl order), and return every register
    once it has returned to `_RETURN`, plus `ESP` relative to where it started."""
    esp = _STACK + 0x800
    for arg in reversed(args):
        esp -= 4
        uc.mem_write(esp, struct.pack("<I", arg))
    esp -= 4
    uc.mem_write(esp, struct.pack("<I", _RETURN))
    start = esp + 4 + 4 * len(args)
    uc.reg_write(UC_X86_REG_ESP, esp)
    for reg, value in regs.items():
        uc.reg_write(_REGS[reg], value)
    uc.emu_start(entry, _RETURN, count=4096)
    assert uc.reg_read(UC_X86_REG_EIP) == _RETURN
    out = {reg: uc.reg_read(uc_reg) for reg, uc_reg in _REGS.items()}
    out[-1] = uc.reg_read(UC_X86_REG_ESP) - start
    return out


def _labels(data: bytes | bytearray) -> dict[str, int]:
    """Every routine's entry, read back from where the sites call."""
    cave_va = _cave_va(data)
    entries = {}
    for va, (_stock, patched) in hooks(cave_va).items():
        at = patched.index(0xE8)
        entries[va] = va + at + 5 + struct.unpack_from("<i", patched, at + 1)[0]
    return {"pick": cave_va, **{f"{va:08x}": entry for va, entry in entries.items()}}


_SAVED = {EBX: 0x0B0B0B0B, ESI: 0x05050505, EDI: 0x0D0D0D0D, EBP: 0x0E0E0E0E}


def _pick(patched: bytearray, target: _Target, **kwargs):
    uc, calls, names = _machine(patched, target, **kwargs)
    out = _run(uc, _labels(patched)["pick"], dict(_SAVED), (_TARGET, _RIDER))
    assert out[-1] == 0, "pick is __stdcall, ret 8"
    assert all(out[reg] == value for reg, value in _SAVED.items())
    return names.get(out[EAX], out[EAX]), calls


#: The Edain lair: tribute-cart slaughter first, wight tunnel last (so at `OBJECT_CONTAIN`).
def _lair(tunnel_accepts: bool, slaughter_accepts: bool) -> _Target:
    return _Target(
        [None, ("slaughter", True, slaughter_accepts), None, ("tunnel", False, tunnel_accepts)],
        "tunnel",
    )


class TestPick:
    def test_the_usual_contain_wins_when_it_accepts(self, patched: bytearray) -> None:
        picked, calls = _pick(patched, _lair(True, True))
        assert picked == "tunnel"
        assert calls == [("valid", "tunnel", (_RIDER, 0, 0))]

    def test_a_cart_goes_to_the_slaughter(self, patched: bytearray) -> None:
        picked, calls = _pick(patched, _lair(False, True))
        assert picked == "slaughter"
        assert calls == [
            ("valid", "tunnel", (_RIDER, 0, 0)),
            ("slaughter", "slaughter", ()),
            ("valid", "slaughter", (_RIDER, 0, 0)),
        ]

    def test_nobody_accepting_reads_as_stock(self, patched: bytearray) -> None:
        picked, _calls = _pick(patched, _lair(False, False))
        assert picked == "tunnel"

    def test_a_contain_that_keeps_passengers_is_never_second(self, patched: bytearray) -> None:
        """Gandalf's shape: a hobbit transport ahead of the ring slaughter at `OBJECT_CONTAIN`."""
        target = _Target([("transport", False, True), ("ring", True, False)], "ring")
        picked, calls = _pick(patched, target)
        assert picked == "ring"
        assert ("valid", "transport", (_RIDER, 0, 0)) not in calls

    def test_the_first_accepting_slaughter_wins(self, patched: bytearray) -> None:
        target = _Target(
            [("a", True, False), ("b", True, True), ("c", True, True), ("usual", False, False)],
            "usual",
        )
        assert _pick(patched, target)[0] == "b"

    @pytest.mark.parametrize("flags", [(True, False), (False, True)], ids=["horde", "member"])
    def test_hordes_stay_with_the_usual_contain(
        self, patched: bytearray, flags: tuple[bool, bool]
    ) -> None:
        picked, calls = _pick(patched, _lair(False, True), rider_flags=flags)
        assert (picked, calls) == ("tunnel", [])

    def test_no_contain_at_all(self, patched: bytearray) -> None:
        assert _pick(patched, _Target([("slaughter", True, True)], None)) == (0, [])


class TestRelease:
    def test_every_contain_on_the_target_releases_the_rider(self, patched: bytearray) -> None:
        uc, calls, _names = _machine(patched, _lair(True, True))
        entry = _labels(patched)[f"{min(RELEASE_SITES):08x}"]
        out = _run(uc, entry, dict(_SAVED), (_TARGET, _RIDER))
        assert out[-1] == 0, "release is __stdcall, ret 8"
        assert all(out[reg] == value for reg, value in _SAVED.items())
        release = (_RIDER, CONTAIN_RIDER_INTENT_RELEASE)
        assert calls == [("intent", "slaughter", release), ("intent", "tunnel", release)]


class TestSites:
    @pytest.mark.parametrize("va", sorted(LOAD_SITES), ids=lambda va: f"{va:08x}")
    def test_each_load_hands_back_the_picked_contain(self, patched: bytearray, va: int) -> None:
        """Only the destination changes, and it holds what `pick` chose for that site's rider."""
        _stock, dst, target, rider = LOAD_SITES[va]
        uc, _calls, names = _machine(patched, _lair(False, True))
        regs = {reg: 0x1000 * (reg + 1) for reg in _REGS}
        regs[target], regs[rider] = _TARGET, _RIDER
        out = _run(uc, _labels(patched)[f"{va:08x}"], dict(regs))
        assert out[-1] == 0, "a plain call/ret"
        assert names[out[dst]] == "slaughter"
        assert all(out[reg] == value for reg, value in regs.items() if reg != dst)

    def test_the_hint_reads_the_first_selected_object(self, patched: bytearray) -> None:
        uc, _calls, names = _machine(patched, _lair(False, True))
        head, node = _SELECTION + 0x100, _SELECTION + 0x200
        uc.mem_write(_SELECTION, struct.pack("<I", head))  # the list's head
        uc.mem_write(head, struct.pack("<I", node))  # its first node
        uc.mem_write(node + 8, struct.pack("<I", _DRAWABLE))
        uc.mem_write(_DRAWABLE + DRAWABLE_OBJECT, struct.pack("<I", _RIDER))
        regs = {reg: 0x1000 * (reg + 1) for reg in _REGS}
        regs[EDI], regs[ESI] = _TARGET, _SELECTION
        out = _run(uc, _labels(patched)[f"{ENTER_HINT_CONTAIN_LOAD:08x}"], dict(regs))
        assert names[out[EBX]] == "slaughter"
        assert all(out[reg] == value for reg, value in regs.items() if reg != EBX)

    def test_the_group_filter_asks_the_picked_contain_its_own_question(
        self, patched: bytearray
    ) -> None:
        """Entered with the stock `(member, 0, 1)` pushed; the answer is the picked contain's to
        that question, and its `ret 0xc` takes the three arguments."""
        uc, calls, _names = _machine(patched, _lair(False, True))
        frame = _STACK + 0xC00
        uc.mem_write(frame + 8, struct.pack("<I", _COMMAND))
        uc.mem_write(_COMMAND + AI_GROUP_ENTER_FILTER_TARGET, struct.pack("<I", _TARGET))
        regs = {EBX: _RIDER, EBP: frame, ESI: 0x05050505, EDI: 0x0D0D0D0D}
        out = _run(
            uc, _labels(patched)[f"{AI_GROUP_ENTER_FILTER_MEMBER_TEST:08x}"], regs, (_RIDER, 0, 1)
        )
        assert out[-1] == 0
        assert out[EAX] & 0xFF == 1
        assert calls[-1] == ("valid", "slaughter", (_RIDER, 0, 1))
        assert all(out[reg] == value for reg, value in regs.items())


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_window_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, expected in stock_windows().items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#x}"
        assert set(ANCHORS) <= set(stock_windows())

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        MultiContainPatch().apply(data)
        assert MultiContainPatch().verify(data) == []
        assert isinstance(MultiContainPatch.detect(data), MultiContainPatch)
        assert _read(data, CAN_ENTER_OBJECT_CONTAIN_LOAD, 1) == b"\xe8"
