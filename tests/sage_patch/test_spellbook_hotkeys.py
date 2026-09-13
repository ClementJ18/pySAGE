"""Ctrl + a spellbook button's own `&` letter, tested by running the cave rather than reading it.

The two routines are executed against a modelled world, because the thing most likely to be wrong
in a hand-assembled cave is not which helper it calls but where its frame is: this one keeps three
slots live across five engine calls, and every one of them cleans its own arguments.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence

import pytest

from sage_patch import addresses as ad
from sage_patch.patches import SpellbookHotkeysPatch as Exported
from sage_patch.patches import spellbook_commandset_refresh as refresh
from sage_patch.patches.experimental import spellbook_hotkeys as hk
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import spellbook_hotkeys_and_refresh_image, spellbook_hotkeys_image
from .test_commandset_button_upgrade import Cpu, Machine, Unsupported

_CAVE = 0x03000000
_STACK = 0x01000000
_FRAME = _STACK + 0x200
_PLAYER = 0x00110000
_OBJECT = 0x00120000
_SET = 0x00130000
_BUTTON = 0x00140000


class _Cpu(Cpu):
    """The shared decoder plus the five instruction forms this cave uses and that one does not.

    SIB addressing is the reason for most of it: the frame lives on `esp` rather than on a frame
    pointer of its own, so every slot reference goes through a `[esp+disp]` operand.
    """

    stubs: dict[int, object]

    def modrm(self) -> tuple[int, tuple[str, int]]:
        byte = self.machine_bytes(self.eip, 1)[0]
        mod, reg, rm = byte >> 6, (byte >> 3) & 7, byte & 7
        if mod == 3 or rm != 4:
            return super().modrm()
        self.eip += 1
        sib = self.imm8()
        base, index = sib & 7, (sib >> 3) & 7
        if index != 4:
            raise Unsupported("a scaled index this cave never emits")
        address = self.machine.regs[("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")[base]]
        if mod == 1:
            address += self.simm8()
        elif mod == 2:
            address += self.simm32()
        return reg, ("mem", address & 0xFFFFFFFF)

    def condition(self, code: int) -> bool:
        return self.machine.cf if code == 0x2 else super().condition(code)

    def step(self) -> None:
        op = self.machine_bytes(self.eip, 1)[0]
        if op == 0x04:  # add al, imm8
            self.eip += 1
            self.machine.set8(
                0, self.machine._add_flags(self.machine.regs["eax"] & 0xFF, self.imm8(), 8)
            )
            return
        if op in (0x38, 0x3A):  # cmp r/m8, r8 and cmp r8, r/m8
            self.eip += 1
            reg, operand = self.modrm()
            left, right = self.machine.get8(reg), self.load(operand, 8)
            self.machine._sub_flags(*((right, left) if op == 0x38 else (left, right)), 8)
            return
        if 0x70 <= op <= 0x7F:  # jcc rel8
            self.eip += 1
            displacement = self.simm8()
            if self.condition(op & 0xF):
                self.eip = (self.eip + displacement) & 0xFFFFFFFF
            return
        if (
            op == 0xF7 and (self.machine_bytes(self.eip + 1, 1)[0] >> 3) & 7 == 0
        ):  # test r/m32, imm32
            self.eip += 1
            _, operand = self.modrm()
            self.machine._logic_flags(self.load(operand) & self.imm32())
            return
        if op == 0x0F and self.machine_bytes(self.eip + 1, 1)[0] == 0x95:  # setne r/m8
            self.eip += 2
            _, operand = self.modrm()
            self.store(operand, 0 if self.machine.zf else 1, 8)
            return
        super().step()

    def engine_call(self, target: int) -> None:
        handler = self.stubs.get(target)
        if handler is None:
            raise Unsupported(f"call to unmodelled 0x{target:08x}")
        eax, popped = handler(self.machine)  # type: ignore[operator]
        self.machine.regs["eax"] = eax & 0xFFFFFFFF
        self.machine.regs["esp"] = (self.machine.regs["esp"] + popped) & 0xFFFFFFFF


class _World:
    """A local player whose spellbook set holds `labels`, one entry per slot.

    A `None` entry is an empty slot; a label with no `&` is a button that was never given a
    shortcut, which is the whole of the opt-in this patch relies on.
    """

    def __init__(
        self,
        machine: Machine,
        labels: Sequence[str | None],
        *,
        player: int = _PLAYER,
        availability: int = 1,
        refuse: frozenset[int] = frozenset(),
    ) -> None:
        self.machine = machine
        self.player = player
        self.labels = list(labels)
        #: Where `esp` stood when the routine was entered, so an exit can be checked as balanced.
        self.entry_esp = machine.regs["esp"]
        self.availability = availability
        #: Slots the evaluator answers 0 for, whatever `availability` says.
        self.refuse = refuse
        self.asked: list[int] = []
        self.fired: list[tuple[int, int, int]] = []
        self.constructed = 0
        self.destroyed = 0
        self.slots_read: list[int] = []
        self.buttons = [
            _BUTTON + 0x100 * i if text is not None else 0 for i, text in enumerate(labels)
        ]

    def button_label(self, button: int) -> str:
        return self.labels[self.buttons.index(button)] or ""

    def stubs(self) -> dict[int, object]:
        m = self.machine

        def local_player(_: Machine) -> tuple[int, int]:
            return self.player, 0

        def spellbook_object(_: Machine) -> tuple[int, int]:
            return (_OBJECT if self.player else 0), 0

        def command_set_string(_: Machine) -> tuple[int, int]:
            slot = m.alloc(4)
            m.write_field(slot, "TheSpellBookSet")
            return slot, 0

        def find_command_set(_: Machine) -> tuple[int, int]:
            return _SET, 4

        def get_command_button(_: Machine) -> tuple[int, int]:
            slot = m.arg(0)
            self.slots_read.append(slot)
            return (self.buttons[slot] if slot < len(self.buttons) else 0), 4

        def get_text_label(_: Machine) -> tuple[int, int]:
            slot = m.alloc(4)
            m.write_field(slot, self.button_label(m.regs["ecx"]))
            return slot, 0

        def hotkey_from_label(_: Machine) -> tuple[int, int]:
            out, label = m.arg(0), m.arg(1)
            # No `&` leaves `rest` empty, which is what the engine's own scan answers.
            rest = m.read_field(label).partition("&")[2]
            m.write_field(out, rest[:1])
            self.constructed += 1
            return out, 8

        def ascii_dtor(_: Machine) -> tuple[int, int]:
            if m.read32(m.regs["ecx"]):
                self.destroyed += 1
            m.write32(m.regs["ecx"], 0)
            return m.regs["ecx"], 0

        def get_availability(_: Machine) -> tuple[int, int]:
            button = m.arg(0)
            self.asked.append(button)
            m.write32(m.arg(3), 0)  # the Real out; the cave never reads it
            refused = self.buttons.index(button) in self.refuse
            return (0 if refused else self.availability), 0x14

        def do_command(_: Machine) -> tuple[int, int]:
            self.fired.append((m.arg(0), m.arg(1) & 0xFF, m.arg(2) & 0xFF))
            return 0, 0xC

        return {
            ad.PLAYER_LIST_GET_LOCAL_PLAYER: local_player,
            ad.PLAYER_GET_SPELLBOOK_OBJECT: spellbook_object,
            ad.OBJECT_GET_COMMAND_SET_STRING: command_set_string,
            ad.COMMAND_SET_STORE_FIND_COMMAND_SET: find_command_set,
            ad.COMMAND_SET_GET_COMMAND_BUTTON: get_command_button,
            ad.COMMAND_BUTTON_GET_TEXT_LABEL: get_text_label,
            ad.HOT_KEY_MANAGER_HOTKEY_FROM_LABEL: hotkey_from_label,
            ad.ASCII_STRING_DTOR: ascii_dtor,
            ad.CONTROL_BAR_GET_COMMAND_AVAILABILITY: get_availability,
            ad.CONTROL_BAR_DO_COMMAND: do_command,
        }


def _machine() -> Machine:
    m = Machine()
    m.regs["ebp"] = _FRAME
    m.regs["esp"] = _FRAME - 0x40
    m.write32(ad.THE_PLAYER_LIST, 0x00160000)
    m.write32(ad.THE_COMMAND_SET_STORE, 0x00170000)
    m.write32(ad.THE_HOT_KEY_MANAGER, 0x00180000)
    m.write32(ad.THE_APT_PLAYER, 0x00190000)
    m.write32(0x00190000 + ad.APT_PLAYER_MODE, 1)  # not mode 2, so doCommand's second Bool is 1
    return m


def _load(m: Machine) -> bytes:
    """The cave, in the modelled address space, so the decoder fetches the real bytes."""
    code = hk.build_cave(_CAVE)
    m.write(_CAVE, code)
    return code


def _run(cpu: _Cpu) -> int:
    """Step until control leaves the cave, and answer where it went."""
    for _ in range(200_000):
        if not cpu.code_va <= cpu.eip < cpu.code_va + len(cpu.code):
            return cpu.eip
        cpu.step()
    raise AssertionError("the cave did not leave")


def _null_answer(real: object) -> object:
    """The same stub, answering null - so the caller's `ret n` is still the real one."""
    return lambda m: (0, real(m)[1])  # type: ignore[operator]


