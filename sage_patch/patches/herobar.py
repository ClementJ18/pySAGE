"""`HEROBAR` - a kindof that puts an object on the hero bar without making it a `HERO`.

Two shapes, one patch.

**Membership**, the default, is the whole feature for most callers: a `HEROBAR` object joins the
hero bar and nothing else about it changes. It is *not* a `HERO`, so nothing that asks "is this a
hero" - armour, targeting, the AI, scripts, `ExcludedKindOf` lists - answers differently. It gets
a slot of its own, drawn with the rank, health, highlight and flash every other slot has, and
clicking it selects it. Three hooks, no runtime state, and a read-execute cave.

**Grouping**, `--grouped`, adds slot sharing on top: every instance of one `ThingTemplate`
occupies **one** slot, that slot draws **how many members the group has** where a hero's slot
draws its rank, and clicking it selects the members **one at a time** - click again for the next
one, the way `PORTER` steps through porters. It is still not what `PORTER` does: `PORTER` collapses
every porter into a **single** slot whatever template it came from, so its grouping key is nothing
at all where this one is the template.

Why the grouped half is small
-----------------------------
The hero bar already has the shape it needs, for porters, and almost all of it is generic:

* the slot cache is `0x18` bytes x 16 at `bar+0x48`, and `slot+0x16` is a **"this slot is a
  group" byte** that the click handler at `0x0092DBD6` already reads and dispatches on;
* a group slot is drawn with the *same* ActionScript calls as a hero slot, so nothing about the
  `.apt` movie changes;
* `KindOfMaskType` has two free bits, so the kindof itself costs no data growth (see
  :mod:`.kind_of`).

So this patch adds no drawing code at all. Both modes put `HEROBAR` objects on the **hero list** -
the one the draw loop already walks, sorted, slot by slot - and grouping then does four small
things around that loop: reset a per-pass set of templates before it starts, skip a node whose
template has already been drawn this pass, mark the slot it did draw as a group, and hand the
engine a member count where it was about to draw a rank. The engine draws the representative; the
duplicates simply never reach a slot.

The hooks, all five-to-seven-byte detours:

===========  ==========================  ===========  =========================================
site         engine function             mode         what the detour adds
===========  ==========================  ===========  =========================================
`0x0092CD7F` `onObjectAdded`             both         `HEROBAR` joins `HERO` on the way to the
                                                      hero list
`0x0092C439` `onObjectRemoved` gate      both         `HEROBAR` is a thing this function accepts
`0x0092C467` `onObjectRemoved` list      both         ...and removes from the hero list
`0x0092D36F` draw-loop preheader         `--grouped`  clear the per-pass template set
`0x0092D3EE` draw loop, per node         `--grouped`  skip a drawn template; mark and count it
`0x0092DBD6` click dispatch              `--grouped`  a `2` in `slot+0x16` means "step the group"
===========  ==========================  ===========  =========================================

Plus one edit that is not a detour: `0x0092BF4E`, in the hover handler, which reads the same
`slot+0x16` byte as a flag and would otherwise give a group the porter's *"select nearest unit"*
tooltip. Two bytes, `--grouped` only - see :data:`TOOLTIP_EDIT`.

The removal pair is not optional bookkeeping in either mode: without it a dead `HEROBAR` object's
node stays on the hero list forever, because the stock gate accepts only `HERO` and `PORTER`.

The count badge
---------------
A `PORTER` slot shows how many porters there are; a group slot here shows how many members the
group has, and it costs no drawing code either. The number a hero slot draws is a single local,
`[ebp-0x18]`, filled by the call at `0x0092D3AF` and then read three times - compared against the
slot's cached number, formatted with the same wide `"%d"` at `0x00BDF1B0` the porter count uses,
and cached. **All three of those reads happen after the `per_node` hook**, and the two reads that
feed the level-up flash happen before it, so writing the count into that local is the entire badge:
the rank still drives the flash, and the engine's own "has the number changed" test repaints the
slot exactly when the count does.

The count is not knowable when the representative is drawn, because its duplicates come later in
the same pass. So the hook walks the rest of the list itself, applying the same two tests the draw
loop applies to each node - `findObjectByID`, then the eligibility gate at `0x0092BBEF` - and
counts the matches. Starting at the current node inclusive is exact: any earlier node of this
template would have become the representative instead of this one.

That walk is the badge's only real cost, and it is per drawn group per pass rather than per node.
Past the sixteenth distinct template the per-pass set is full, and that path skips the count as
well as the recording - a slot the engine is drawing ungrouped keeps the rank it was going to
draw, rather than a count that would not match what the bar shows.

Stepping a group
----------------
`PORTER`'s cycle keeps its cursor on the bar object - one "a cycle is in progress" byte and one
frame stamp, for the single group the stock engine can have. There is no room there for one cursor
per template, so this keeps its own: **16 dwords in the cave, indexed by slot, each holding the
`ObjectID` this patch last selected out of that slot**. A click walks the hero list once and takes
the first eligible member *after* that `ObjectID`, falling back to the first member when the
cursor names nobody still on the list - which is what a fresh slot, a dead unit and a wrap-around
all look like. Selection is then the engine's own single-object idiom, so a stepped member ends up
selected exactly as clicking a hero's slot selects a hero.

An `ObjectID` rather than a node pointer, because the cursor outlives the object it names: nothing
runs when a group member dies, and a stale pointer would be dereferenced where a stale ID is
simply not found.

**Click again to jump.** A second click on the same slot, soon enough after the first, means "take
me there" rather than "next one": it centres the camera on the member the previous click selected
and leaves the cursor alone. "Soon enough" is `--jump-window` milliseconds, :data:`500
<DEFAULT_JUMP_WINDOW>` by default, scaled to logic frames at runtime with the engine's own `.data`
float and `_ftol`. `--jump-window 0` turns the gesture off and leaves every click a step.

Why it is a constant of this patch's own, and not the engine's. The obvious value to share is
`SelectNearestBuilderCycleTimeOut` (`TheInGameUI+0x988`), which is what the porter's own repeat
test uses, and an earlier version took it by calling the engine routine at `0x0092BA91`. Two
things were wrong with that:

* **It is the wrong quantity.** 3500 ms on this data - a reasonable length for a porter *round* to
  stay open, and about seven times too long for "was that a double click". A gesture window and a
  round timeout are different things that happen to be read by similar-looking comparisons.
* **It is not at a fixed address.** That routine *stores* its answer in `bar+0x1DC`, past the slot
  array, which `hero-bar-slots` slides up by `(count-16)*0x18`. On a 25-slot bar the cave was
  reading byte `0x14` of slot 16 for a deadline - and stomping the porter's real field, at
  `bar+0x2B4`, on the way past.

So the window is a word in the cave and the scaling is re-emitted. Nothing here reads the bar
object past the slot array, which is what keeps this patch and `hero-bar-slots` independent in
either order.

The mouse button is not available here to do this the obvious way. `_OnBttnHeroSelect` is called
*by the movie*, with the button's path (`"Hero3"`) as its only argument, and the APT runtime's
event vocabulary is Flash's - `onPress`, `onRelease`, `onReleaseOutside`, `onRollOver`, `onRollOut`,
`onMouseWheel`, interned at `0x00B20E40`. There is no right-button event anywhere on that path, so
"left selects, right jumps" cannot be told apart at this hook; a repeat click can.

Known limits, stated rather than discovered
-------------------------------------------
* **A group shows its member count where a hero shows a rank**, the way a `PORTER` slot does, and
  a group of one therefore shows `1`. That is not a separate feature: grouping and the badge are
  the same thing seen twice, so `--grouped` carries both.
* **The veteran member's rank is not readable from the bar** once the number is a count. The
  health bar and the rank progress ring still come from the representative.
* **A repeat click always centres, where the porter only centres what is off screen.** The porter
  cycle asks `0x0092BB2A` whether the object is already visible and skips the camera if it is.
  Here the second click *is* the request, so it moves the camera either way.
* **The bar is still 16 slots** unless `hero-bar-slots` widens it. Groups consume slots, so enough
  distinct `HEROBAR` templates in play push heroes off the end - the stock `buttonIndex >= 0x11`
  break at `0x0092D3E5`, which drops them silently rather than crashing. Past slot 16 the per-pass
  set and the cursor table both clamp: grouping and stepping degrade, nothing corrupts.
* **`HERO` and `HEROBAR` are not exclusive.** The classifier tests `HERO` first, but both arms
  end on the same list, and the draw hook asks only whether the template is `HEROBAR` - so a
  template carrying both is a hero *and* groups with its own kind.
* **A template with no hero-bar button image is dropped** by `addHero`, in both modes, exactly as
  a `HERO` without one is.
* **Derived statically, then run in a game** - except the step-through cycle, which replaced a
  select-the-whole-group click and has not been run. See ``../docs/herobar.md``.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, EnumDelta

from ..asm import JAE, JE, JNE, JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import apply_byte_patch, find_section
from .utils import kind_of
from .utils.name_tables import offset as _offset

__all__ = [
    "DEFAULT_JUMP_WINDOW",
    "DEFAULT_KINDOF",
    "GROUPING_HOOKS",
    "MAX_JUMP_WINDOW",
    "HOOKS",
    "MEMBERSHIP_HOOKS",
    "SECTION_CHARACTERISTICS",
    "SECTION_NAME",
    "STATE_SIZE",
    "TOOLTIP_EDIT",
    "UNGROUPED_CHARACTERISTICS",
    "Cave",
    "HeroBarPatch",
    "build_cave",
    "hooks",
    "state_size",
]

SECTION_NAME = ".hbar"

#: `CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE`, for `--grouped`. That
#: cave holds the rebuilt name table, the new name, the hook code *and* the scratch words the draw
#: and click hooks write, and a section carries one set of page permissions for all of it.
SECTION_CHARACTERISTICS = 0xE0000060

#: What a membership-only cave asks for instead: read-execute. It keeps no runtime state, so a
#: writable cave would be a page permission granted for nothing.
UNGROUPED_CHARACTERISTICS = kind_of.SECTION_CHARACTERISTICS

DEFAULT_KINDOF = "HEROBAR"

#: How long after a click a second one still means "take me there", in milliseconds, and the
#: ceiling `--jump-window` accepts. 500 is what Windows itself calls a double click, and it is a
#: gesture window rather than a timeout: the engine's own `SelectNearestBuilderCycleTimeOut` is
#: 3500 on this data, but that number says how long a porter *round* stays open, which is a
#: different quantity that happens to be read by a similar-looking comparison. `0` turns the jump
#: off and leaves every click a step.
DEFAULT_JUMP_WINDOW = 500
MAX_JUMP_WINDOW = 60_000

#: `KindOfMaskType` bit 90. Tested inline as `test byte [tmpl+0x113], 4` wherever the engine asks
#: "is this a hero", which is the encoding :func:`kind_of.bit_test` reproduces.
HERO_BIT = 90

#: ModRM r/m encodings, for the register a `bit_test` reads the template through.
_EAX, _ECX, _ESI = 0, 1, 6

THE_GAME_LOGIC = 0x00DE412C
THE_IN_GAME_UI = 0x00DE4830
THE_MESSAGE_STREAM = 0x00DE6398
THE_GAME_CLIENT = 0x00DE4388
THE_TACTICAL_VIEW = 0x00DE447C

FIND_OBJECT_BY_ID = 0x00449681  # thiscall(TheGameLogic, ObjectID) -> Object*, ret 4
OBJECT_GET_DRAWABLE = 0x0070E013  # thiscall(Object) -> Drawable*, ret 0
APPEND_BOOLEAN_ARGUMENT = 0x00711104  # thiscall(GameMessage, bool), ret 4
APPEND_OBJECT_ID_ARGUMENT = 0x0071111A  # thiscall(GameMessage, ObjectID), ret 4
BAR_ACCEPTS_OBJECT = 0x0092BBEF  # (Object*) -> bool: local player && !NO_HERO_PROPERTIES, ret 4
DRAWABLE_POSITION = 0x00676711  # thiscall(Drawable) -> Coord3D*, ret 0
#: MSVC's `_ftol`: truncates `st(0)` into `eax`, no stack arguments, pops the value.
FTOL = 0x00A3CFA4

#: `TheInGameUI` vtable slots, as the hero bar's own click path uses them.
UI_DESELECT_ALL = 0x110
UI_SELECT_DRAWABLE = 0x108
#: `TheGameClient::getFrame()`, and `TheTacticalView::lookAt(Coord3D*)`.
CLIENT_FRAME = 0x7C
VIEW_LOOK_AT = 0x54
#: The millisecond-to-logic-frame factor the engine scales its own window by at `0x0092BAB3`.
#: Read at runtime rather than folded in here, because it is a `.data` word rather than a literal.
MSEC_TO_FRAMES = 0x00D9F624
#: `TheMessageStream::appendMessage(GameMessageType) -> GameMessage*`.
STREAM_APPEND_MESSAGE = 0x48
#: The message the hero bar's single-object click raises: a boolean, then the `ObjectID`s.
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

#: Within an `Object`: its `ThingTemplate` and its `ObjectID`. Within a hero-list node: the
#: `ObjectID` that node names.
OBJECT_TEMPLATE = 0x04
OBJECT_ID = 0x74
NODE_OBJECT_ID = 0x08

#: The draw loop reaches its per-node hook with the slot pointer already biased by 4, so the
#: group byte is at `edi + 0x12` and the node it is replacing is at `edi - 4`.
_EDI_SLOT_BIAS = 4


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


#: What every mode installs: how a `HEROBAR` object reaches the bar, and how it leaves again.
MEMBERSHIP_HOOKS = (
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
)

#: What `--grouped` adds: which nodes reach a slot, and what a click on one of them does.
GROUPING_HOOKS = (
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
        "click dispatch: step through the group",
    ),
)

HOOKS = MEMBERSHIP_HOOKS + GROUPING_HOOKS


@dataclass(frozen=True)
class _Edit:
    """An in-place rewrite: no cave, no detour, just different bytes at a known address."""

    va: int
    original: bytes
    patched: bytes
    note: str


#: The hover handler at `0x0092BF34` picks a tooltip off the *same* `slot+0x16` byte the click
#: dispatches on, and it reads that byte as a flag rather than as a kind: `cmp ..., 0 ; je` sends
#: **every** non-zero value down the porter arm, which looks up the command button named
#: `NonCommand_SelectNearestBuilder` and shows its "select nearest unit" text. A `2` therefore
#: inherits the porter's tooltip along with its own click behaviour.
#:
#: Narrowing the test to `cmp ..., 1 ; jne` costs two bytes and no cave: `1` still means the porter
#: group, and `0` and `2` both take the arm that builds the tooltip from the slot's own node - which
#: is the representative's object, drawn exactly as a hero's slot draws it. Grouped-only, because
#: nothing writes a `2` without grouping.
TOOLTIP_EDIT = _Edit(
    0x0092BF4E,
    bytes.fromhex("807816007456"),  # cmp byte [eax+0x16], 0 ; je 0x0092BFAA
    bytes.fromhex("807816017556"),  # cmp byte [eax+0x16], 1 ; jne 0x0092BFAA
    "hover: only the porter group gets the 'select nearest unit' tooltip",
)


def hooks(grouped: bool) -> tuple[_Hook, ...]:
    """The detours a mode installs. The three it leaves out are asserted **unpatched** by
    :meth:`HeroBarPatch.verify`, which is what keeps the two modes distinguishable in a binary."""
    return HOOKS if grouped else MEMBERSHIP_HOOKS


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

#: Scratch words at the head of a `--grouped` cave, in this order: the per-pass template set and
#: its length, the values the click routine carries across the calls it makes, the per-slot cursor
#: table, and the two the badge count needs. Sized to a round `0xC0` so the code that follows
#: starts on a recognisable boundary. A membership-only cave has none of this and opens with its
#: code.
#:
#: The last word is the odd one out: :data:`_OFF_WINDOW_MS` is written by the patcher and only
#: *read* at runtime. It sits here rather than in the code because `fild` wants a memory operand
#: anyway, and because a word at a known offset is what lets :meth:`HeroBarPatch.detect` recover
#: the setting from an image instead of guessing it.
_MAX_SLOTS = 16
STATE_SIZE = 0xC0
_OFF_EMITTED_N = 0x00
_OFF_EMITTED = 0x04  # 16 dwords, 0x04..0x43
_OFF_TEMPLATE = 0x44
_OFF_MESSAGE = 0x48
_OFF_SENTINEL = 0x4C
_OFF_NODE = 0x50
_OFF_SLOT = 0x54
_OFF_LAST = 0x58
_OFF_FIRST = 0x5C
_OFF_CHOSEN = 0x60
_OFF_SEEN = 0x64
_OFF_CURSOR = 0x68  # 16 dwords, 0x68..0xA7
_OFF_COUNT = 0xA8
_OFF_COUNT_TEMPLATE = 0xAC
_OFF_CLICK_SLOT = 0xB0  # the last clicked slot, biased by 1 so that 0 means "none yet"
_OFF_CLICK_DEADLINE = 0xB4
_OFF_WINDOW_MS = 0xB8  # written once by the patcher; the only word here the game never writes


def state_size(grouped: bool) -> int:
    """How many bytes of scratch the cave opens with. Grouping keeps runtime state; membership
    keeps none, which is also why its cave asks for no `MEM_WRITE`."""
    return STATE_SIZE if grouped else 0


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


def build_cave(
    base_va: int,
    bit: int,
    grouped: bool = False,
    jump_window: int = DEFAULT_JUMP_WINDOW,
) -> Cave:
    """One mode's hook routines - and, for ``grouped``, the scratch words they use - at
    ``base_va``.

    Deterministic: :meth:`HeroBarPatch.apply` and :meth:`HeroBarPatch.verify` build the same
    bytes from the same ``(base_va, bit, grouped, jump_window)`` and compare them, which is what
    makes verification possible without a disassembler."""
    emitted_n = base_va + _OFF_EMITTED_N
    emitted = base_va + _OFF_EMITTED
    template = base_va + _OFF_TEMPLATE
    message = base_va + _OFF_MESSAGE
    sentinel = base_va + _OFF_SENTINEL
    node = base_va + _OFF_NODE
    slot = base_va + _OFF_SLOT
    last = base_va + _OFF_LAST
    first = base_va + _OFF_FIRST
    chosen = base_va + _OFF_CHOSEN
    seen = base_va + _OFF_SEEN
    cursor = base_va + _OFF_CURSOR
    count = base_va + _OFF_COUNT
    count_template = base_va + _OFF_COUNT_TEMPLATE
    click_slot = base_va + _OFF_CLICK_SLOT
    click_deadline = base_va + _OFF_CLICK_DEADLINE
    window_ms = base_va + _OFF_WINDOW_MS

    is_hero = kind_of.bit_test(HERO_BIT, _EAX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_eax = kind_of.bit_test(bit, _EAX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_ecx = kind_of.bit_test(bit, _ECX, kind_of.THING_TEMPLATE_MASK_OFFSET)
    is_herobar_esi = kind_of.bit_test(bit, _ESI, kind_of.THING_TEMPLATE_MASK_OFFSET)

    a = Asm(base_va + state_size(grouped))

    # classify: eax = ThingTemplate, edx = Object.
    # The stock code is `HERO ? addHero : PORTER ? addPorter`. This makes the first arm
    # `HERO || HEROBAR` by re-testing both bits and re-entering at whichever arm won, so neither
    # the `je` nor the two calls the engine already has need touching.
    a.label("classify")
    a.emit(is_hero).jcc(JNZ, "classify_hero")
    a.emit(is_herobar_eax).jcc(JNZ, "classify_hero")
    a.jmp_absolute(_CLASSIFY_PORTER)
    a.label("classify_hero").jmp_absolute(_CLASSIFY_HERO)

    # remove_gate: eax = ThingTemplate, edi = the HERO bit within dword 2.
    # Both removal hooks end by falling into the engine's own branch, so what they have to get
    # right is the flags, not a target: the last `test` executed is the one the engine reads.
    a.label("remove_gate")
    a.emit(bytes.fromhex("85b810010000")).jcc(JZ, "remove_gate_herobar")  # test [eax+0x110],edi
    a.jmp_absolute(_REMOVE_GATE_RESUME)
    a.label("remove_gate_herobar").emit(is_herobar_eax).jmp_absolute(_REMOVE_GATE_RESUME)

    # remove_list: esi = ThingTemplate, edi = the HERO bit.
    a.label("remove_list")
    a.emit(bytes.fromhex("85be10010000")).jcc(JZ, "remove_list_herobar")  # test [esi+0x110],edi
    a.jmp_absolute(_REMOVE_LIST_RESUME)
    a.label("remove_list_herobar").emit(is_herobar_esi).jmp_absolute(_REMOVE_LIST_RESUME)

    if not grouped:
        return Cave(
            content=a.finish(),
            entries={hook.label: a.label_va(hook.label) for hook in MEMBERSHIP_HOOKS},
        )

    # pass_reset: the loop preheader, run once per draw pass.
    a.label("pass_reset")
    a.emit(_abs_mem(bytes.fromhex("8325"), emitted_n), 0x00)  # and dword [emitted_n], 0
    a.emit(bytes.fromhex("8b45dc"))  # mov eax, [ebp-0x24]   (the displaced pair)
    a.emit(bytes.fromhex("8d4801"))  # lea ecx, [eax+1]
    a.jmp_absolute(_PASS_RESET_RESUME)

    # per_node: ebx = list node, edi = slot+4, [ebp-0x20] = Object.
    # Runs after the engine's own eligibility and slot-ceiling checks, so a node that reaches
    # here is one the engine was about to draw. Jumping to the engine's "next node" label skips
    # it *without* consuming the slot, which is exactly what a duplicate needs.
    a.label("per_node")
    a.emit(bytes.fromhex("505152"))  # push eax ; push ecx ; push edx
    a.emit(bytes.fromhex("8b4de0"))  # mov ecx, [ebp-0x20]   -> Object
    a.emit(bytes.fromhex("8b49"), OBJECT_TEMPLATE)  # mov ecx, [ecx+4] -> ThingTemplate
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

    # The badge. `[ebp-0x18]` is the number the engine is about to draw on this slot - the
    # representative's rank, already resolved by the call at `0x0092D3AF` and not read again until
    # after this hook returns. Overwriting it with the member count is the whole of the badge: the
    # engine's own "did the number change" test then repaints the slot exactly when the count does,
    # through the same text write the porter count uses.
    #
    # The count is not knowable when the representative is drawn - its duplicates come later in the
    # same pass - so this walks the rest of the list and applies the two tests the draw loop itself
    # applies, `findObjectByID` and the eligibility gate. Starting at `ebx` inclusive is exact: any
    # earlier node of this template would have become the representative instead of this one.
    a.emit(_abs_mem(bytes.fromhex("890d"), count_template))  # mov [count_template], ecx
    a.emit(_abs_mem(bytes.fromhex("8325"), count), 0x00)  # and dword [count], 0
    a.emit(bytes.fromhex("8bd3"))  # mov edx, ebx

    a.label("per_node_count")
    a.emit(bytes.fromhex("8b45c4"))  # mov eax, [ebp-0x3c]  -> &the list head
    a.emit(bytes.fromhex("3b10")).jcc(JE, "per_node_counted")  # cmp edx, [eax]
    a.emit(bytes.fromhex("52"))  # push edx              (the walker, across the calls)
    a.emit(bytes.fromhex("ff72"), NODE_OBJECT_ID)  # push dword [edx+8]
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)  # ret 4
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "per_node_count_next")
    a.emit(bytes.fromhex("8b48"), OBJECT_TEMPLATE)  # mov ecx, [eax+4]
    a.emit(_abs_mem(bytes.fromhex("3b0d"), count_template)).jcc(JNE, "per_node_count_next")
    a.emit(bytes.fromhex("50"))  # push eax
    a.call_absolute(BAR_ACCEPTS_OBJECT)  # ret 4
    a.emit(bytes.fromhex("84c0")).jcc(JZ, "per_node_count_next")  # test al, al
    a.emit(_abs_mem(bytes.fromhex("ff05"), count))  # inc dword [count]

    a.label("per_node_count_next")
    a.emit(bytes.fromhex("5a"))  # pop edx
    a.emit(bytes.fromhex("8b12")).jmp("per_node_count")  # mov edx, [edx]

    a.label("per_node_counted")
    a.emit(_abs_mem(bytes.fromhex("a1"), count))  # mov eax, [count]
    a.emit(bytes.fromhex("8945e8"))  # mov [ebp-0x18], eax   -> the number the slot draws

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

    # click: eax = slot index, ecx = index*0x18, esi = the bar.
    # Three-way instead of the stock two-way. Reading the byte twice rather than caching it in a
    # register keeps every register the two stock arms expect exactly as they expect it.
    a.label("click")
    a.emit(bytes.fromhex("807c315e"), GROUPED_HEROBAR).jcc(JE, "click_group")
    a.emit(bytes.fromhex("807c315e"), 0x00).jcc(JNE, "click_porter")
    a.jmp_absolute(_CLICK_SINGLE)
    a.label("click_porter").jmp_absolute(_CLICK_PORTER)

    # click_group: select the member after the one this slot selected last.
    a.label("click_group")
    a.emit(_abs_mem(bytes.fromhex("a3"), slot))  # mov [slot], eax
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
    a.emit(bytes.fromhex("ff77"), NODE_OBJECT_ID)  # push dword [edi+8]
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_done")
    a.emit(bytes.fromhex("8b40"), OBJECT_TEMPLATE)  # mov eax, [eax+4] -> ThingTemplate
    a.emit(_abs_mem(bytes.fromhex("a3"), template))  # mov [template], eax

    # The pick, in three words: the first eligible member (where a click wraps to), the one after
    # the cursor (what this click wants), and whether the cursor has been passed yet. All four are
    # cleared per click, the cursor last because a slot past the sixteenth has none to load.
    for word in (first, chosen, seen, last):
        a.emit(_abs_mem(bytes.fromhex("8325"), word), 0x00)  # and dword [word], 0
    a.emit(_abs_mem(bytes.fromhex("a1"), slot))  # mov eax, [slot]
    a.emit(bytes.fromhex("83f8"), _MAX_SLOTS).jcc(JAE, "click_scan")  # cmp eax, 16
    a.emit(_abs_mem(bytes.fromhex("8b0485"), cursor))  # mov eax, [cursor + eax*4]
    a.emit(_abs_mem(bytes.fromhex("a3"), last))  # mov [last], eax

    # A second click on the same slot, inside the window the porter cycle uses for exactly this
    # question, means "take me there" rather than "next one": centre the camera on the member the
    # previous click selected and leave the cursor where it is. Anything else - a different slot,
    # a slow click, a member that has died since - falls through and steps.
    a.emit(_abs_mem(bytes.fromhex("a1"), slot))  # mov eax, [slot]
    a.emit(bytes.fromhex("40"))  # inc eax               (0 means "no slot yet")
    a.emit(_abs_mem(bytes.fromhex("3b05"), click_slot)).jcc(JNE, "click_scan")
    a.emit(_abs_mem(bytes.fromhex("833d"), last), 0x00).jcc(JE, "click_scan")  # cmp [last], 0
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_CLIENT))
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("ff50"), CLIENT_FRAME)  # call [eax+0x7c]  -> the frame now
    a.emit(_abs_mem(bytes.fromhex("3b05"), click_deadline)).jcc(JAE, "click_scan")

    a.emit(_abs_mem(bytes.fromhex("ff35"), last))  # push dword [last]   (the ObjectID)
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_scan")  # gone since: step instead
    a.emit(bytes.fromhex("8bc8"))  # mov ecx, eax
    a.call_absolute(OBJECT_GET_DRAWABLE)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_done")
    a.emit(bytes.fromhex("8bc8"))  # mov ecx, eax          (the Drawable)
    a.call_absolute(DRAWABLE_POSITION)  # -> Coord3D*
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_TACTICAL_VIEW))
    a.emit(bytes.fromhex("8b11"))  # mov edx, [ecx]        (the vtable, read after the call)
    a.emit(bytes.fromhex("50"))  # push eax
    a.emit(bytes.fromhex("ff52"), VIEW_LOOK_AT)  # call [edx+0x54]
    a.jmp("click_done")

    a.label("click_scan")
    a.emit(_abs_mem(bytes.fromhex("8b0d"), sentinel))  # mov ecx, [sentinel]
    a.emit(bytes.fromhex("8b39"))  # mov edi, [ecx]
    a.label("click_loop")
    a.emit(_abs_mem(bytes.fromhex("3b3d"), sentinel)).jcc(JE, "click_pick")
    a.emit(bytes.fromhex("ff77"), NODE_OBJECT_ID)  # push dword [edi+8]
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_LOGIC))
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_next")
    a.emit(bytes.fromhex("8b48"), OBJECT_TEMPLATE)  # mov ecx, [eax+4]
    a.emit(_abs_mem(bytes.fromhex("3b0d"), template)).jcc(JNE, "click_next")

    a.emit(bytes.fromhex("50"))  # push eax              (keep the Object)
    a.emit(bytes.fromhex("50"))  # push eax              (the argument)
    a.call_absolute(BAR_ACCEPTS_OBJECT)  # ret 4
    a.emit(bytes.fromhex("59"))  # pop ecx               -> the Object again
    a.emit(bytes.fromhex("84c0")).jcc(JZ, "click_next")  # test al, al

    a.emit(_abs_mem(bytes.fromhex("833d"), first), 0x00).jcc(JNE, "click_after")  # cmp [first],0
    a.emit(_abs_mem(bytes.fromhex("890d"), first))  # mov [first], ecx

    a.label("click_after")
    a.emit(_abs_mem(bytes.fromhex("833d"), seen), 0x00).jcc(JE, "click_cursor")  # cmp [seen], 0
    a.emit(_abs_mem(bytes.fromhex("890d"), chosen))  # mov [chosen], ecx
    a.jmp("click_pick")

    a.label("click_cursor")
    a.emit(bytes.fromhex("8b41"), OBJECT_ID)  # mov eax, [ecx+0x74]
    a.emit(_abs_mem(bytes.fromhex("3b05"), last)).jcc(JNE, "click_next")  # cmp eax, [last]
    a.emit(_abs_mem(bytes.fromhex("c705"), seen), _u32(1))  # mov dword [seen], 1

    a.label("click_next")
    a.emit(bytes.fromhex("8b3f")).jmp("click_loop")  # mov edi, [edi]

    # Nothing after the cursor means the cursor was the last member, or names nobody at all: both
    # wrap to the first. No first member means the group is empty and there is nothing to select.
    a.label("click_pick")
    a.emit(_abs_mem(bytes.fromhex("8b0d"), chosen))  # mov ecx, [chosen]
    a.emit(bytes.fromhex("85c9")).jcc(JNZ, "click_select")  # test ecx, ecx
    a.emit(_abs_mem(bytes.fromhex("8b0d"), first))  # mov ecx, [first]
    a.emit(bytes.fromhex("85c9")).jcc(JZ, "click_done")

    a.label("click_select")
    a.emit(bytes.fromhex("8b41"), OBJECT_ID)  # mov eax, [ecx+0x74]
    a.emit(_abs_mem(bytes.fromhex("8b15"), slot))  # mov edx, [slot]
    a.emit(bytes.fromhex("83fa"), _MAX_SLOTS).jcc(JAE, "click_message")  # cmp edx, 16
    a.emit(_abs_mem(bytes.fromhex("890495"), cursor))  # mov [cursor + edx*4], eax

    a.label("click_message")
    a.emit(bytes.fromhex("51"))  # push ecx              (keep the Object)

    # Remember which slot this click landed on and when a second one stops counting as a repeat.
    # The window is `jump_window` milliseconds, scaled to logic frames the way the engine scales
    # its own at `0x0092BAA4` - `fild`, the same `.data` float, the same `_ftol`.
    #
    # It is a constant of this patch's own rather than the engine's
    # `SelectNearestBuilderCycleTimeOut`, which an earlier version read through
    # `0x0092BA91`. Two things were wrong with that. It is 3500 ms on this data, which is a
    # sensible length for a porter *round* and far too long for "was that a double click"; and
    # the routine stores its answer in `bar+0x1DC`, a field past the slot array that
    # `hero-bar-slots` slides up - so on a widened bar the cave read a slot's cached bytes for a
    # deadline, and stomped the porter's real field on the way. Reading nothing off the bar keeps
    # the two patches independent in either order.
    a.emit(_abs_mem(bytes.fromhex("a1"), slot))  # mov eax, [slot]
    a.emit(bytes.fromhex("40"))  # inc eax
    a.emit(_abs_mem(bytes.fromhex("a3"), click_slot))  # mov [click_slot], eax
    a.emit(_abs_mem(bytes.fromhex("db05"), window_ms))  # fild dword [window_ms]
    a.emit(_abs_mem(bytes.fromhex("d80d"), MSEC_TO_FRAMES))  # fmul dword [msec -> frames]
    a.call_absolute(FTOL)  # -> eax, the window in frames
    a.emit(_abs_mem(bytes.fromhex("a3"), click_deadline))  # mov [click_deadline], eax
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_GAME_CLIENT))
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("ff50"), CLIENT_FRAME)  # call [eax+0x7c]  -> the frame now
    a.emit(_abs_mem(bytes.fromhex("0305"), click_deadline))  # add eax, [click_deadline]
    a.emit(_abs_mem(bytes.fromhex("a3"), click_deadline))  # mov [click_deadline], eax

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

    a.emit(bytes.fromhex("59"))  # pop ecx               -> the Object again
    a.emit(bytes.fromhex("51"))  # push ecx
    a.emit(bytes.fromhex("ff71"), OBJECT_ID)  # push dword [ecx+0x74]
    a.emit(_abs_mem(bytes.fromhex("8b0d"), message))
    a.call_absolute(APPEND_OBJECT_ID_ARGUMENT)  # ret 4
    a.emit(bytes.fromhex("59"))  # pop ecx
    a.call_absolute(OBJECT_GET_DRAWABLE)  # -> eax
    a.emit(bytes.fromhex("85c0")).jcc(JZ, "click_done")
    a.emit(_abs_mem(bytes.fromhex("8b0d"), THE_IN_GAME_UI))
    a.emit(bytes.fromhex("50"))  # push eax              (the Drawable)
    a.emit(bytes.fromhex("8b01"))  # mov eax, [ecx]
    a.emit(bytes.fromhex("ff90"), _u32(UI_SELECT_DRAWABLE))  # call [eax+0x108]

    a.label("click_done").jmp_absolute(_CLICK_DONE)

    code = a.finish()
    state = bytearray(STATE_SIZE)
    struct.pack_into("<I", state, _OFF_WINDOW_MS, jump_window)
    return Cave(
        content=bytes(state) + code,
        entries={hook.label: a.label_va(hook.label) for hook in HOOKS},
    )


@dataclass
class HeroBarPatch(Patch):
    """Add a `HEROBAR` kindof: a hero-bar slot for an object that is not a `HERO`."""

    name = "herobar"
    author = "officialNecro"
    description = (
        "add a HEROBAR kindof: an object gets a hero-bar slot without being a HERO; --grouped "
        "shares one slot between every instance of a template and steps through them on click"
    )

    kindof: str = DEFAULT_KINDOF
    grouped: bool = False
    jump_window: int = DEFAULT_JUMP_WINDOW

    def __post_init__(self) -> None:
        if not 0 <= self.jump_window <= MAX_JUMP_WINDOW:
            raise ValueError(
                f"jump-window must be in 0..{MAX_JUMP_WINDOW} milliseconds, "
                f"got {self.jump_window}"
            )

    def _cave(self, base_va: int, bit: int) -> Cave:
        return build_cave(base_va, bit, self.grouped, self.jump_window)

    def apply(self, data: bytearray) -> None:
        extension = kind_of.extend(
            data,
            SECTION_NAME,
            [self.kindof],
            tail=lambda tail_va, bits: self._cave(tail_va, bits[0]).content,
            characteristics=(
                SECTION_CHARACTERISTICS if self.grouped else UNGROUPED_CHARACTERISTICS
            ),
        )
        cave = self._cave(extension.tail_va, extension.bits[0])
        for hook in hooks(self.grouped):
            apply_byte_patch(
                data,
                _offset(data, hook.va),
                hook.original,
                _detour(hook, cave.entries[hook.label]),
                f"{hook.note} @0x{hook.va:08x}",
            )
        if self.grouped:
            apply_byte_patch(
                data,
                _offset(data, TOOLTIP_EDIT.va),
                TOOLTIP_EDIT.original,
                TOOLTIP_EDIT.patched,
                f"{TOOLTIP_EDIT.note} @0x{TOOLTIP_EDIT.va:08x}",
            )

    def ini_surface(self) -> Engine:
        """The one token this patch teaches the INI parser, as a `KindOf` member.

        No index is stated: which bit the name lands on depends on what else the binary already
        carries, so the generator reads it back from the live table instead."""
        return Engine(enum_members=(EnumDelta(enum="KindOf", name=self.kindof, patch=self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch, for this kindof name and this mode.

        Reads only via ``struct`` and the section table. Both the bit and the end of the table
        come from **the cave's own copy**, never from the live one: a second kindof-adding patch
        becomes the live table and shifts nothing about this one, and this patch is still
        correctly installed. The live table is consulted only to confirm it still agrees.

        The hooks a mode does *not* install are checked to still hold their stock bytes, which is
        what makes the two modes tell each other apart rather than one verifying the other's
        binary."""
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
        cave = self._cave(tail_va, bit)
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
            mode = "--grouped" if self.grouped else "membership-only"
            window = f" with a {self.jump_window}ms jump window" if self.grouped else ""
            problems.append(
                f"the {SECTION_NAME} hook code at 0x{tail_va:08x} is not what bit {bit} builds "
                f"for a {mode} patch{window}"
            )

        here = bytes(data[_offset(data, TOOLTIP_EDIT.va) :][: len(TOOLTIP_EDIT.patched)])
        wanted = TOOLTIP_EDIT.patched if self.grouped else TOOLTIP_EDIT.original
        if here != wanted:
            problems.append(
                f"{TOOLTIP_EDIT.note} @0x{TOOLTIP_EDIT.va:08x}: expected {wanted.hex()}, "
                f"got {here.hex()}"
            )

        installed = hooks(self.grouped)
        for hook in HOOKS:
            here = bytes(data[_offset(data, hook.va) :][: hook.size])
            if hook not in installed:
                if here != hook.original:
                    problems.append(
                        f"{hook.note} @0x{hook.va:08x} is detoured, which only the --grouped "
                        "patch does"
                    )
                continue
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
        """Recover every parameter from the image: the kindof name is the last entry of the cave's
        own table, the window is the word the patcher left at :data:`_OFF_WINDOW_MS`, and the mode
        is whichever of the two the cave's code then turns out to be.

        The window is *read* rather than searched for because `verify` compares whole cave bytes:
        a value guessed wrong would fail verification with nothing to say which of the two the
        binary disagreed about."""
        try:
            located = find_section(data, SECTION_NAME)
            if located is None:
                return None
            section_va = located[0]
            entries = _cave_table_entries(data, section_va)
            name = kind_of.read_cstring(data, _cave_entry(data, section_va, entries - 1))
            if name is None:
                return None
            membership = cls(kindof=name)
            if not membership.verify(data):
                return membership
            # Only a grouped cave has a state block at all, so the window word is read *after* the
            # membership mode has been ruled out - on a membership cave that offset is past the
            # section entirely.
            tail_va = section_va + entries * 4 + 4 + _padded(len(name) + 1)
            window = struct.unpack_from("<I", data, _offset(data, tail_va + _OFF_WINDOW_MS))[0]
            if 0 <= window <= MAX_JUMP_WINDOW:
                grouped = cls(kindof=name, grouped=True, jump_window=window)
                if not grouped.verify(data):
                    return grouped
            return None
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--kindof",
            default=DEFAULT_KINDOF,
            help=f"name of the kindof to add (default: {DEFAULT_KINDOF})",
        )
        parser.add_argument(
            "--grouped",
            action="store_true",
            help="share one slot between every instance of a template, and step through them one "
            "at a time on click (default: no, one slot per object)",
        )
        parser.add_argument(
            "--jump-window",
            type=int,
            default=DEFAULT_JUMP_WINDOW,
            metavar="MS",
            help="--grouped only: how long after a click a second one on the same slot centres "
            f"the camera instead of stepping, in milliseconds, 0..{MAX_JUMP_WINDOW} "
            f"(default: {DEFAULT_JUMP_WINDOW}; 0 turns the jump off)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(kindof=args.kindof, grouped=args.grouped, jump_window=args.jump_window)


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
