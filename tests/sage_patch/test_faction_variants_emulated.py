"""Faction variants, executed.

`test_faction_variants.py` checks where the cave is wired in. This runs it: every routine executes
under unicorn against a stand-in engine - `ThePlayerTemplateStore`, the setup screen, its slots
and its combo boxes are Python, reached through stubs at the engine addresses the cave calls - and
the hooks are caught where the stock code would resume. What it pins is the behaviour the bytes
cannot show: which templates each box lists and selects, that a pick in the Variant box reaches the
screen's strategy object exactly as a pick in the faction box does, and that Random and the faction
list agree on what a variant is.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import pytest

from sage_patch.addresses import (
    COMBO_BOX_ADD_ENTRY,
    COMBO_BOX_DROPDOWN_BUTTON,
    COMBO_BOX_ENTRY_COUNT,
    COMBO_BOX_GADGET_DATA,
    COMBO_BOX_GET_ITEM_DATA,
    COMBO_BOX_GET_SELECTED,
    COMBO_BOX_OPEN_GO,
    COMBO_BOX_OPEN_SKIP,
    COMBO_BOX_RESET,
    COMBO_BOX_SET_DROPDOWN_LINES,
    COMBO_BOX_SET_ITEM_DATA,
    COMBO_BOX_SET_SELECTED,
    COMBO_BOX_TOGGLE_BOX_EBP,
    GAME_INFO_GET_SLOT,
    GAME_LOGIC_RANDOM_VALUE,
    GAME_LOGIC_SOURCE_FILE,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_SET_PLAYER_TEMPLATE,
    GAME_START_RANDOM_ASSIGN_RESUME,
    GAME_START_RANDOM_CANDIDATES_EBP,
    GAME_START_RANDOM_DRAW_RESUME,
    GAME_START_RANDOM_POOL_INDEX_EBP,
    GAME_START_RANDOM_POOL_RESUME,
    GAME_START_RANDOM_POOL_SKIP,
    GAME_START_RANDOM_SLOT_EBP,
    GAME_START_SLOT_TEMPLATE_RESUME,
    GAME_TEXT_FETCH_SLOT,
    GUI_RANDOM_LABEL,
    INI_NEXT_TOKEN_OR_NULL,
    MP_SETUP_DIRTY,
    MP_SETUP_DROPDOWN_LINES,
    MP_SETUP_FACTION_COMBO,
    MP_SETUP_FACTION_LIST_INDEX_EBP,
    MP_SETUP_FACTION_LIST_PLAYABLE_RESUME,
    MP_SETUP_FACTION_LIST_SKIP,
    MP_SETUP_FACTION_REQUEST_PENDING,
    MP_SETUP_FACTION_WINDOWS,
    MP_SETUP_GADGET_FILED,
    MP_SETUP_GADGET_HERO_TEST_RESUME,
    MP_SETUP_GADGET_SLOT_EBP,
    MP_SETUP_GADGET_UNKNOWN,
    MP_SETUP_GAME_INFO,
    MP_SETUP_GET_GAME_INFO,
    MP_SETUP_REDRAW_SLOT,
    MP_SETUP_SELECTION_DONE,
    MP_SETUP_STRATEGY,
    MP_SETUP_STRATEGY_REQUEST_TEMPLATE_SLOT,
    MP_SETUP_SYNC_FACTION,
    MP_SETUP_SYNC_FACTION_TEMPLATE_RESUME,
    MP_SETUP_WOTR_IS_HISTORICAL,
    MULTIPLAYER_COLOR_VALUE,
    MULTIPLAYER_SETTINGS_GET_COLOR,
    NAME_KEY_FROM_CSTR,
    PLAYER_TEMPLATE_EVIL,
    PLAYER_TEMPLATE_FIND_BY_INDEX,
    PLAYER_TEMPLATE_GET_DISPLAY_NAME,
    PLAYER_TEMPLATE_IS_OBSERVER,
    PLAYER_TEMPLATE_NAME_KEY,
    PLAYER_TEMPLATE_PARSED_JOIN_RESUME,
    PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME,
    PLAYER_TEMPLATE_PLAYABLE_SIDE,
    PLAYER_TEMPLATE_SIZE,
    PLAYER_TEMPLATE_STORE_BEGIN,
    PLAYER_TEMPLATE_STORE_END,
    STRICMP,
    THE_GAME_TEXT,
    THE_MULTIPLAYER_SETTINGS,
    THE_NAME_KEY_GENERATOR,
    THE_PLAYER_TEMPLATE_STORE,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
    WINDOW_ENABLE,
    WINDOW_HIDE,
    WINDOW_STATUS,
    WINDOW_STATUS_ENABLED,
    WINDOW_STATUS_HIDDEN,
)
from sage_patch.patches.faction_variants import (
    _MEMSET,
    EVIL_LABEL,
    GADGET_KIND,
    GOOD_LABEL,
    RANDOM_EVIL,
    RANDOM_GOOD,
    RANDOM_OF,
    RANDOM_STANDARD,
    RANDOM_VARIANT,
    RANDOM_VARIANTS,
    ROWS,
    STANDARD_LABEL,
    build_section,
    layout,
)

unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

SECTION = 0x00F00000
HEAP = 0x10000000
STACK = 0x20000000
PAGE = 0x1000
RETURN = 0x30000000

#: Where each stub returns and how much stack it takes back - the conventions the cave relies on.
_STUBS = {
    INI_NEXT_TOKEN_OR_NULL: 4,
    NAME_KEY_FROM_CSTR: 4,
    PLAYER_TEMPLATE_FIND_BY_INDEX: 4,
    PLAYER_TEMPLATE_GET_DISPLAY_NAME: 4,
    MP_SETUP_GET_GAME_INFO: 0,
    GAME_INFO_GET_SLOT: 4,
    COMBO_BOX_RESET: 0,
    COMBO_BOX_ADD_ENTRY: 0,
    COMBO_BOX_SET_ITEM_DATA: 0,
    COMBO_BOX_GET_ITEM_DATA: 0,
    COMBO_BOX_SET_SELECTED: 0,
    COMBO_BOX_GET_SELECTED: 0,
    COMBO_BOX_SET_DROPDOWN_LINES: 0,
    WINDOW_ENABLE: 4,
    WINDOW_HIDE: 4,
    MULTIPLAYER_SETTINGS_GET_COLOR: 4,
    MP_SETUP_DROPDOWN_LINES: 0,
    MP_SETUP_REDRAW_SLOT: 0xC,
    MP_SETUP_WOTR_IS_HISTORICAL: 0,
    GAME_LOGIC_RANDOM_VALUE: 0,
    GAME_SLOT_SET_PLAYER_TEMPLATE: 4,
    MP_SETUP_FACTION_COMBO: 4,
    MP_SETUP_SYNC_FACTION: 4,
    STRICMP: 0,
    _MEMSET: 0,
    UNICODE_STRING_CONCAT: 0,
    UNICODE_STRING_DTOR: 0,
}

#: Where the stock code would take over again. Reaching one ends a run.
_EXITS = {
    RETURN,
    COMBO_BOX_OPEN_GO,
    COMBO_BOX_OPEN_SKIP,
    GAME_START_SLOT_TEMPLATE_RESUME,
    GAME_START_RANDOM_ASSIGN_RESUME,
    GAME_START_RANDOM_DRAW_RESUME,
    PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME,
    PLAYER_TEMPLATE_PARSED_JOIN_RESUME,
    MP_SETUP_FACTION_LIST_PLAYABLE_RESUME,
    MP_SETUP_FACTION_LIST_SKIP,
    GAME_START_RANDOM_POOL_RESUME,
    GAME_START_RANDOM_POOL_SKIP,
    MP_SETUP_SYNC_FACTION_TEMPLATE_RESUME,
    MP_SETUP_SELECTION_DONE,
    MP_SETUP_GADGET_FILED,
    MP_SETUP_GADGET_UNKNOWN,
    MP_SETUP_GADGET_HERO_TEST_RESUME,
}


@dataclass
class Box:
    """A combo box as the window manager would hold it."""

    rows: list[tuple[str, int]] = field(default_factory=list)
    selected: int = -1


class Engine:
    """Just enough of the engine for every routine in the cave to run."""

    def __init__(
        self, templates: list[tuple[str, str, bool] | tuple[str, str, bool, bool]]
    ) -> None:
        """`templates`: `(block name, display name, playable[, evil])`, in store order."""
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        section = build_section(SECTION)
        self.uc.mem_map(SECTION, _pages(len(section)))
        self.uc.mem_write(SECTION, section)
        self.at = layout(SECTION)

        self.uc.mem_map(HEAP, 0x100000)
        self.uc.mem_map(STACK, 0x10000)
        self._heap = HEAP

        self._text_vtable = self._alloc(0x40)
        self._strategy_vtable = self._alloc(0x40)
        fetch = self._alloc(4)
        request = self._alloc(4)
        self._stubs = dict(_STUBS)
        self._stubs[fetch] = 0xC
        self._stubs[request] = 8
        self._fetch, self._request = fetch, request
        self._write(self._text_vtable + GAME_TEXT_FETCH_SLOT, fetch)
        self._write(self._strategy_vtable + MP_SETUP_STRATEGY_REQUEST_TEMPLATE_SLOT, request)

        engine_pages = {va & ~(PAGE - 1) for va in [*self._stubs, *_EXITS]}
        engine_pages |= {
            va & ~(PAGE - 1)
            for va in (
                THE_NAME_KEY_GENERATOR,
                THE_PLAYER_TEMPLATE_STORE,
                THE_MULTIPLAYER_SETTINGS,
                THE_GAME_TEXT,
                GUI_RANDOM_LABEL,
                GAME_LOGIC_SOURCE_FILE,
            )
        }
        for page in engine_pages:
            if not HEAP <= page < HEAP + 0x100000:
                self.uc.mem_map(page, PAGE)
        for va, pop in self._stubs.items():
            self.uc.mem_write(va, b"\xc2" + struct.pack("<H", pop) if pop else b"\xc3")
        for va in _EXITS:
            self.uc.mem_write(va, b"\xf4")

        self.keys: dict[str, int] = {}
        self.strings: dict[int, str] = {}
        #: What the string table answers per label; unlisted labels read back as `<label>`.
        self.labels: dict[str, str] = {}
        self.boxes: dict[int, Box] = {}
        self.buttons: dict[int, int] = {}
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.resets: list[int] = []
        #: What the strategy object does with a request: `apply` it (skirmish, LAN host),
        #: `defer` it (a LAN client: accepted, answered later), or `refuse` it.
        self.requests = "apply"
        self._token = 0

        text = self._alloc(4)
        self._write(text, self._text_vtable)
        self._write(THE_GAME_TEXT, text)
        self.uc.mem_write(GUI_RANDOM_LABEL, b"GUI:Random\x00")
        self.uc.mem_write(GAME_LOGIC_SOURCE_FILE, b"GameLogic.cpp\x00")
        #: What `GameLogicRandomValue` answers: an offset into its range, taken modulo its size.
        self.draw = 0
        self.draws: list[tuple[int, int]] = []
        colors = self._alloc(0x100)
        self._write(colors + MULTIPLAYER_COLOR_VALUE, 0xFFFFFFFF)
        self._colors = colors
        self._write(THE_MULTIPLAYER_SETTINGS, self._alloc(0x100))

        # The store: a contiguous vector, as `ThePlayerTemplateStore` holds it.
        self.names = [entry[0] for entry in templates]
        self.display = {i: entry[1] for i, entry in enumerate(templates)}
        vector = self._alloc(PLAYER_TEMPLATE_SIZE * len(templates))
        for index, (name, _display, playable, *evil) in enumerate(templates):
            template = vector + index * PLAYER_TEMPLATE_SIZE
            self._write(template + PLAYER_TEMPLATE_NAME_KEY, self.key(name))
            self.uc.mem_write(template + PLAYER_TEMPLATE_PLAYABLE_SIDE, bytes([playable]))
            self.uc.mem_write(template + PLAYER_TEMPLATE_IS_OBSERVER, b"\x00")
            self.uc.mem_write(template + PLAYER_TEMPLATE_EVIL, bytes([bool(evil and evil[0])]))
        self.vector = vector
        store = self._alloc(0x40)
        self._write(store + PLAYER_TEMPLATE_STORE_BEGIN, vector)
        self._write(
            store + PLAYER_TEMPLATE_STORE_END, vector + PLAYER_TEMPLATE_SIZE * len(templates)
        )
        self._write(THE_PLAYER_TEMPLATE_STORE, store)

        # The setup screen, one GameInfo with eight slots, a faction box per slot.
        self.screen = self._alloc(0x400)
        self.game_info = self._alloc(0x40)
        self._write(self.screen + MP_SETUP_GAME_INFO, self._alloc(0x10))
        strategy = self._alloc(0x10)
        self._write(strategy, self._strategy_vtable)
        self._write(self.screen + MP_SETUP_STRATEGY, strategy)
        self.slots = [self._alloc(0x40) for _ in range(8)]
        self.faction_boxes = []
        for slot in range(8):
            window = self.window(enabled=True)
            self._write(self.screen + MP_SETUP_FACTION_WINDOWS + 4 * slot, window)
            self.faction_boxes.append(window)
            self.set_template(slot, -1)

        self.exit: int | None = None
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)

    # memory

    def _alloc(self, size: int) -> int:
        va = self._heap
        self._heap += (size + 15) & ~15
        return va

    def _read(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def _write(self, va: int, value: int) -> None:
        self.uc.mem_write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def _arg(self, n: int) -> int:
        return self._read(self.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * n)

    def _cstr(self, va: int) -> str:
        return bytes(self.uc.mem_read(va, 256)).split(b"\x00", 1)[0].decode()

    def cstr(self, text: str) -> int:
        va = self._alloc(len(text) + 1)
        self.uc.mem_write(va, text.encode() + b"\x00")
        return va

    def key(self, name: str) -> int:
        return self.keys.setdefault(name, 0x100 + len(self.keys))

    def window(self, *, enabled: bool = True, hidden: bool = False) -> int:
        """A combo box: its window, its gadget data at `+0x2C`, and the drop-down button the data
        names - the window whose enabled bit is whether the arrow is drawn."""
        window = self._alloc(0x40)
        status = (WINDOW_STATUS_ENABLED if enabled else 0) | (WINDOW_STATUS_HIDDEN if hidden else 0)
        self._write(window + WINDOW_STATUS, status)
        data = self._alloc(0x40)
        button = self._alloc(0x20)
        self._write(button + WINDOW_STATUS, WINDOW_STATUS_ENABLED if enabled else 0)
        self._write(data + COMBO_BOX_DROPDOWN_BUTTON, button)
        self._write(window + COMBO_BOX_GADGET_DATA, data)
        self.buttons[window] = button
        self.boxes[window] = Box()
        return window

    def arrow(self, window: int) -> bool:
        """Whether `window`'s drop-down arrow is drawn: its button is enabled."""
        return self.status(self.buttons[window])[1]

    def status(self, window: int) -> tuple[bool, bool]:
        """`(shown, enabled)`."""
        status = self._read(window + WINDOW_STATUS)
        return not status & WINDOW_STATUS_HIDDEN, bool(status & WINDOW_STATUS_ENABLED)

    def set_template(self, slot: int, index: int) -> None:
        self._write(self.slots[slot] + GAME_SLOT_PLAYER_TEMPLATE, index)

    def template(self, slot: int) -> int:
        return struct.unpack(
            "<i", self.uc.mem_read(self.slots[slot] + GAME_SLOT_PLAYER_TEMPLATE, 4)
        )[0]

    def index(self, name: str) -> int:
        return self.names.index(name)

    # the stand-in engine

    def _string(self, text: str) -> int:
        """A `UnicodeString` buffer as the engine lays one out - the characters at +8 - tracked
        until something owns and ends it."""
        handle = self._alloc(8 + 2 * (len(text) + 1))
        self.uc.mem_write(handle + 8, text.encode("utf-16-le") + b"\x00\x00")
        self.strings[handle] = text
        return handle

    def _wide(self, va: int) -> str:
        raw = bytes(self.uc.mem_read(va, 512))
        end = next(i for i in range(0, len(raw), 2) if raw[i : i + 2] == b"\x00\x00")
        return raw[:end].decode("utf-16-le")

    def _on_code(self, uc: Uc, address: int, _size: int, _user: object) -> None:
        if address in _EXITS:
            self.exit = address
            uc.emu_stop()
            return
        if address not in self._stubs:
            return
        eax = None
        if address == INI_NEXT_TOKEN_OR_NULL:
            eax = self._token
        elif address == NAME_KEY_FROM_CSTR:
            assert uc.reg_read(UC_X86_REG_ECX) == self._read(THE_NAME_KEY_GENERATOR)
            eax = self.key(self._cstr(self._arg(0)))
        elif address == PLAYER_TEMPLATE_FIND_BY_INDEX:
            index = self._arg(0)
            eax = self.vector + index * PLAYER_TEMPLATE_SIZE if index < len(self.names) else 0
        elif address == PLAYER_TEMPLATE_GET_DISPLAY_NAME:
            index = (uc.reg_read(UC_X86_REG_ECX) - self.vector) // PLAYER_TEMPLATE_SIZE
            out = self._arg(0)
            self._write(out, self._string(self.display[index]))
            eax = out
        elif address == self._fetch:
            out, label = self._arg(0), self._cstr(self._arg(1))
            self._write(out, self._string(self.labels.get(label, f"<{label}>")))
            eax = out
        elif address == MULTIPLAYER_SETTINGS_GET_COLOR:
            assert self._arg(0) == 0xFFFFFFFF
            eax = self._colors
        elif address == MP_SETUP_GET_GAME_INFO:
            eax = self.game_info
        elif address == GAME_INFO_GET_SLOT:
            eax = self.slots[self._arg(0)] if self._arg(0) < 8 else 0
        elif address == COMBO_BOX_RESET:
            self.resets.append(self._arg(0))
            box = self.boxes[self._arg(0)]
            box.rows.clear()
            box.selected = -1
        elif address == COMBO_BOX_ADD_ENTRY:
            box = self.boxes[self._arg(0)]
            text = self.strings.pop(self._arg(1))  # by value: the callee owns and ends it
            assert self._arg(2) == 0xFFFFFFFF, "rows are written in the fill's own colour"
            box.rows.append((text, -99))
            eax = len(box.rows) - 1
        elif address == COMBO_BOX_SET_ITEM_DATA:
            box, row, data = self.boxes[self._arg(0)], self._arg(1), self._arg(2)
            box.rows[row] = (box.rows[row][0], struct.unpack("<i", struct.pack("<I", data))[0])
        elif address == COMBO_BOX_GET_ITEM_DATA:
            box, row = self.boxes[self._arg(0)], self._arg(1)
            eax = box.rows[row][1]
        elif address == COMBO_BOX_SET_SELECTED:
            self.boxes[self._arg(0)].selected = self._arg(1)
        elif address == COMBO_BOX_GET_SELECTED:
            self._write(self._arg(1), self.boxes[self._arg(0)].selected)
        elif address == WINDOW_ENABLE:
            window, on = uc.reg_read(UC_X86_REG_ECX), self._arg(0) & 0xFF
            self._flag(window, WINDOW_STATUS_ENABLED, on)
            if window in self.buttons:
                # `winEnable` enables the children too, then the combo box gadget answers the
                # enable message by disabling its drop-down button unless it lists two or more.
                button = self.buttons[window]
                self._flag(button, WINDOW_STATUS_ENABLED, on)
                if on and len(self.boxes[window].rows) < 2:
                    self._flag(button, WINDOW_STATUS_ENABLED, 0)
        elif address == WINDOW_HIDE:
            self._flag(uc.reg_read(UC_X86_REG_ECX), WINDOW_STATUS_HIDDEN, self._arg(0) & 0xFF)
        elif address == MP_SETUP_DROPDOWN_LINES:
            eax = 4
        elif address == self._request:
            slot, index = self._arg(0), self._arg(1)
            self.calls.append(
                (
                    "request",
                    (self.slots.index(slot), struct.unpack("<i", struct.pack("<I", index))[0]),
                )
            )
            if self.requests == "apply":
                self._write(slot + GAME_SLOT_PLAYER_TEMPLATE, index)
            eax = int(self.requests != "refuse")
        elif address == MP_SETUP_REDRAW_SLOT:
            self.calls.append(
                ("redraw", (self.slots.index(self._arg(0)), self._arg(1), self._arg(2)))
            )
        elif address == UNICODE_STRING_CONCAT:
            dest, fmt = self._arg(0), self._read(self._arg(1))
            assert self._read(dest) == 0, "formatted into a fresh slot"
            text = self._wide(fmt + 8)
            assert text.count("%") == text.count("%s"), "only %s is ever formatted"
            self._write(dest, self._string(text.replace("%s", self._wide(self._arg(2)))))
        elif address == UNICODE_STRING_DTOR:
            this = uc.reg_read(UC_X86_REG_ECX)
            handle = self._read(this)
            if handle:
                self.strings.pop(handle)
            self._write(this, 0)
        elif address == GAME_LOGIC_RANDOM_VALUE:
            lo, hi = self._arg(0), self._arg(1)
            assert self._cstr(self._arg(2)) == "GameLogic.cpp"
            self.draws.append((lo, hi))
            eax = lo + self.draw % (hi - lo + 1)
        elif address == GAME_SLOT_SET_PLAYER_TEMPLATE:
            self.calls.append(
                ("set", (self.slots.index(uc.reg_read(UC_X86_REG_ECX)), self._arg(0)))
            )
            self._write(uc.reg_read(UC_X86_REG_ECX) + GAME_SLOT_PLAYER_TEMPLATE, self._arg(0))
        elif address == MP_SETUP_WOTR_IS_HISTORICAL:
            eax = 0
        elif address in (MP_SETUP_FACTION_COMBO, MP_SETUP_SYNC_FACTION):
            assert uc.reg_read(UC_X86_REG_ECX) == self.screen
            self.calls.append(("stock", (address, self._arg(0))))
        elif address == STRICMP:
            eax = int(self._cstr(self._arg(0)).lower() != self._cstr(self._arg(1)).lower())
        elif address == _MEMSET:
            self.calls.append(("memset", (self._arg(0), self._arg(1), self._arg(2))))
        if eax is not None:
            uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        else:
            uc.reg_write(UC_X86_REG_EAX, 0xDEADBEEF)  # nothing may rely on a void's eax

    def _flag(self, window: int, bit: int, on: int) -> None:
        status = self._read(window + WINDOW_STATUS)
        self._write(window + WINDOW_STATUS, status | bit if on else status & ~bit)

    # running

    def _frame(self, *, ebp_room: int = 0x400) -> int:
        esp = STACK + 0x8000
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_EBP, esp + ebp_room)
        return esp

    def _push(self, *values: int) -> None:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        for value in values:
            esp -= 4
            self._write(esp, value)
        self.uc.reg_write(UC_X86_REG_ESP, esp)

    def run(self, label: str) -> int:
        self.exit = None
        self.uc.emu_start(self.at[label], 0xFFFFFFFF, count=200_000)
        assert self.exit is not None, "ran off without reaching an exit"
        return self.exit

    def call(self, label: str, *args: int, ecx: int = 0, cdecl: bool = False) -> int:
        """Run `label` as a routine taking `args`; returns eax. Asserts it cleans them exactly
        as its convention says - all of them, or none for `cdecl`."""
        esp = self._frame()
        self._push(*reversed(args))
        self._push(RETURN)
        self.uc.reg_write(UC_X86_REG_ECX, ecx)
        assert self.run(label) == RETURN
        popped = self.uc.reg_read(UC_X86_REG_ESP) - esp
        want = -4 * len(args) if cdecl else 0
        assert popped == want, f"{label} left the stack {popped:+#x} from where it started"
        return self.uc.reg_read(UC_X86_REG_EAX)

    # the INI side

    def declare(self, name: str, variant_of: str | None, *, override: bool = False) -> None:
        """One `PlayerTemplate` block through the store's parse: the fields, then the key."""
        if variant_of is not None:
            self._token = self.cstr(variant_of)
            esp = self._frame()
            self._push(0, 0, 0, self._alloc(0x10))
            self._push(RETURN)
            assert self.run("parse") == RETURN
            assert self.uc.reg_read(UC_X86_REG_ESP) == esp - 16, "parse is cdecl"
        esp = self._frame()
        self.uc.reg_write(UC_X86_REG_EDI, self.key(name))
        self.uc.reg_write(UC_X86_REG_ECX, 0x1234)
        exit_ = self.run("join" if override else "new_key")
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp
        assert self.uc.reg_read(UC_X86_REG_ECX) == 0x1234, "the stock code reads ecx next"
        if override:
            assert exit_ == PLAYER_TEMPLATE_PARSED_JOIN_RESUME
            assert self.uc.reg_read(UC_X86_REG_EAX) == self._read(THE_PLAYER_TEMPLATE_STORE)
        else:
            assert exit_ == PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME
            ebp = self.uc.reg_read(UC_X86_REG_EBP)
            assert self._read(ebp - 0x1E4) == self.key(name), "the displaced store still happens"

    # the lobby side

    def listed(self, index: int) -> bool:
        """Whether the faction fill keeps template `index`."""
        self._frame()
        ebp = self.uc.reg_read(UC_X86_REG_EBP)
        self._write(ebp + MP_SETUP_FACTION_LIST_INDEX_EBP, index)
        self.uc.reg_write(UC_X86_REG_ESI, self.vector + index * PLAYER_TEMPLATE_SIZE)
        return self.run("faction_list") == MP_SETUP_FACTION_LIST_PLAYABLE_RESUME

    def in_random_pool(self, index: int) -> bool:
        self._frame()
        ebp = self.uc.reg_read(UC_X86_REG_EBP)
        self._write(ebp + GAME_START_RANDOM_POOL_INDEX_EBP, index)
        self.uc.reg_write(UC_X86_REG_ESI, self.vector + index * PLAYER_TEMPLATE_SIZE)
        return self.run("random_pool") == GAME_START_RANDOM_POOL_RESUME

    def synced(self, slot: int) -> int:
        """What `syncFactionCombo` puts in the faction box for `slot`."""
        self._frame()
        self.uc.reg_write(UC_X86_REG_EDI, self.slots[slot])
        assert self.run("sync_template") == MP_SETUP_SYNC_FACTION_TEMPLATE_RESUME
        ebp = self.uc.reg_read(UC_X86_REG_EBP)
        return struct.unpack("<i", self.uc.mem_read(ebp - 0x14, 4))[0]

    def file_gadget(self, slot: int, kind: str) -> tuple[int, int]:
        """The binder's last rung for `~<slot>.<kind>`: `(exit, window)`."""
        window = self.window()
        self._frame()
        ebp = self.uc.reg_read(UC_X86_REG_EBP)
        self._write(ebp + MP_SETUP_GADGET_SLOT_EBP, slot)
        self.uc.reg_write(UC_X86_REG_EBX, self.cstr(kind))
        self.uc.reg_write(UC_X86_REG_ESI, window)
        self.uc.reg_write(UC_X86_REG_EDI, self.screen)
        return self.run("gadget"), window

    def variant_box(self, slot: int) -> int:
        exit_, window = self.file_gadget(slot, GADGET_KIND)
        assert exit_ == MP_SETUP_GADGET_FILED
        esp = STACK + 0x8000
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp - 4, "one window left for the rung's pop"
        return window

    def fill(self, slot: int) -> None:
        self.call("fill", slot, ecx=self.screen)

    def pick(self, slot: int, window: int, row: int) -> int:
        """The player picks `row` in `window`; the selection handler's unmatched edge runs."""
        self.boxes[window].selected = row
        self.resets.clear()
        esp = self._frame()
        self.uc.reg_write(UC_X86_REG_EBX, window)
        self.uc.reg_write(UC_X86_REG_ESI, self.screen)
        self.uc.reg_write(UC_X86_REG_EDI, 0x5555)
        assert self.run("selection") == MP_SETUP_SELECTION_DONE
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp
        assert self.uc.reg_read(UC_X86_REG_EDI) == 0x5555
        # The game crashes if a combo box is reset from inside its own selection message.
        assert window not in self.resets, "the picked box was reset from its own notification"
        return self.uc.mem_read(self.screen + MP_SETUP_DIRTY, 1)[0]