def _gate(modifiers: int, flag: int) -> tuple[int, int, Machine]:
    m = _machine()
    m.regs["esi"] = modifiers
    m.regs["ebx"] = 0
    m.write8(_FRAME + ad.HOT_KEY_TRANSLATOR_FLAG_EBP, flag)
    cpu = _Cpu(machine=m, code=_load(m), code_va=_CAVE)
    cpu.stubs = {}
    cpu.eip = hk.cave_entries(_CAVE)[0]
    exit_va = _run(cpu)
    return exit_va, m.read8(_FRAME + ad.HOT_KEY_TRANSLATOR_FLAG_EBP), m


def _dispatch(
    labels: Sequence[str | None],
    pressed: str,
    flag: int = hk.MARK,
    absent: int | None = None,
    availability: int = 1,
    refuse: frozenset[int] = frozenset(),
) -> tuple[int, _World, Machine]:
    """Run the dispatch routine. `absent` makes one link of the chain answer null instead."""
    m = _machine()
    world = _World(m, labels, availability=availability, refuse=refuse)
    key_slot = m.alloc(4)
    m.write_field(key_slot, pressed)
    m.write32(_FRAME + ad.HOT_KEY_EXECUTE_KEY_EBP, key_slot)
    m.write32(_FRAME + ad.HOT_KEY_EXECUTE_FLAG_EBP, flag)
    stubs = world.stubs()
    if absent is not None:
        stubs[absent] = _null_answer(stubs[absent])
    cpu = _Cpu(machine=m, code=_load(m), code_va=_CAVE)
    cpu.stubs = stubs
    cpu.eip = hk.cave_entries(_CAVE)[1]
    exit_va = _run(cpu)
    return exit_va, world, m


