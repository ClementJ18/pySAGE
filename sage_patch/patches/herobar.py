"""`HEROBAR` - a kindof that gives an object a hero-bar slot shared with its own kind.

Every instance of one `ThingTemplate` occupies **one** slot; two different templates occupy two.
Clicking a grouped slot selects the whole group. That is deliberately not what `PORTER` does:
`PORTER` collapses every porter into a **single** slot whatever template it came from, and
clicking that slot walks the mixed set one object at a time.

Why this is small
-----------------
The hero bar already has the shape this needs, for porters, and almost all of it is generic:

* the slot cache is `0x18` bytes x 16 at `bar+0x48`, and `slot+0x16` is a **"this slot is a
  group" byte** that the click handler at `0x0092DBD6` already reads and dispatches on;
* a group slot is drawn with the *same* ActionScript calls as a hero slot, so nothing about the
  `.apt` movie changes;
* `KindOfMaskType` has two free bits, so the kindof itself costs no data growth (see
  :mod:`.kind_of`).

So this patch adds no drawing code at all. It puts `HEROBAR` objects on the **hero list** - the
one the draw loop already walks, sorted, slot by slot - and then does three small things around
that loop: reset a per-pass set of templates before it starts, skip a node whose template has
already been drawn this pass, and mark the slot it did draw as a group. The engine draws the
representative; the duplicates simply never reach a slot.

Six hooks, all five-to-seven-byte detours:

===========  ==========================  ====================================================
site         engine function             what the detour adds
===========  ==========================  ====================================================
`0x0092CD7F` `onObjectAdded`             `HEROBAR` joins `HERO` on the way to the hero list
`0x0092C439` `onObjectRemoved` gate      `HEROBAR` is a thing this function accepts at all
`0x0092C467` `onObjectRemoved` list      ...and removes from the hero list, not the porter one
`0x0092D36F` draw-loop preheader         clear the per-pass template set
`0x0092D3EE` draw loop, per node         skip a template already drawn; mark the slot
`0x0092DBD6` click dispatch              a `2` in `slot+0x16` means "select this whole group"
===========  ==========================  ====================================================

The removal pair is not optional bookkeeping: without it a dead `HEROBAR` object's node stays on
the hero list forever, because the stock gate accepts only `HERO` and `PORTER`.

Known limits, stated rather than discovered
-------------------------------------------
* **No count badge.** A `PORTER` slot shows how many porters there are, because the porter path
  writes the count where a hero's rank goes. Here the engine draws the representative unmodified,
  so the slot shows *its* rank and health. Adding a badge means writing `SetButtonRankProgress`
  from the cave, which is a call through the APT bridge and a much bigger patch.
* **The bar is still 16 slots.** Groups consume slots, so enough distinct `HEROBAR` templates in
  play push heroes off the end - the stock `buttonIndex >= 0x11` break at `0x0092D3E5`, which
  drops them silently rather than crashing.
* **`HERO` wins.** The classifier tests `HERO` first, so a template carrying both is a hero and
  never groups.
* **Not run in a game.** Everything below is derived statically. See ``../docs/herobar.md``.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, EnumDelta

from ..asm import JAE, JE, JNE, JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import apply_byte_patch, find_section
from . import kind_of
from .name_tables import offset as _offset

__all__ = [
    "DEFAULT_KINDOF",
    "HOOKS",
    "SECTION_CHARACTERISTICS",
    "SECTION_NAME",
    "STATE_SIZE",
    "Cave",
    "HeroBarPatch",
    "build_cave",
]

SECTION_NAME = ".hbar"

#: `CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE`. The cave holds the
#: rebuilt name table, the new name, the hook code *and* the scratch words the draw hook writes
#: once per node, and a section carries one set of page permissions for all of it.
SECTION_CHARACTERISTICS = 0xE0000060

DEFAULT_KINDOF = "HEROBAR"

# --- the engine, as this build has it -------------------------------------------------------

#: `KindOfMaskType` bit 90. Tested inline as `test byte [tmpl+0x113], 4` wherever the engine asks
#: "is this a hero", which is the encoding :func:`kind_of.bit_test` reproduces.
HERO_BIT = 90

#: ModRM r/m encodings, for the register a `bit_test` reads the template through.
_EAX, _ECX, _ESI = 0, 1, 6

THE_GAME_LOGIC = 0x00DE412C
THE_IN_GAME_UI = 0x00DE4830
THE_MESSAGE_STREAM = 0x00DE6398

FIND_OBJECT_BY_ID = 0x00449681  # thiscall(TheGameLogic, ObjectID) -> Object*, ret 4
OBJECT_GET_DRAWABLE = 0x0070E013  # thiscall(Object) -> Drawable*, ret 0
APPEND_BOOLEAN_ARGUMENT = 0x00711104  # thiscall(GameMessage, bool), ret 4
APPEND_OBJECT_ID_ARGUMENT = 0x0071111A  # thiscall(GameMessage, ObjectID), ret 4
BAR_ACCEPTS_OBJECT = 0x0092BBEF  # (Object*) -> bool: local player && !NO_HERO_PROPERTIES, ret 4

#: `TheInGameUI` vtable slots, as the hero bar's own click path uses them.
UI_DESELECT_ALL = 0x110
UI_SELECT_DRAWABLE = 0x108
#: `TheMessageStream::appendMessage(GameMessageType) -> GameMessage*`.
STREAM_APPEND_MESSAGE = 0x48
#: The message the hero bar's single-object click raises. Appending more than one `ObjectID` to
#: it is what turns it into a group selection.
MSG_CREATE_SELECTED_GROUP = 0x3E9

#: `bar+0x10` is the shared model; `model+0x10` is the hero list, whose head node doubles as the
#: end-of-list sentinel. `bar+0x48` is the slot array, `0x18` bytes per slot.
BAR_MODEL = 0x10
MODEL_HERO_LIST = 0x10
SLOT_ARRAY = 0x48
SLOT_STRIDE = 0x18
#: Within a slot: the list node it is showing, and the "this slot is a group" byte.
SLOT_NODE = 0x00
SLOT_GROUPED = 0x16
#: What this patch writes into :data:`SLOT_GROUPED`. `1` is the stock porter group, and the two
#: have to stay distinguishable because they dispatch to different click behaviour.
GROUPED_HEROBAR = 2

#: The draw loop reaches its per-node hook with the slot pointer already biased by 4, so the
#: group byte is at `edi + 0x12` and the node it is replacing is at `edi - 4`.
_EDI_SLOT_BIAS = 4

# --- the six hook sites ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Hook:
    """One detour: where it goes, what has to be there first, and which cave label it enters."""

    va: int
    original: bytes
    label: str
    note: str

    @property
    def size(self) -> int:
        return len(self.original)


HOOKS = (
    _Hook(
        0x0092CD7F,
        bytes.fromhex("f6801301000004"),  # test byte [eax+0x113], 4
        "classify",
        "onObjectAdded: route HEROBAR to the hero list",
    ),
    _Hook(
        0x0092C439,
        bytes.fromhex("85b810010000"),  # test [eax+0x110], edi
        "remove_gate",
        "onObjectRemoved: accept HEROBAR at all",
    ),
    _Hook(
        0x0092C467,
        bytes.fromhex("85be10010000"),  # test [esi+0x110], edi
        "remove_list",
        "onObjectRemoved: erase HEROBAR from the hero list",
    ),
    _Hook(
        0x0092D36F,
        bytes.fromhex("8b45dc8d4801"),  # mov eax,[ebp-0x24] ; lea ecx,[eax+1]
        "pass_reset",
        "draw loop preheader: clear the per-pass template set",
    ),
    _Hook(
        0x0092D3EE,
        bytes.fromhex("3b5ffc7432"),  # cmp ebx,[edi-4] ; je 0x92d425
        "per_node",
        "draw loop: one slot per template, and mark it",
    ),
    _Hook(
        0x0092DBD6,
        bytes.fromhex("807c315e00"),  # cmp byte [ecx+esi+0x5e], 0
        "click",
        "click dispatch: select the whole group",
    ),
)

# Where each detour rejoins the engine.
_CLASSIFY_HERO = 0x0092CD88  # push edx ; call addHero
_CLASSIFY_PORTER = 0x0092CD90  # the stock PORTER test
_REMOVE_GATE_RESUME = 0x0092C43F  # mov ebx,ecx ; jne <hero>
_REMOVE_LIST_RESUME = 0x0092C46D  # je <porter list>
_PASS_RESET_RESUME = 0x0092D375  # imul eax, eax, 0x18
_PER_NODE_SAME = 0x0092D425  # the slot already shows this node
_PER_NODE_DRAW = 0x0092D3F3  # draw the slot from scratch
_PER_NODE_SKIP = 0x0092D76F  # next node, without consuming a slot
_CLICK_PORTER = 0x0092DBDD  # the stock porter cycle
_CLICK_SINGLE = 0x0092DBEB  # the stock single-object select
_CLICK_DONE = 0x0092DDE1  # pop edi ; pop esi ; leave ; ret 4

# --- the cave ------------------------------------------------------------------------------

#: Scratch words at the head of the cave, in this order: the per-pass template set and its
#: length, then the four values the click routine carries across the calls it makes. Sized to a
#: round `0x60` so the code that follows starts on a recognisable boundary.
_MAX_SLOTS = 16
STATE_SIZE = 0x60
_OFF_EMITTED_N = 0x00
_OFF_EMITTED = 0x04  # 16 dwords, 0x04..0x43
_OFF_TEMPLATE = 0x44
_OFF_MESSAGE = 0x48
_OFF_SENTINEL = 0x4C
_OFF_NODE = 0x50


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _abs_mem(opcode: bytes, va: int) -> bytes:
    """An instruction whose only operand is `[disp32]` - the cave's own scratch words."""
    return opcode + _u32(va)