def _pages(size: int) -> int:
    return (size + PAGE - 1) & ~(PAGE - 1)


_EDAIN_LIKE = [
    ("FactionMen", "Gondor", True),
    ("FactionElves", "Lorien", True),
    ("FactionMen_DolAmroth", "Dol Amroth", True),
    ("FactionMen_Ithilien", "Ithilien", True),
    ("FactionMen_Hidden", "Hidden", False),
    ("FactionOrphan", "Orphan", True),
    ("FactionSelf", "Self", True),
]


@pytest.fixture
def engine() -> Engine:
    e = Engine(_EDAIN_LIKE)
    e.declare("FactionMen", None)
    e.declare("FactionElves", None)
    e.declare("FactionMen_DolAmroth", "FactionMen")
    e.declare("FactionMen_Ithilien", "FactionMen")
    e.declare("FactionMen_Hidden", "FactionMen")
    e.declare("FactionOrphan", "FactionNowhere")
    e.declare("FactionSelf", "FactionSelf")
    return e


class TestParse:
    def test_declarations_land_in_the_table(self, engine: Engine):
        rows = engine._read(engine.at["count"])
        got = {
            engine._read(engine.at["rows"] + 8 * i): engine._read(engine.at["rows"] + 8 * i + 4)
            for i in range(rows)
        }
        k = engine.key
        assert got == {
            k("FactionMen_DolAmroth"): k("FactionMen"),
            k("FactionMen_Ithilien"): k("FactionMen"),
            k("FactionMen_Hidden"): k("FactionMen"),
            k("FactionOrphan"): k("FactionNowhere"),
            k("FactionSelf"): k("FactionSelf"),
        }

    def test_a_block_without_the_field_does_not_inherit_the_last_one(self, engine: Engine):
        assert engine._read(engine.at["pending"]) == 0
        assert engine.listed(engine.index("FactionElves"))

    def test_an_override_redeclares_in_place(self, engine: Engine):
        before = engine._read(engine.at["count"])
        engine.declare("FactionMen_Ithilien", "FactionElves", override=True)
        assert engine._read(engine.at["count"]) == before
        engine.set_template(0, engine.index("FactionMen_Ithilien"))
        assert engine.synced(0) == engine.index("FactionElves")

    def test_a_full_table_drops_the_declaration_not_the_load(self):
        e = Engine([("A", "A", True)])
        for n in range(ROWS + 3):
            e.declare(f"V{n}", "A")
        assert e._read(e.at["count"]) == ROWS
        assert e._read(e.at["pending"]) == 0