def test_surface() -> None:
    cls = hk.SpellbookHotkeysPatch
    assert Exported is cls
    assert PATCHES[cls.name] is cls
    assert cls.experimental and ".experimental." in cls.__module__
    assert cls().ini_surface().is_stock  # it adds no INI keyword: the `&` is the whole authoring
    assert len(hk.SECTION_NAME) <= 8
    assert cls.detect(spellbook_hotkeys_image()) is None


def test_the_cave_is_pinned_so_a_later_edit_has_to_be_deliberate() -> None:
    code = hk.build_cave(_CAVE)
    assert len(code) == 421
    assert hashlib.sha256(code).hexdigest() == (
        "ffccacf70a6676806db891f978493fa934e98b6eef1c0c56cf1f4c4a002f238d"
    )


def test_round_trip_and_only_the_two_declared_windows_change() -> None:
    original = spellbook_hotkeys_image()
    data = bytearray(original)
    patch = hk.SpellbookHotkeysPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    assert patch.detect(data) is not None

    touched: set[int] = set()
    for va, stock in hk.SITES.items():
        off = va_to_offset(data, va)
        assert off is not None
        touched |= set(range(off, off + len(stock)))
    changed = {i for i in range(0x400, len(original)) if original[i] != data[i]}
    assert changed <= touched


def test_each_detour_is_a_jump_to_its_own_entry_point_padded_not_overrun() -> None:
    data = bytearray(spellbook_hotkeys_image())
    hk.SpellbookHotkeysPatch().apply(data)
    located = find_section(data, hk.SECTION_NAME)
    assert located is not None
    entries = hk.cave_entries(located[0])
    for (va, stock), entry in zip(hk.SITES.items(), entries, strict=True):
        off = va_to_offset(data, va)
        assert off is not None
        width = len(stock)
        assert data[off] == 0xE9
        assert struct.unpack("<i", data[off + 1 : off + 5])[0] + va + 5 == entry
        assert bytes(data[off + 5 : off + width]) == b"\x90" * (width - 5)


def test_applying_twice_fails_rather_than_double_patching() -> None:
    data = bytearray(spellbook_hotkeys_image())
    patch = hk.SpellbookHotkeysPatch()
    patch.apply(data)
    before = bytes(data)
    with pytest.raises(ValueError, match="expected"):
        patch.apply(data)
    assert data == before