@dataclass(frozen=True)
class Cave:
    """What :func:`build_cave` laid out: the bytes, and where each detour has to land.

    The two travel together because they come from one emission. Recomputing the entry VAs by
    counting the code a second time is exactly the arithmetic :mod:`..asm` exists to remove."""

    content: bytes
    entries: dict[str, int]


def build_cave(base_va: int, bit: int) -> Cave:
    """The scratch words and all six hook routines, laid out at ``base_va``.

    Deterministic: :meth:`HeroBarPatch.apply` and :meth:`HeroBarPatch.verify` build the same
    bytes from the same ``(base_va, bit)`` and compare them, which is what makes verification
    possible without a disassembler."""
    emitted_n = base_va + _OFF_EMITTED_N
    emitted = base_va + _OFF_EMITTED
    template = base_va + _OFF_TEMPLATE
    message = base_va + _OFF_MESSAGE
    sentinel = base_va + _OFF_SENTINEL
    node = base_va + _OFF_NODE

    is_hero = kind_of.bit_test(HERO_BIT, _EAX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_eax = kind_of.bit_test(bit, _EAX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_ecx = kind_of.bit_test(bit, _ECX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_esi = kind_of.bit_test(bit, _ESI, kind_of.THING_TEMPLATE_MASK_OFFSET)

    a = Asm(base_va + STATE_SIZE)

    # --- classify: eax = ThingTemplate, edx = Object ----------------------------------------
    # The stock code is `HERO ? addHero : PORTER ? addPorter`. This makes the first arm
    # `HERO || HEROBAR` by re-testing both bits and re-entering at whichever arm won, so neither
    # the `je` nor the two calls the engine already has need touching.
    a.label("classify")
    a.emit(is_hero).jcc(JNZ, "classify_hero")
    a.emit(is_herobar_eax).jcc(JNZ, "classify_hero")
    a.jmp_absolute(_CLASSIFY_PORTER)
    a.label("classify_hero").jmp_absolute(_CLASSIFY_HERO)

    # --- remove_gate: eax = ThingTemplate, edi = the HERO bit within dword 2 -----------------
    # Both removal hooks end by falling into the engine's own branch, so what they have to get
    # right is the flags, not a target: the last `test` executed is the one the engine reads.
    a.label("remove_gate")
    a.emit(bytes.fromhex("85b810010000")).jcc(JZ, "remove_gate_herobar")  # test [eax+0x110],edi
    a.jmp_absolute(_REMOVE_GATE_RESUME)
    a.label("remove_gate_herobar").emit(is_herobar_eax).jmp_absolute(_REMOVE_GATE_RESUME)

    # --- remove_list: esi = ThingTemplate, edi = the HERO bit --------------------------------
    a.label("remove_list")
    a.emit(bytes.fromhex("85be10010000")).jcc(JZ, "remove_list_herobar")  # test [esi+0x110],edi
    a.jmp_absolute(_REMOVE_LIST_RESUME)
    a.label("remove_list_herobar").emit(is_herobar_esi).jmp_absolute(_REMOVE_LIST_RESUME)

    # --- pass_reset: the loop preheader, run once per draw pass ------------------------------
    a.label("pass_reset")
    a.emit(_abs_mem(bytes.fromhex("8325"), emitted_n), 0x00)  # and dword [emitted_n], 0
    a.emit(bytes.fromhex("8b45dc"))  # mov eax, [ebp-0x24]   (the displaced pair)
    a.emit(bytes.fromhex("8d4801"))  # lea ecx, [eax+1]
    a.jmp_absolute(_PASS_RESET_RESUME)

    # --- per_node: ebx = list node, edi = slot+4, [ebp-0x20] = Object -----------------------
    # Runs after the engine's own eligibility and slot-ceiling checks, so a node that reaches
    # here is one the engine was about to draw. Jumping to the engine's "next node" label skips
    # it *without* consuming the slot, which is exactly what a duplicate needs.
    a.label("per_node")
    a.emit(bytes.fromhex("505152"))  # push eax ; push ecx ; push edx
    a.emit(bytes.fromhex("8b4de0"))  # mov ecx, [ebp-0x20]   -> Object
    a.emit(bytes.fromhex("8b4904"))  # mov ecx, [ecx+4]      -> ThingTemplate
    a.emit(is_herobar_ecx).jcc(JZ, "per_node_plain")

    a.emit(bytes.fromhex("33c0"))  # xor eax, eax
    a.label("per_node_scan")
    a.emit(_abs_mem(bytes.fromhex("3b05"), emitted_n)).jcc(JAE, "per_node_add")  # cmp eax,[n]
    a.emit(_abs_mem(bytes.fromhex("8b1485"), emitted))  # mov edx, [emitted + eax*4]
    a.emit(bytes.fromhex("3bd1")).jcc(JE, "per_node_dup")  # cmp edx, ecx
    a.emit(bytes.fromhex("40")).jmp("per_node_scan")  # inc eax

    a.label("per_node_add")
    a.emit(bytes.fromhex("83f8"), _MAX_SLOTS).jcc(JAE, "per_node_mark")  # cmp eax, 16
    a.emit(_abs_mem(bytes.fromhex("890c85"), emitted))  # mov [emitted + eax*4], ecx
    a.emit(_abs_mem(bytes.fromhex("ff05"), emitted_n))  # inc dword [emitted_n]

    a.label("per_node_mark")
    a.emit(bytes.fromhex("c647"), SLOT_GROUPED - _EDI_SLOT_BIAS, GROUPED_HEROBAR)
    a.jmp("per_node_resume")

    a.label("per_node_plain")
    a.emit(bytes.fromhex("c647"), SLOT_GROUPED - _EDI_SLOT_BIAS, 0x00)

    a.label("per_node_resume")
    a.emit(bytes.fromhex("5a5958"))  # pop edx ; pop ecx ; pop eax
    a.emit(bytes.fromhex("3b5ffc"))  # cmp ebx, [edi-4]      (the displaced instruction)
    a.jcc(JNE, "per_node_draw")
    a.jmp_absolute(_PER_NODE_SAME)
    a.label("per_node_draw").jmp_absolute(_PER_NODE_DRAW)

    a.label("per_node_dup")
    a.emit(bytes.fromhex("5a5958"))  # pop edx ; pop ecx ; pop eax
    a.jmp_absolute(_PER_NODE_SKIP)

    # --- click: eax = slot index, ecx = index*0x18, esi = the bar ----------------------------
    # Three-way instead of the stock two-way. Reading the byte twice rather than caching it in a
    # register keeps every register the two stock arms expect exactly as they expect it.
    a.label("click")
    a.emit(bytes.fromhex("807c315e"), GROUPED_HEROBAR).jcc(JE, "click_group")
    a.emit(bytes.fromhex("807c315e"), 0x00).jcc(JNE, "click_porter")
    a.jmp_absolute(_CLICK_SINGLE)
    a.label("click_porter").jmp_absolute(_CLICK_PORTER)

    # --- click_group: select every live member of the clicked slot's template ---------------
    a.label("click_group")
    a.emit(bytes.fromhex("6bc0"), SLOT_STRIDE)  # imul eax, eax, 0x18
    a.emit(bytes.fromhex("8b8430"), _u32(SLOT_ARRAY + SLOT_NODE))  # mov eax,[eax+esi+0x48]
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_done")  # test eax, eax
    a.emit(_abs_mem(bytes.fromhex("a3"), node))  # mov [node], eax

    # The slot's node pointer is only as fresh as the last draw pass, so it is validated against
    # the live list before anything dereferences it. A slot left marked from an earlier pass then
    # costs a walk and nothing else.
    a.emit(bytes.fromhex("8b4e"), BAR_MODEL)  # mov ecx, [esi+0x10]
    a.emit(bytes.fromhex("8b49"), MODEL_HERO_LIST)  # mov ecx, [ecx+0x10]
    a.emit(_abs_mem(bytes.fromhex("890d"), sentinel))  # mov [sentinel], ecx
    a.emit(bytes.fromhex("8b39"))  # mov edi, [ecx]
    a.label("click_validate")
    a.emit(_abs_mem(bytes.fromhex("3b3d"), sentinel)).jcc(JE, "click_done")  # cmp edi,[sentinel]
    a.emit(_abs_mem(bytes.fromhex("3b3d"), node)).jcc(JE, "click_found")  # cmp edi, [node]
    a.emit(bytes.fromhex("8b3f")).jmp("click_validate")  # mov edi, [edi]

    a.label("click_found")
    a.emit(bytes.fromhex("ff7708"))  # push dword [edi+8]    (ObjectID)
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_done")
    a.emit(bytes.fromhex("8b4004"))  # mov eax, [eax+4]      -> ThingTemplate
    a.emit(_abs_mem(bytes.fromhex("a3"), template))  # mov [template], eax

    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_IN_GAME_UI))
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("ff90"), _u32(UI_DESELECT_ALL))  # call [eax+0x110]

    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_MESSAGE_STREAM))
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("68"), _u32(MSG_CREATE_SELECTED_GROUP))
    a.emit(bytes.fromhex("ff50"), STREAM_APPEND_MESSAGE)  # call [eax+0x48]
    a.emit(_abs_mem(bytes.fromhex("a3"), message))  # mov [message], eax
    a.emit(bytes.fromhex("6a01"))  # push 1                (create a new group)
    a.emit(bytes.fromhex("8bc8"))  # mov ecx, eax
    a.call_absolute(APPEND_BOOLEAN_ARGUMENT)

    a.emit(_abs_mem(bytes.fromhex("8b0d"), sentinel))  # mov ecx, [sentinel]
    a.emit(bytes.fromhex("8b39"))  # mov edi, [ecx]
    a.label("click_loop")
    a.emit(_abs_mem(bytes.fromhex("3b3d"), sentinel)).jcc(JE, "click_done")
    a.emit(bytes.fromhex("ff7708"))  # push dword [edi+8]
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_next")
    a.emit(bytes.fromhex("8b4804"))  # mov ecx, [eax+4]
    a.emit(_abs_mem(bytes.fromhex("3b0d"), template)).jcc(JNE, "click_next")

    a.emit(bytes.fromhex("50"))  # push eax              (keep the Object)
    a.emit(bytes.fromhex("50"))  # push eax              (the argument)
    a.emit(bytes.fromhex("8bce"))  # mov ecx, esi
    a.call_absolute(BAR_ACCEPTS_OBJECT)  # ret 4
    a.emit(bytes.fromhex("59"))  # pop ecx               -> the Object again
    a.emit(bytes.fromhex("84c0")).jcc(JZ, "click_next")  # test al, al

    a.emit(bytes.fromhex("51"))  # push ecx
    a.emit(bytes.fromhex("ff7174"))  # push dword [ecx+0x74]  (ObjectID)
    a.emit(_abs_mem(bytes.fromhex("8b0d"), message))
    a.call_absolute(APPEND_OBJECT_ID_ARGUMENT)  # ret 4
    a.emit(bytes.fromhex("59"))  # pop ecx
    a.call_absolute(OBJECT_GET_DRAWABLE)  # -> eax
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_next")
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_IN_GAME_UI))
    a.emit(bytes.fromhex("50"))  # push eax              (the Drawable)
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("ff90"), _u32(UI_SELECT_DRAWABLE))  # call [eax+0x108]

    a.label("click_next")
    a.emit(bytes.fromhex("8b3f")).jmp("click_loop")  # mov edi, [edi]

    a.label("click_done").jmp_absolute(_CLICK_DONE)

    code = a.finish()
    return Cave(
        content=bytes(STATE_SIZE) + code,
        entries={hook.label: a.label_va(hook.label) for hook in HOOKS},
    )