class TestFactionList:
    def test_only_base_factions_and_broken_declarations_are_listed(self, engine: Engine):
        listed = {name for i, name in enumerate(engine.names) if engine.listed(i)}
        # Orphan names a template that does not exist and Self names itself: both stay factions.
        assert listed == {"FactionMen", "FactionElves", "FactionOrphan", "FactionSelf"}

    def test_random_draws_from_the_same_set(self, engine: Engine):
        pool = {name for i, name in enumerate(engine.names) if engine.in_random_pool(i)}
        assert pool == {"FactionMen", "FactionElves", "FactionOrphan", "FactionSelf"}

    @pytest.mark.parametrize(
        ("template", "shown"),
        [
            ("FactionMen_DolAmroth", "FactionMen"),
            ("FactionMen", "FactionMen"),
            ("FactionElves", "FactionElves"),
            ("FactionOrphan", "FactionOrphan"),
        ],
    )
    def test_the_faction_box_shows_a_variant_as_its_faction(self, engine, template, shown):
        engine.set_template(3, engine.index(template))
        assert engine.synced(3) == engine.index(shown)

    @pytest.mark.parametrize("special", [-1, -2])
    def test_random_and_observer_pass_through(self, engine: Engine, special: int):
        engine.set_template(3, special)
        assert engine.synced(3) == special