@pytest.mark.parametrize("va", [*hk.SITES, *hk.ANCHORS])
def test_a_disturbed_site_or_anchor_is_refused_before_anything_is_written(va: int) -> None:
    data = spellbook_hotkeys_image()
    off = va_to_offset(data, va)
    assert off is not None
    data[off] ^= 0xFF
    before = bytes(data)
    with pytest.raises(ValueError, match=f"0x{va:08x}"):
        hk.SpellbookHotkeysPatch().apply(data)
    assert data == before


def test_an_unmodified_key_takes_the_stock_answer() -> None:
    exit_va, flag, _ = _gate(0x00, 0)
    assert exit_va == ad.HOT_KEY_TRANSLATOR_PROCEED
    assert flag == 0


def test_shift_is_still_the_stock_answer_and_keeps_its_own_flag() -> None:
    exit_va, flag, _ = _gate(0x10, 1)
    assert exit_va == ad.HOT_KEY_TRANSLATOR_PROCEED
    assert flag == 1


def test_ctrl_alone_now_proceeds_carrying_the_mark() -> None:
    exit_va, flag, _ = _gate(hk.CTRL_MASK, 0)
    assert exit_va == ad.HOT_KEY_TRANSLATOR_PROCEED
    assert flag == hk.MARK


@pytest.mark.parametrize("modifiers", [0x40, 0x44, 0x54])
def test_alt_in_any_combination_stays_discarded(modifiers: int) -> None:
    exit_va, flag, _ = _gate(modifiers, 0)
    assert exit_va == ad.HOT_KEY_TRANSLATOR_REJECT
    assert flag == 0


def test_ctrl_is_matched_by_mask_so_a_stray_state_bit_does_not_lose_the_press() -> None:
    """The engine matches `CommandMap` modifiers by equality, so a binding on Ctrl stops matching
    the moment anything else joins the mask. The gate tests the bits it cares about instead,
    which is what keeps Ctrl+Shift and the unidentified `0x400` state bit working."""
    for modifiers in (hk.CTRL_MASK, hk.CTRL_MASK | 0x10):
        exit_va, flag, _ = _gate(modifiers, 0)
        assert exit_va == ad.HOT_KEY_TRANSLATOR_PROCEED
        assert flag == hk.MARK


def test_an_unmarked_press_re_emits_the_displaced_saves_and_resumes() -> None:
    exit_va, world, m = _dispatch(["&Anduril"], "a", flag=1)
    assert exit_va == ad.HOT_KEY_EXECUTE_RESUME
    assert world.fired == []
    # push esi, push edi, push [ebp+8]: the three instructions the detour displaced.
    assert m.regs["esp"] == world.entry_esp - 0xC
    assert m.read32(m.regs["esp"]) == m.read32(_FRAME + ad.HOT_KEY_EXECUTE_KEY_EBP)


def test_a_marked_press_fires_the_button_whose_label_carries_that_letter() -> None:
    exit_va, world, m = _dispatch(["&Blight", "&Anduril", "&Cloud"], "a")
    assert exit_va == ad.HOT_KEY_EXECUTE_HIT
    assert m.regs["eax"] & 0xFF == 1  # the key was consumed
    assert world.fired == [(world.buttons[1], 1, 0)]
    assert m.regs["esp"] == world.entry_esp


def test_the_match_is_case_insensitive_in_both_directions() -> None:
    assert _dispatch(["&Anduril"], "A")[1].fired
    assert _dispatch(["&anduril"], "A")[1].fired
    assert _dispatch(["&ANDURIL"], "a")[1].fired


def test_a_label_with_no_ampersand_is_never_a_shortcut() -> None:
    exit_va, world, m = _dispatch(["Anduril", "Blight"], "a")
    assert exit_va == ad.HOT_KEY_EXECUTE_MISS
    assert world.fired == []
    assert m.regs["esp"] == world.entry_esp


def test_an_empty_slot_is_stepped_over_rather_than_dereferenced() -> None:
    exit_va, world, _ = _dispatch([None, None, "&Anduril"], "a")
    assert exit_va == ad.HOT_KEY_EXECUTE_HIT
    assert world.fired == [(world.buttons[2], 1, 0)]


def test_the_walk_stops_at_the_bar_s_own_slot_limit() -> None:
    exit_va, world, _ = _dispatch([None] * 40, "a")
    assert exit_va == ad.HOT_KEY_EXECUTE_MISS
    assert world.slots_read == list(range(ad.SPELLBOOK_UI_SLOT_LIMIT))