@dataclass
class HeroBarPatch(Patch):
    """Add a `HEROBAR` kindof that groups a template's instances into one hero-bar slot."""

    name = "herobar"
    description = (
        "add a HEROBAR kindof: every instance of one template shares a hero-bar slot, "
        "and clicking it selects the whole group"
    )

    kindof: str = DEFAULT_KINDOF

    def apply(self, data: bytearray) -> None:
        extension = kind_of.extend(
            data,
            SECTION_NAME,
            [self.kindof],
            tail=lambda tail_va, bits: build_cave(tail_va, bits[0]).content,
            characteristics=SECTION_CHARACTERISTICS,
        )
        cave = build_cave(extension.tail_va, extension.bits[0])
        for hook in HOOKS:
            apply_byte_patch(
                data,
                _offset(data, hook.va),
                hook.original,
                _detour(hook, cave.entries[hook.label]),
                f"{hook.note} @0x{hook.va:08x}",
            )

    def ini_surface(self) -> Engine:
        """The one token this patch teaches the INI parser, as a `KindOf` member.

        No index is stated: which bit the name lands on depends on what else the binary already
        carries, so the generator reads it back from the live table instead."""
        return Engine(enum_members=(EnumDelta(enum="KindOf", name=self.kindof, patch=self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this kindof name.

        Reads only via ``struct`` and the section table. Both the bit and the end of the table
        come from **the cave's own copy**, never from the live one: a second kindof-adding patch
        becomes the live table and shifts nothing about this one, and this patch is still
        correctly installed. The live table is consulted only to confirm it still agrees."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            entries = _cave_table_entries(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot read the {SECTION_NAME} cave's name table: {exc}"]

        bit = entries - 1
        name = kind_of.read_cstring(data, _cave_entry(data, section_va, bit))
        if name != self.kindof:
            return [f"the {SECTION_NAME} cave adds kindof {name!r}, not {self.kindof!r}"]

        tail_va = section_va + entries * 4 + 4 + _padded(len(self.kindof) + 1)
        cave = build_cave(tail_va, bit)
        if not section_va <= tail_va < section_va + vsize:
            return [f"the {SECTION_NAME} cave is too small to hold the hook code"]

        problems: list[str] = []
        try:
            table = kind_of.read(data)
        except (ValueError, struct.error) as exc:
            problems.append(f"cannot read the live kindof name table (wrong build?): {exc}")
        else:
            if table.index_of(data, self.kindof) != bit:
                problems.append(
                    f"{self.kindof!r} is kindof {table.index_of(data, self.kindof)} in the live "
                    f"table but {bit} in the {SECTION_NAME} cave"
                )

        off = _offset(data, tail_va)
        if bytes(data[off : off + len(cave.content)]) != cave.content:
            problems.append(
                f"the {SECTION_NAME} hook code at 0x{tail_va:08x} is not what bit {bit} builds"
            )

        for hook in HOOKS:
            here = bytes(data[_offset(data, hook.va) :][: hook.size])
            if here == hook.original:
                problems.append(f"{hook.note} @0x{hook.va:08x} is unpatched")
                continue
            if here[0] != 0xE9:
                problems.append(
                    f"{hook.note} @0x{hook.va:08x} does not start with a jmp: {here.hex()}"
                )
                continue
            target = hook.va + 5 + struct.unpack_from("<i", here, 1)[0]
            if target != cave.entries[hook.label]:
                problems.append(
                    f"{hook.note} @0x{hook.va:08x} jumps to 0x{target:08x}, but the cave puts "
                    f"{hook.label!r} at 0x{cave.entries[hook.label]:08x}"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """Recover the kindof name from the image: it is the last entry of the cave's own table,
        which is the one parameter this patch has."""
        try:
            located = find_section(data, SECTION_NAME)
            if located is None:
                return None
            section_va = located[0]
            entries = _cave_table_entries(data, section_va)
            name = kind_of.read_cstring(data, _cave_entry(data, section_va, entries - 1))
            if name is None:
                return None
            patch = cls(kindof=name)
            return None if patch.verify(data) else patch
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--kindof",
            default=DEFAULT_KINDOF,
            help=f"name of the kindof to add (default: {DEFAULT_KINDOF})",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(kindof=args.kindof)


def _detour(hook: _Hook, target_va: int) -> bytes:
    """A `jmp rel32` to ``target_va``, padded with `nop` to exactly cover the site."""
    jump = b"\xe9" + struct.pack("<i", target_va - (hook.va + 5))
    return jump + b"\x90" * (hook.size - len(jump))


def _padded(size: int) -> int:
    """``size`` rounded up to a dword, the way :func:`kind_of.layout` pads its name strings."""
    return size + (-size % 4)


def _cave_entry(data: bytes | bytearray, section_va: int, index: int) -> int:
    """One name pointer out of the cave's own copy of the table."""
    return struct.unpack_from("<I", data, _offset(data, section_va) + index * 4)[0]


def _cave_table_entries(data: bytes | bytearray, section_va: int, limit: int = 1024) -> int:
    """How many names the cave's own table holds, found by its NULL terminator.

    Read from the cave rather than from the live table on purpose: the live one is whichever
    kindof-adding patch was applied last, and this patch has to stay verifiable underneath it."""
    off = _offset(data, section_va)
    for index in range(limit):
        if struct.unpack_from("<I", data, off + index * 4)[0] == 0:
            if index == 0:
                raise ValueError(f"the {SECTION_NAME} cave starts with an empty table")
            return index
    raise ValueError(f"the {SECTION_NAME} cave's table is not terminated within {limit} entries")