class TestGadget:
    def test_the_variant_kind_is_filed_for_this_screen(self, engine: Engine):
        window = engine.variant_box(2)
        assert engine._read(engine.at["boxes"] + 8) == window
        assert engine._read(engine.at["owners"] + 8) == engine.screen

    def test_other_kinds_fall_through_to_the_stock_rung(self, engine: Engine):
        exit_, _window = engine.file_gadget(2, "Hero")
        assert exit_ == MP_SETUP_GADGET_HERO_TEST_RESUME
        esp = engine.uc.reg_read(UC_X86_REG_ESP)
        assert engine._read(esp) == 0x00C04BF4, 'the displaced push of "Hero" is reproduced'

    def test_a_ninth_slot_is_refused(self, engine: Engine):
        exit_, _window = engine.file_gadget(8, GADGET_KIND)
        assert exit_ == MP_SETUP_GADGET_UNKNOWN

    def test_a_new_screen_forgets_the_old_boxes(self, engine: Engine):
        engine.variant_box(0)
        engine.call("ctor_clear", 0x1111, 0, 0x20, cdecl=True)
        assert engine.calls[-1] == ("memset", (0x1111, 0, 0x20)), "the displaced memset runs"
        for off in range(0, 24 * 4, 4):
            assert engine._read(engine.at["boxes"] + off) == 0