def test_every_string_the_scan_constructs_is_destroyed_on_both_exits() -> None:
    for labels, pressed in ((["&Blight", "&Anduril"], "a"), (["&Blight", "&Cloud"], "a")):
        _, world, m = _dispatch(labels, pressed)
        assert world.constructed == len(labels)
        assert world.destroyed == world.constructed
        assert m.read32(world.entry_esp - 0x18) == 0  # the out slot, left empty


@pytest.mark.parametrize(
    "missing",
    [
        ad.PLAYER_LIST_GET_LOCAL_PLAYER,
        ad.PLAYER_GET_SPELLBOOK_OBJECT,
        ad.COMMAND_SET_STORE_FIND_COMMAND_SET,
    ],
)
def test_a_missing_link_in_the_chain_misses_instead_of_dereferencing_null(missing: int) -> None:
    exit_va, world, m = _dispatch(["&Anduril"], "a", absent=missing)
    assert exit_va == ad.HOT_KEY_EXECUTE_MISS
    assert world.fired == []
    assert m.regs["esp"] == world.entry_esp


def test_an_empty_pressed_key_misses_without_walking_anything() -> None:
    exit_va, world, _ = _dispatch(["&Anduril"], "")
    assert exit_va == ad.HOT_KEY_EXECUTE_MISS
    assert world.slots_read == []


def test_it_composes_with_the_refresh_guard_in_either_order() -> None:
    """The two patches closest to each other: both reach into the same bar.

    They share four helper addresses and resolve the same CommandSet chain, but one rewrites bytes
    in the bar's cache function and the other in the hotkey layer, so neither reads what the other
    wrote. Applying both each way is what checks that rather than asserting it.
    """
    both = (hk.SpellbookHotkeysPatch(), refresh.SpellbookCommandSetRefreshPatch())
    produced = []
    for order in (both, both[::-1]):
        data = spellbook_hotkeys_and_refresh_image()
        for patch in order:
            patch.apply(data)
        for patch in order:
            assert patch.verify(data) == [], patch.name
        produced.append(data)
    # Same edits either way; only which cave landed first, and so the section table, can differ.
    for va, stock in {**hk.SITES, refresh.SPELLBOOK_UI_CACHE_HOOK: refresh.HOOK_BYTES}.items():
        assert len(stock) >= 5
        for data in produced:
            off = va_to_offset(data, va)
            assert off is not None
            assert data[off] == 0xE9, hex(va)


@pytest.mark.parametrize("availability", [1, 2])
def test_the_two_answers_that_mean_a_click_would_work_fire(availability: int) -> None:
    exit_va, world, _ = _dispatch(["&Anduril"], "a", availability=availability)
    assert exit_va == ad.HOT_KEY_EXECUTE_HIT
    assert world.asked == [world.buttons[0]]
    assert world.fired == [(world.buttons[0], 1, 0)]


@pytest.mark.parametrize("availability", [0, 3, 4, 6, 7])
def test_a_power_the_bar_would_not_let_you_click_is_not_cast(availability: int) -> None:
    """The reported defect: a spellbook button is greyed inside the APT movie, so a disabled one
    never reaches the engine and nothing on the `SPELL_BOOK` path checks. Without this the
    shortcut armed a targeting cursor for a power still on cooldown."""
    exit_va, world, m = _dispatch(["&Anduril"], "a", availability=availability)
    assert exit_va == ad.HOT_KEY_EXECUTE_MISS
    assert world.asked == [world.buttons[0]]
    assert world.fired == []
    assert m.regs["esp"] == world.entry_esp


def test_a_refused_button_does_not_stop_a_later_one_with_the_same_letter() -> None:
    """Refusing rejoins the walk rather than ending it, which is the same rule duplicate letters
    already follow: the lowest slot that can actually do something wins."""
    exit_va, world, _ = _dispatch(["&Anduril", "&Anduril"], "a", refuse=frozenset({0}))
    assert exit_va == ad.HOT_KEY_EXECUTE_HIT
    assert world.asked == world.buttons[:2]
    assert world.fired == [(world.buttons[1], 1, 0)]


def test_availability_is_asked_only_about_the_button_whose_letter_matched() -> None:
    _, world, _ = _dispatch(["&Blight", "&Anduril", "&Cloud"], "a")
    assert world.asked == [world.buttons[1]]