class TestVariantBox:
    def test_lists_the_faction_and_its_playable_variants(self, engine: Engine):
        box = engine.variant_box(1)
        engine.set_template(1, engine.index("FactionMen_Ithilien"))
        engine.fill(1)
        assert engine.calls[-1] == ("stock", (MP_SETUP_FACTION_COMBO, 1))
        rows = engine.boxes[box].rows
        assert rows == [
            ("<GUI:Random>", RANDOM_OF - engine.index("FactionMen")),
            (f"<{STANDARD_LABEL}>", engine.index("FactionMen")),
            ("Dol Amroth", engine.index("FactionMen_DolAmroth")),
            ("Ithilien", engine.index("FactionMen_Ithilien")),
        ]
        assert engine.boxes[box].selected == 3
        assert engine.status(box) == (True, True)
        assert not engine.strings, "every text built was handed to the box"

    def test_the_standard_label_may_name_the_faction(self, engine: Engine):
        engine.labels[STANDARD_LABEL] = "%s (Standard)"
        box = engine.variant_box(1)
        engine.set_template(1, engine.index("FactionMen_Ithilien"))
        engine.fill(1)
        assert engine.boxes[box].rows[1] == ("Gondor (Standard)", engine.index("FactionMen"))
        assert not engine.strings, "the label and the name were both released"

    def test_the_base_selects_the_standard_row(self, engine: Engine):
        box = engine.variant_box(1)
        engine.set_template(1, engine.index("FactionMen"))
        engine.fill(1)
        assert engine.boxes[box].selected == 1

    @pytest.mark.parametrize("faction", ["FactionElves", "FactionOrphan"])
    def test_a_faction_without_variants_shows_standard_alone(self, engine: Engine, faction):
        engine.labels[STANDARD_LABEL] = "%s (Standard)"
        box = engine.variant_box(1)
        engine.set_template(1, engine.index(faction))
        engine.fill(1)
        name = engine.display[engine.index(faction)]
        assert engine.boxes[box].rows == [(f"{name} (Standard)", engine.index(faction))]
        assert engine.boxes[box].selected == 0
        assert engine.status(box) == (True, True)
        assert not engine.strings

    def test_hidden_for_an_observer(self, engine: Engine):
        box = engine.variant_box(1)
        engine.set_template(1, -2)
        engine.fill(1)
        assert engine.boxes[box].rows == []
        assert engine.status(box) == (False, False)

    def test_follows_a_disabled_faction_box(self, engine: Engine):
        box = engine.variant_box(4)
        engine.set_template(4, engine.index("FactionMen_DolAmroth"))
        engine._flag(engine.faction_boxes[4], WINDOW_STATUS_ENABLED, 0)
        engine.fill(4)
        assert engine.status(box) == (True, False), "a remote player's pick is shown, not offered"
        # ... and the enable hook brings it back when the screen re-enables the faction box
        engine.uc.reg_write(UC_X86_REG_ESI, engine.screen)
        engine.uc.reg_write(UC_X86_REG_EDI, 4)
        esp = engine._frame()
        engine.uc.reg_write(UC_X86_REG_ESI, engine.screen)
        engine.uc.reg_write(UC_X86_REG_EDI, 4)
        engine._push(1, RETURN)
        engine.uc.reg_write(UC_X86_REG_ECX, engine.faction_boxes[4])
        assert engine.run("enable") == RETURN
        assert engine.uc.reg_read(UC_X86_REG_ESP) == esp
        assert engine.status(engine.faction_boxes[4]) == (True, True)
        assert engine.status(box) == (True, True)

    def test_follows_a_hidden_faction_box(self, engine: Engine):
        box = engine.variant_box(6)
        engine.set_template(6, engine.index("FactionMen"))
        engine._flag(engine.faction_boxes[6], WINDOW_STATUS_HIDDEN, 1)
        engine.fill(6)
        assert engine.status(box)[0] is False

    def test_the_sync_path_rebuilds_too(self, engine: Engine):
        box = engine.variant_box(0)
        engine.set_template(0, engine.index("FactionMen_DolAmroth"))
        engine.call("sync", 0, ecx=engine.screen)
        assert engine.calls[-1] == ("stock", (MP_SETUP_SYNC_FACTION, 0))
        assert engine.boxes[box].selected == 2

    def test_a_slot_without_a_variant_box_is_left_alone(self, engine: Engine):
        engine.set_template(5, engine.index("FactionMen"))
        engine.fill(5)  # no box filed for slot 5: nothing to do, and nothing to crash on


class TestRandom:
    @pytest.mark.parametrize(
        ("template", "row"), [(RANDOM_VARIANT, 0), (RANDOM_STANDARD, 1), (RANDOM_VARIANTS, 2)]
    )
    def test_a_random_slot_offers_random_and_standard(self, engine: Engine, template, row):
        box = engine.variant_box(1)
        engine.set_template(1, template)
        engine.fill(1)
        assert engine.boxes[box].rows == [
            ("<GUI:Random>", RANDOM_VARIANT),
            ("<GUI:FactionVariantStandard>", RANDOM_STANDARD),
            ("<GUI:FactionVariantVariants>", RANDOM_VARIANTS),
        ]
        assert engine.boxes[box].selected == row
        assert engine.status(box) == (True, True)

    def test_a_random_standard_row_is_named_random(self, engine: Engine):
        engine.labels.update({STANDARD_LABEL: "%s - Standard", "GUI:Random": "Random"})
        box = engine.variant_box(1)
        engine.set_template(1, RANDOM_STANDARD)
        engine.fill(1)
        texts = [text for text, _data in engine.boxes[box].rows]
        assert texts == ["Random", "Random - Standard", "<GUI:FactionVariantVariants>"]
        assert not engine.strings

    @pytest.mark.parametrize("template", [RANDOM_VARIANT, RANDOM_VARIANTS])
    def test_the_faction_box_shows_random_for_each(self, engine: Engine, template):
        engine.set_template(3, template)
        assert engine.synced(3) == RANDOM_STANDARD

    def test_picking_variants_asks_for_its_sentinel(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, RANDOM_STANDARD)
        engine.fill(2)
        engine.calls.clear()
        engine.pick(2, box, 2)
        assert engine.calls[0] == ("request", (2, RANDOM_VARIANTS))

    def test_no_variants_row_when_the_mod_has_none(self):
        e = Engine([("A", "A", True), ("B", "B", True)])
        box = e.variant_box(1)
        e.set_template(1, RANDOM_STANDARD)
        e.fill(1)
        assert [data for _text, data in e.boxes[box].rows] == [RANDOM_VARIANT, RANDOM_STANDARD]

    def test_picking_random_asks_for_the_new_sentinel(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, RANDOM_STANDARD)
        engine.fill(2)
        engine.calls.clear()
        engine.pick(2, box, 0)
        assert engine.calls[0] == ("request", (2, RANDOM_VARIANT))
        assert engine.template(2) == RANDOM_VARIANT

    def test_a_pending_random_pick_is_kept_by_the_fill(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, RANDOM_STANDARD)
        engine.fill(2)
        engine.requests = "defer"
        engine.pick(2, box, 0)
        engine.fill(2)
        assert engine.boxes[box].selected == 0, "Random and Standard are one family"

    def assign(self, engine: Engine, slot: int, drawn: str) -> int:
        """`startNewGame` giving `slot` the base faction `drawn`; returns what it was given."""
        esp = engine._frame()
        engine.uc.reg_write(UC_X86_REG_EBX, engine.slots[slot])
        engine.uc.reg_write(UC_X86_REG_ESI, engine.index(drawn))
        assert engine.run("random_assign") == GAME_START_RANDOM_ASSIGN_RESUME
        assert engine.uc.reg_read(UC_X86_REG_ESP) == esp
        given = engine.uc.reg_read(UC_X86_REG_ESI)
        assert engine.template(slot) == given, "the code after the hook reads esi"
        return given

    @pytest.mark.parametrize(
        ("draw", "expected"),
        [(0, "FactionMen"), (1, "FactionMen_DolAmroth"), (2, "FactionMen_Ithilien")],
    )
    def test_random_draws_among_the_faction_and_its_offered_variants(self, engine, draw, expected):
        engine.set_template(0, RANDOM_VARIANT)
        engine.draw = draw
        assert self.assign(engine, 0, "FactionMen") == engine.index(expected)
        # the unplayable FactionMen_Hidden is not a candidate: base + two variants
        assert engine.draws == [(0, 2)]

    def test_standard_plays_the_faction_drawn(self, engine: Engine):
        engine.set_template(0, RANDOM_STANDARD)
        engine.draw = 2
        assert self.assign(engine, 0, "FactionMen") == engine.index("FactionMen")
        assert engine.draws == [], "Standard consumes no random number"

    def test_a_faction_without_variants_draws_nothing(self, engine: Engine):
        engine.set_template(0, RANDOM_VARIANT)
        assert self.assign(engine, 0, "FactionElves") == engine.index("FactionElves")
        assert engine.draws == []


class TestRandomOfAFaction:
    def test_picking_it_asks_for_the_faction_s_random(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen_DolAmroth"))
        engine.fill(2)
        engine.calls.clear()
        engine.pick(2, box, 0)
        assert engine.calls[0] == ("request", (2, RANDOM_OF - engine.index("FactionMen")))

    def test_it_shows_as_its_faction_and_selects_random(self, engine: Engine):
        box = engine.variant_box(3)
        engine.set_template(3, RANDOM_OF - engine.index("FactionMen"))
        assert engine.synced(3) == engine.index("FactionMen")
        engine.fill(3)
        assert engine.boxes[box].selected == 0
        assert [data for _text, data in engine.boxes[box].rows][1:] == [
            engine.index("FactionMen"),
            engine.index("FactionMen_DolAmroth"),
            engine.index("FactionMen_Ithilien"),
        ]

    def test_a_pending_pick_of_it_is_kept_by_the_fill(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen"))
        engine.fill(2)
        engine.requests = "defer"
        engine.pick(2, box, 0)
        engine.fill(2)
        assert engine.boxes[box].selected == 0, "the faction's Random is of its family"

    def settle(self, engine: Engine, slot: int) -> int:
        """`startNewGame` reading `slot`'s template for the Random pass; returns what it read."""
        esp = engine._frame()
        engine.uc.reg_write(UC_X86_REG_EBX, engine.slots[slot])
        assert engine.run("slot_template") == GAME_START_SLOT_TEMPLATE_RESUME
        assert engine.uc.reg_read(UC_X86_REG_ESP) == esp
        read = struct.unpack("<i", struct.pack("<I", engine.uc.reg_read(UC_X86_REG_ESI)))[0]
        assert read == engine.template(slot), "the Random pass reads esi"
        return read

    @pytest.mark.parametrize(
        ("draw", "expected"),
        [(0, "FactionMen"), (1, "FactionMen_DolAmroth"), (2, "FactionMen_Ithilien")],
    )
    def test_game_start_settles_it_to_the_faction_or_a_variant(self, engine, draw, expected):
        engine.set_template(0, RANDOM_OF - engine.index("FactionMen"))
        engine.draw = draw
        assert self.settle(engine, 0) == engine.index(expected)
        assert engine.draws == [(0, 2)]

    @pytest.mark.parametrize("template", [RANDOM_STANDARD, RANDOM_VARIANT, -2, 1])
    def test_every_other_template_passes_through(self, engine: Engine, template):
        engine.set_template(0, template)
        engine.calls.clear()
        assert self.settle(engine, 0) == template
        assert engine.draws == []
        assert engine.calls == [], "nothing is set on the slot"


class TestVariantsOnly:
    def settle(self, engine: Engine, slot: int) -> int:
        esp = engine._frame()
        engine.uc.reg_write(UC_X86_REG_EBX, engine.slots[slot])
        assert engine.run("slot_template") == GAME_START_SLOT_TEMPLATE_RESUME
        assert engine.uc.reg_read(UC_X86_REG_ESP) == esp
        read = struct.unpack("<i", struct.pack("<I", engine.uc.reg_read(UC_X86_REG_ESI)))[0]
        assert read == engine.template(slot)
        return read

    @pytest.mark.parametrize(
        ("draw", "expected"), [(0, "FactionMen_DolAmroth"), (1, "FactionMen_Ithilien")]
    )
    def test_it_draws_among_every_offered_variant_only(self, engine, draw, expected):
        # Hidden is unplayable, Orphan and Self are no one's variant: two candidates.
        engine.set_template(0, RANDOM_VARIANTS)
        engine.draw = draw
        assert self.settle(engine, 0) == engine.index(expected)
        assert engine.draws == [(0, 1)]

    def test_with_no_variants_it_falls_back_to_standard(self):
        e = Engine([("A", "A", True), ("B", "B", True)])
        e.set_template(0, RANDOM_VARIANTS)
        assert self.settle(e, 0) == RANDOM_STANDARD, "left for the Random pass to draw a faction"
        assert e.draws == []


class TestPick:
    def test_a_pick_asks_for_the_template_and_redraws(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen"))
        engine.fill(2)
        engine.uc.mem_write(engine.screen + MP_SETUP_FACTION_REQUEST_PENDING, b"\x01")
        engine.calls.clear()
        dirty = engine.pick(2, box, 2)
        assert engine.calls[:2] == [
            ("request", (2, engine.index("FactionMen_DolAmroth"))),
            ("redraw", (2, 2, 1)),
        ]
        assert engine.template(2) == engine.index("FactionMen_DolAmroth")
        assert engine.boxes[box].selected == 2
        assert dirty == 1
        assert engine.uc.mem_read(engine.screen + MP_SETUP_FACTION_REQUEST_PENDING, 1)[0] == 0

    def test_a_pending_request_keeps_the_pick_on_screen(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen"))
        engine.fill(2)
        engine.requests = "refuse"
        engine.pick(2, box, 2)
        assert engine.template(2) == engine.index("FactionMen")
        assert [c[0] for c in engine.calls[-1:]] == ["request"], "refused: no redraw"

    def test_a_pending_request_that_is_accepted_later_keeps_the_pick(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen"))
        engine.fill(2)

        # accepted, but the host's answer has not arrived: the slot still holds the old template
        engine.requests = "defer"
        engine.pick(2, box, 3)
        assert engine.template(2) == engine.index("FactionMen")
        engine.fill(2)  # the screen's next update, before the host has answered
        assert engine.boxes[box].selected == 3, "the box keeps the pick until the host answers"
        engine.call("sync", 2, ecx=engine.screen)  # ... and the slot wins once it is synced
        assert engine.boxes[box].selected == 1

    def test_the_same_template_only_redraws(self, engine: Engine):
        box = engine.variant_box(2)
        engine.set_template(2, engine.index("FactionMen_DolAmroth"))
        engine.fill(2)
        engine.calls.clear()
        engine.pick(2, box, 2)
        assert [c[0] for c in engine.calls] == ["redraw"]

    def test_an_unknown_window_is_not_ours(self, engine: Engine):
        engine.variant_box(2)
        stranger = engine.window()
        engine.calls.clear()
        assert engine.pick(2, stranger, 0) == 0
        assert engine.calls == []

    def test_a_box_filed_by_another_screen_is_not_ours(self, engine: Engine):
        box = engine.variant_box(2)
        engine._write(engine.at["owners"] + 8, engine.screen + 0x10)
        engine.calls.clear()
        assert engine.pick(2, box, 1) == 0
        assert engine.calls == []


_SIDED = [
    ("FactionMen", "Gondor", True, False),
    ("FactionMordor", "Mordor", True, True),
    ("FactionElves", "Lorien", True, False),
    ("FactionIsengard", "Isengard", True, True),
    ("FactionMen_DolAmroth", "Dol Amroth", True, False),
    ("FactionMordor_Harad", "Harad", True, True),
    ("FactionHidden", "Hidden", False, True),
]


@pytest.fixture
def sided() -> Engine:
    e = Engine(_SIDED)
    for name, *_rest in _SIDED:
        e.declare(name, None)
    e.declare("FactionMen_DolAmroth", "FactionMen")
    e.declare("FactionMordor_Harad", "FactionMordor")
    return e


class TestGoodAndEvil:
    def test_a_random_slot_offers_both_sides_after_the_others(self, sided: Engine):
        box = sided.variant_box(1)
        sided.set_template(1, RANDOM_STANDARD)
        sided.fill(1)
        assert sided.boxes[box].rows == [
            ("<GUI:Random>", RANDOM_VARIANT),
            ("<GUI:FactionVariantStandard>", RANDOM_STANDARD),
            ("<GUI:FactionVariantVariants>", RANDOM_VARIANTS),
            (f"<{GOOD_LABEL}>", RANDOM_GOOD),
            (f"<{EVIL_LABEL}>", RANDOM_EVIL),
        ]
        assert sided.boxes[box].selected == 1
        assert not sided.strings

    @pytest.mark.parametrize(("template", "row"), [(RANDOM_GOOD, 3), (RANDOM_EVIL, 4)])
    def test_each_selects_its_row(self, sided: Engine, template: int, row: int):
        box = sided.variant_box(1)
        sided.set_template(1, template)
        sided.fill(1)
        assert sided.boxes[box].selected == row

    def test_a_mod_with_one_side_does_not_offer_them(self, engine: Engine):
        box = engine.variant_box(1)  # every faction of `engine` is Evil = No
        engine.set_template(1, RANDOM_STANDARD)
        engine.fill(1)
        data = [d for _text, d in engine.boxes[box].rows]
        assert RANDOM_GOOD not in data
        assert RANDOM_EVIL not in data

    def test_offered_without_variants_too(self):
        e = Engine([("A", "A", True, False), ("B", "B", True, True)])
        box = e.variant_box(1)
        e.set_template(1, RANDOM_STANDARD)
        e.fill(1)
        assert [d for _text, d in e.boxes[box].rows] == [
            RANDOM_VARIANT,
            RANDOM_STANDARD,
            RANDOM_GOOD,
            RANDOM_EVIL,
        ]

    def test_a_variant_alone_does_not_make_a_side(self):
        # The only Evil template is a variant: no Evil base faction to draw, so no rows.
        e = Engine([("A", "A", True, False), ("A_V", "AV", True, True)])
        e.declare("A", None)
        e.declare("A_V", "A")
        box = e.variant_box(1)
        e.set_template(1, RANDOM_STANDARD)
        e.fill(1)
        assert RANDOM_EVIL not in [d for _text, d in e.boxes[box].rows]

    @pytest.mark.parametrize("template", [RANDOM_GOOD, RANDOM_EVIL])
    def test_the_faction_box_shows_random(self, sided: Engine, template: int):
        sided.set_template(3, template)
        assert sided.synced(3) == RANDOM_STANDARD

    @pytest.mark.parametrize(("row", "template"), [(3, RANDOM_GOOD), (4, RANDOM_EVIL)])
    def test_picking_asks_for_its_sentinel(self, sided: Engine, row: int, template: int):
        box = sided.variant_box(2)
        sided.set_template(2, RANDOM_STANDARD)
        sided.fill(2)
        sided.calls.clear()
        sided.pick(2, box, row)
        assert sided.calls[0] == ("request", (2, template))
        assert sided.template(2) == template

    def test_a_pending_pick_is_kept_by_the_fill(self, sided: Engine):
        box = sided.variant_box(2)
        sided.set_template(2, RANDOM_STANDARD)
        sided.fill(2)
        sided.requests = "defer"
        sided.pick(2, box, 4)
        sided.fill(2)
        assert sided.boxes[box].selected == 4, "every Random of a slot is one family"

    @pytest.mark.parametrize("template", [RANDOM_GOOD, RANDOM_EVIL])
    def test_game_start_leaves_it_to_the_random_pass(self, sided: Engine, template: int):
        sided.set_template(0, template)
        sided.calls.clear()
        esp = sided._frame()
        sided.uc.reg_write(UC_X86_REG_EBX, sided.slots[0])
        assert sided.run("slot_template") == GAME_START_SLOT_TEMPLATE_RESUME
        assert sided.uc.reg_read(UC_X86_REG_ESP) == esp
        assert sided.calls == [] and sided.draws == []

    @pytest.mark.parametrize("template", [RANDOM_GOOD, RANDOM_EVIL])
    def test_the_drawn_faction_is_played_as_it_stands(self, sided: Engine, template: int):
        sided.set_template(0, template)
        sided._frame()
        sided.uc.reg_write(UC_X86_REG_EBX, sided.slots[0])
        sided.uc.reg_write(UC_X86_REG_ESI, sided.index("FactionMordor"))
        assert sided.run("random_assign") == GAME_START_RANDOM_ASSIGN_RESUME
        assert sided.template(0) == sided.index("FactionMordor")
        assert sided.draws == [], "no variant draw: Good and Evil are Standard of a side"


class TestSidedDraw:
    """The hook at the Random draw, with the slot's candidates as a real `std::vector<Int>`."""

    SENTINEL_EBX = 0x7777

    def draw(self, e: Engine, slot: int, candidates: list[str]) -> list[str]:
        """Run the hook for `slot` over `candidates`; returns what the stock draw then sees."""
        e._frame()
        ebp = e.uc.reg_read(UC_X86_REG_EBP)
        vector = e._alloc(4 * len(candidates) + 4)
        for i, name in enumerate(candidates):
            e._write(vector + 4 * i, e.index(name))
        e._write(ebp + GAME_START_RANDOM_CANDIDATES_EBP, vector)
        e._write(ebp + GAME_START_RANDOM_CANDIDATES_EBP + 4, vector + 4 * len(candidates))
        e._write(ebp + GAME_START_RANDOM_SLOT_EBP, e.slots[slot])
        e.uc.reg_write(UC_X86_REG_EBX, self.SENTINEL_EBX)
        esp = e.uc.reg_read(UC_X86_REG_ESP)
        assert e.run("random_side") == GAME_START_RANDOM_DRAW_RESUME
        assert e.uc.reg_read(UC_X86_REG_ESP) == esp
        assert e.uc.reg_read(UC_X86_REG_EBX) == self.SENTINEL_EBX
        begin = e._read(ebp + GAME_START_RANDOM_CANDIDATES_EBP)
        end = e._read(ebp + GAME_START_RANDOM_CANDIDATES_EBP + 4)
        assert begin == vector, "the block is freed through its begin"
        # the displaced loads: esi = end, edi = begin
        assert e.uc.reg_read(UC_X86_REG_ESI) == end
        assert e.uc.reg_read(UC_X86_REG_EDI) == begin
        return [e.names[e._read(va)] for va in range(begin, end, 4)]

    _POOL = ["FactionMen", "FactionMordor", "FactionElves", "FactionIsengard"]

    def test_good_keeps_the_good_factions_in_order(self, sided: Engine):
        sided.set_template(0, RANDOM_GOOD)
        assert self.draw(sided, 0, self._POOL) == ["FactionMen", "FactionElves"]

    def test_evil_keeps_the_evil_factions_in_order(self, sided: Engine):
        sided.set_template(0, RANDOM_EVIL)
        assert self.draw(sided, 0, self._POOL) == ["FactionMordor", "FactionIsengard"]

    def test_a_start_position_that_left_none_of_the_side_keeps_them_all(self, sided: Engine):
        sided.set_template(0, RANDOM_EVIL)
        assert self.draw(sided, 0, ["FactionMen", "FactionElves"]) == [
            "FactionMen",
            "FactionElves",
        ]

    @pytest.mark.parametrize("template", [RANDOM_STANDARD, RANDOM_VARIANT, RANDOM_VARIANTS])
    def test_every_other_random_is_left_alone(self, sided: Engine, template: int):
        sided.set_template(0, template)
        assert self.draw(sided, 0, self._POOL) == self._POOL

    def test_an_empty_pool_is_left_alone(self, sided: Engine):
        sided.set_template(0, RANDOM_GOOD)
        assert self.draw(sided, 0, []) == []


class TestArrow:
    """The Variant box's drop-down arrow shows whenever the box is usable, as every column's does -
    including a faction without variants, whose list of one the gadget would leave arrowless."""

    @pytest.mark.parametrize("faction", ["FactionElves", "FactionMen"])
    def test_an_enabled_box_shows_its_arrow(self, engine: Engine, faction: str):
        box = engine.variant_box(1)
        engine.set_template(1, engine.index(faction))
        engine.fill(1)
        assert engine.status(box) == (True, True)
        assert engine.arrow(box)

    def test_a_single_row_box_shows_it_too(self, engine: Engine):
        box = engine.variant_box(1)
        engine.set_template(1, engine.index("FactionElves"))
        engine.fill(1)
        assert len(engine.boxes[box].rows) == 1
        assert engine.arrow(box), "the gadget alone would have disabled the button here"

    def test_a_disabled_box_does_not(self, engine: Engine):
        box = engine.variant_box(4)
        engine.set_template(4, engine.index("FactionMen_DolAmroth"))
        engine._flag(engine.faction_boxes[4], WINDOW_STATUS_ENABLED, 0)
        engine.fill(4)
        assert engine.status(box) == (True, False)
        assert not engine.arrow(box), "a remote player's row looks like the other columns"

    def test_the_enable_hook_brings_the_arrow_back(self, engine: Engine):
        box = engine.variant_box(4)
        engine.set_template(4, engine.index("FactionElves"))
        engine._flag(engine.faction_boxes[4], WINDOW_STATUS_ENABLED, 0)
        engine.fill(4)
        assert not engine.arrow(box)
        esp = engine._frame()
        engine.uc.reg_write(UC_X86_REG_ESI, engine.screen)
        engine.uc.reg_write(UC_X86_REG_EDI, 4)
        engine._push(1, RETURN)
        engine.uc.reg_write(UC_X86_REG_ECX, engine.faction_boxes[4])
        assert engine.run("enable") == RETURN
        assert engine.uc.reg_read(UC_X86_REG_ESP) == esp
        assert engine.arrow(box)


class TestOpenGate:
    """The combo box toggle opens a list of two or more; a Variant box also opens a list of one,
    and nothing else in the game does."""

    def opens(self, e: Engine, box: int, entries: int) -> bool:
        e._frame()
        ebp = e.uc.reg_read(UC_X86_REG_EBP)
        data = e._read(box + COMBO_BOX_GADGET_DATA)
        e._write(data + COMBO_BOX_ENTRY_COUNT, entries)
        e._write(ebp + COMBO_BOX_TOGGLE_BOX_EBP, box)
        e.uc.reg_write(UC_X86_REG_EDI, data)
        e.uc.reg_write(UC_X86_REG_EBX, 0x6666)
        e.uc.reg_write(UC_X86_REG_ESI, 0x5555)
        exit_ = e.run("open_gate")
        assert e.uc.reg_read(UC_X86_REG_EDI) == data, "the code after it reads the data in edi"
        assert e.uc.reg_read(UC_X86_REG_EBX) == 0x6666
        assert e.uc.reg_read(UC_X86_REG_ESI) == 0x5555
        return exit_ == COMBO_BOX_OPEN_GO

    def test_a_variant_box_opens_on_its_standard_row_alone(self, engine: Engine):
        assert self.opens(engine, engine.variant_box(3), 1)

    def test_any_other_box_still_needs_two(self, engine: Engine):
        assert not self.opens(engine, engine.faction_boxes[3], 1)
        assert not self.opens(engine, engine.window(), 1)

    @pytest.mark.parametrize("entries", [2, 5])
    def test_two_or_more_open_everywhere(self, engine: Engine, entries: int):
        assert self.opens(engine, engine.faction_boxes[3], entries)
        assert self.opens(engine, engine.variant_box(3), entries)

    def test_an_empty_box_never_opens(self, engine: Engine):
        assert not self.opens(engine, engine.variant_box(3), 0)
        assert not self.opens(engine, engine.window(), 0)
