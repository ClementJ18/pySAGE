"""`MemoryBackend` - observe a running game read-only, with no injection.

`OpenProcess` + `ReadProcessMemory` and nothing else: no code loaded into the game, no
patched binary, no anti-tamper surface. That makes this the low-risk observation path, and
it is worth keeping permanently even once a bridge exists.

Fetching bytes is separated from interpreting them. Everything below reads through a
`MemorySource`, so the whole decode - pointer chains, string headers, the object table - is
exercised against a synthetic image in the data-free suite, and only `ProcessMemory` needs
a real game. `ctypes` is stdlib, so this module adds no dependency.

**Addresses are build-specific, and `connect` checks the build.** `LAYOUT_ROTWK_201` is
verified against RotWK 2.01 (PE timestamp `0x460DA09E`); the derivation is in
`sage_patch/docs/engine-globals.md` and `sage_patch/docs/live-object-model.md`. Pass a
different `EngineLayout` for another build - and note that reading the *wrong* build with
these offsets never fails, it reports nonsense, which is why `sage_live.backends.identity` gates it.

**An observation costs three reads per additional object**, and that is asserted rather than
hoped for - see `test_an_object_costs_three_reads`. Each `MemorySource.read` is a
`ReadProcessMemory`
syscall, so the per-object count is what decides whether a policy observes a few times a second
or a few dozen. Three is the entry, the object header, and the body: everything else on the
header comes out of the one read, a template's name and Side are cached per template rather
than per object, and a template already known to carry no `ProductionUpdate` skips the module
walk entirely. Averaged over a real 386-object match the figure is about **15**, because a
match holds dozens of distinct templates and each pays once for its strings and its module
walk.

Every wide read has a **field-by-field fallback**, and the two must decode identically. That is
not defensive decoration: an object whose header straddles into an unmapped page fails the wide
read while each field inside it reads perfectly, and a recorded snapshot holds only the ranges
its capture touched. The fallback is also what the batching is measured against - refusing the
wide reads on the same image takes the marginal cost from 3 to 16.

Two limits worth knowing before building on this:

- **Observations are whole-map; the fog filter is a separate, deliberate step.** This reads
  every object, and also reads the engine's own shroud grid into `Observation.shroud`, so
  `Observation.under_fog` (or `attach(fog=True)`) can cut it down to one seat's view. `fogged`
  stays False on what this produces, because what this produces is the whole map.
- **Per-object owner is resolved, but indirectly.** An `Object` names its owner by `Team*`
  (`+0x31C`), and a `Team` holds no back-pointer to its `Player`, so the map is inverted from
  each player's own team (`Player+0x30C`). Objects on a *script* team - a player may own several
  - resolve to None rather than a guess; that was 2 of 523 in a live match. Do not substitute
  `template_side`: it is the *template's* declared Side and genuinely disagrees with ownership
  (the creeps own 18 `Neutral`-sided lairs, and the local player owned a `Civilian`-sided
  object).
- **Upgrades come in two scopes and they are not interchangeable.** Faction-wide researches are
  on the `Player`; per-battalion and per-structure ones are on the `Object` and appear in no
  other field. `upgrade_table` reads the engine's own registry for the names, so this module
  stays free of game data even while reporting them.
"""

from __future__ import annotations

import ctypes
import math
import struct
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sage_live.api.observation import GameObject, Observation, PlayerState, ProductionItem
from sage_live.backends.base import ConnectionRefused, GameExited
from sage_live.backends.identity import ROTWK_201_TIMESTAMP, BuildIdentity, read_identity
from sage_live.backends.protocol import Diagnostic, DiagnosticLog, Handshake
from sage_live.backends.shroud import ShroudGrid, read_shroud
from sage_patch.addresses import (
    BUILD,
    IMAGE_BASE,
    OBJECT_MODULE_LIST,
    OBJECT_PRODUCER_ID,
    OBJECT_STATUS,
    OBJECT_STATUS_COUNT,
    OBJECT_STATUS_DWORDS,
    OBJECT_STATUS_NAMES,
    PRODUCTION_UPDATE_VTABLE,
    SHROUD_CELL_SIZE,
    SHROUD_CELLS,
    SHROUD_CELLS_X,
    SHROUD_CELLS_Y,
    SHROUD_FOG_ENABLED,
    SHROUD_IMPL,
    SHROUD_INV_CELL_SIZE,
    SHROUD_ORIGIN_X,
    SHROUD_ORIGIN_Y,
    THE_GAME_LOGIC,
    THE_MESSAGE_STREAM,
    THE_PLAYER_LIST,
    THE_SHROUD_MANAGER,
    THE_SPECIAL_POWER_STORE,
    THE_THING_FACTORY,
    THE_UPGRADE_CENTER,
)
from sage_patch.patches.utils.model_conditions import MASK_DWORDS as MODEL_CONDITION_DWORDS
from sage_patch.patches.utils.model_conditions import MASK_OFFSET as MODEL_CONDITION_MASK
from sage_patch.patches.utils.model_conditions import NAME_TABLE_VA as MODEL_CONDITION_NAMES
from sage_patch.patches.utils.model_conditions import STOCK_BIT_COUNT as MODEL_CONDITION_COUNT
from sage_replay.replay import Order

__all__ = [
    "LAYOUT_ROTWK_201",
    "EngineLayout",
    "MemoryBackend",
    "MemorySource",
    "ProcessMemory",
    "UpgradeDefinition",
    "find_game_processes",
]

# A pointer outside this range is not a live heap object on 32-bit Windows.
_MIN_PTR = 0x10000
_MAX_PTR = 0x7FFFFFFF

# Guards against walking a corrupt or mid-write table into a multi-second stall.
_MAX_TABLE_SLOTS = 1 << 20


@dataclass(frozen=True)
class EngineLayout:
    """Static addresses and struct offsets for one engine build.

    Defaults are RotWK 2.01 + Edain. Every field here was confirmed against a running
    process, not inferred from shape alone.
    """

    # Which image these offsets are meaningful for, as its PE `TimeDateStamp`. `connect`
    # reads the same number out of the running process and refuses a mismatch, because
    # reading the wrong build with these offsets does not fail - it reports nonsense that
    # looks like data. **0 disables the check**, which is what a layout for an unidentified
    # build should carry: no gate is honest, a wrong gate is not.
    build_timestamp: int = ROTWK_201_TIMESTAMP

    # Subsystem globals come from `sage_patch.addresses`, the single description of this
    # build, so the addresses this reads and the ones the live-bridge cave calls cannot drift.
    the_player_list: int = THE_PLAYER_LIST
    the_game_logic: int = THE_GAME_LOGIC
    the_message_stream: int = THE_MESSAGE_STREAM
    the_upgrade_center: int = THE_UPGRADE_CENTER
    # `TheShroudManager` is a 20-byte facade; the grid lives on the object at `+0x10`. See
    # `sage_live.backends.shroud` for the model and how it was recovered.
    the_shroud_manager: int = THE_SHROUD_MANAGER
    shroud_impl: int = SHROUD_IMPL
    shroud_origin_x: int = SHROUD_ORIGIN_X
    shroud_origin_y: int = SHROUD_ORIGIN_Y
    shroud_cell_size: int = SHROUD_CELL_SIZE
    shroud_inv_cell_size: int = SHROUD_INV_CELL_SIZE
    shroud_cells_x: int = SHROUD_CELLS_X
    shroud_cells_y: int = SHROUD_CELLS_Y
    shroud_cells: int = SHROUD_CELLS
    shroud_fog_enabled: int = SHROUD_FOG_ENABLED

    # PlayerList, from PlayerList::getNthPlayer
    pl_local_player: int = 0x10
    pl_count: int = 0x14
    pl_array: int = 0x18
    pl_max_players: int = 20

    # Player
    player_display_name: int = 0x38
    player_name: int = 0x4C
    player_side: int = 0x58
    player_resources: int = 0x94
    player_resources_collected: int = 0x3E0
    # Spellbook points. Found by granting points with the sandbox hero and then *spending*
    # one: both fields rise together on a grant, only `+0x24` falls on a purchase, which is
    # what separates the spendable balance from the lifetime total.
    player_power_points: int = 0x24
    player_power_points_total: int = 0x1C
    # The sciences the player holds, as a `std::vector<ScienceType>`: `{begin, end, capacity}`,
    # so the count is `(end - begin) / 4` and there is no count field to check it against. Same
    # shape as `TheSpecialPowerStore`'s vector, and the same absence of a checksum.
    #
    # Found by decoding rather than by shape, which is what makes it more than a plausible
    # triple: read as ini-order science ids the entries name exactly what each seat should be
    # holding. Measured live across one match's five seats (2026-08-04): every seat carried the
    # four view sciences (`SCIENCE_GENERAL_VIEW`, `..._COMMANDER_VIEW`, `..._UNIT_VIEW`,
    # `..._GROUND_VIEW`), each playing seat carried its own faction science first
    # (`SCIENCE_MEN` for the Men seat, `SCIENCE_MORDOR` for the Mordor one) and nobody else's,
    # and the Mordor AI carried five Mordor spellbook powers on top - `SCIENCE_EyeofSauron`,
    # `SCIENCE_SummonAufseher`, `SCIENCE_SBSummonEasterling`, `SCIENCE_Darkness`,
    # `SCIENCE_CalltheHorde`. Nothing but the right offset decodes as a coherent per-seat
    # spellbook, and the vector's own `end` is what says where the meaning stops: reading past
    # it yields other factions' sciences, which is exactly how a wrong length would look right.
    #
    # That decode is also an independent confirmation of the **id space** - the ids the engine
    # holds are `game.sciences` index + 1, which is what `sage_replay.idspace` derives from the
    # replay corpus and what `orders.purchase_power` sends.
    #
    # **The AI's set does not obey the ini's prerequisites** (it held `SCIENCE_Darkness` with
    # none of the three sciences that unlock it), so this reports what a player *has* and is
    # not a witness to how they got it. A skirmish AI is granted spells by script.
    #
    # **Not covered by the snapshot fixture**: that capture predates this field and never read
    # these bytes, so it decodes as an empty set there.
    player_sciences: int = 0x310
    # A held-science vector longer than this is a bad read rather than a real spellbook. The
    # store carries 263 entries on RotWK 2.01 + Edain and a seat holds a handful of them, so
    # this is loose by two orders of magnitude on purpose - it is a sanity limit, not a count.
    max_sciences: int = 1 << 12
    # Command points, as (in use, cap). `+0x068` was confirmed by recruiting a horde: 120 -> 180.
    #
    # **`+0x064` is the *base* cap and excludes every bonus.** It reads a flat 500 for every
    # player, engine-managed sides included, and usage passes it freely: a measured match ran
    # `+0x068` to 1436 against it. That is not the engine ignoring a ceiling, it is this field
    # not being the whole ceiling - Edain's `CPObject` carries a `CommandPointBonus`, and the
    # capacity the engine checks is this plus whatever those grant.
    #
    # Isolated live, which is what tells the two readings apart: a match sat pinned at 472/500
    # with recruits being discarded and the army stuck at 23 battalions, bought a `CPObject`,
    # and once that **finished building** went 472 -> 484 -> 532 with the army climbing again.
    # The base number never moved through any of it. Note the lag - a `CPObject` is queued and
    # built like a unit, so the capacity arrives at the end of its build time, not at purchase.
    #
    # So the cap is real and is enforced - at the base value until something raises it.
    #
    # **`+0x06C` is where the bonus lands, and base + bonus is the ceiling the engine checks.**
    # Walked live on 2026-08-04 across every seat in one match: base read a flat 500 for all of
    # them, and the two playing seats carried a bonus of 800 and 600 while their usage sat at
    # 1262 and 1077 - each pressed hard against its own `base + bonus` (1300 and 1100) and
    # neither over it. Watched across six samples the usage climbed 1088 -> 1262 as battalions
    # finished and never crossed the sum, and the Mordor seat's bonus stepped 600 -> 800 mid
    # sample, which is a `CPObject` completing.
    #
    # `+0x070` reads a flat 1500 for every seat, engine-managed ones included, and never moves.
    # That has the shape of the absolute maximum the engine will allow rather than anything
    # per-player, so it is recorded here and deliberately not applied: clamping to a number
    # whose meaning is inferred would trade a measured ceiling for a guessed one.
    #
    # **Not covered by the snapshot fixture.** That capture predates this field, so `+0x06C`
    # reads unreadable there and falls back to zero - which happens to be the right answer for
    # those bytes (an early frame with no `CPObject` built) and so leaves the golden decode
    # unchanged. The test therefore passes without exercising this at all; re-capturing during a
    # match with a raised ceiling is what would cover it.
    player_command_points_used: int = 0x68
    player_command_points_cap: int = 0x64
    player_command_points_bonus: int = 0x6C
    # The player's own Team. Ownership on an Object is a Team*, not a player index, so the
    # only way from an object to its owner is to invert this.
    player_default_team: int = 0x30C
    # Upgrade bitsets, indexed by the engine's own upgrade id: bit `id % 32` of the dword at
    # `base + (id // 32) * 4`. Found by researching two upgrades landing in different words and
    # confirming each bit where its id predicted. `in_progress` is set the moment an order is
    # accepted and cleared on completion - but only for PLAYER-scoped upgrades; for an
    # OBJECT-scoped one the engine sets it here and never clears it, so it is filtered by scope.
    player_upgrades_in_progress: int = 0x0BC
    player_upgrades_completed: int = 0x14C

    # GameLogic
    gl_frame: int = 0x40
    gl_table_begin: int = 0xB8
    gl_table_end: int = 0xBC
    gl_object_count: int = 0xC4

    # Table entry: a wrapper, not the object itself
    entry_id: int = 0x04
    entry_object: int = 0x08

    # UpgradeCenter - the engine's own upgrade table, so bit -> name needs no ini load.
    uc_list: int = 0x0C  # head of the template list, most recently registered first
    uc_count: int = 0x10
    # UpgradeTemplate
    upgrade_type: int = 0x04  # 0 = PLAYER, 1 = OBJECT
    upgrade_name: int = 0x08  # AsciiString
    upgrade_index: int = 0x38  # the engine's registration index == the replay id
    upgrade_next: int = 0x64

    # ThingFactory - the same shape as the UpgradeCenter, one list head and one count, so the
    # thing id space is readable from the process too. `tf_count` read 11143 on RotWK 2.01 +
    # Edain. Unlike an upgrade, a `ThingTemplate` carries no index field that was findable, so
    # the id comes from the walk position: the list is prepended, and reversing it gives
    # registration order with `DefaultThingTemplate` first.
    the_thing_factory: int = THE_THING_FACTORY
    tf_list: int = 0x0C
    tf_count: int = 0x10
    tmpl_next: int = 0x494

    # SpecialPowerStore - the third of the four id spaces, and the one registry that is **not**
    # a linked list. It is a `std::vector` of `SpecialPowerTemplate*`: `{begin, end, capacity}`
    # at `+0x0C`, so the count is `(end - begin) / 4` and there is no count field to check it
    # against. That shape is why the list walk used for the other two never found it.
    the_special_power_store: int = THE_SPECIAL_POWER_STORE
    sps_vector: int = 0x0C
    power_name: int = 0x10  # AsciiString on the template
    # A vector longer than this is a bad read rather than a real store.
    max_powers: int = 1 << 14

    # A special-power module, and the frame its power is next usable on. This is the engine's
    # own cooldown - the number `SpecialAbilityUpdate::startPowerRecharge` writes at
    # `0x00896f7f` as `TheGameLogic.frame + frames`, so a power is ready when `readyFrame` is
    # not in the future. Derivation in `sage_patch/docs/spell-recharge-filter.md`.
    #
    # The offsets come from that function's own register use: it is an adjustor thunk on the
    # `SpecialPowerModuleInterface` subobject at `module+0x10`, with the `ModuleData` at
    # `ecx-0xc` and the `Object` at `ecx-8` - so on the module itself the data pointer is at
    # `+0x04` and the ready frame at `+0x18`. The `ModuleData` names its `SpecialPowerTemplate`
    # at `+0x08`, and that template carries its name at `power_name`, the same offset the store
    # walk already uses.
    #
    # **Confirmed twice over, live.** Rallying Call read `readyFrame == frame` while ready, and
    # jumped 902 frames into the future the moment it was cast. And the only two powers on the
    # whole spellbook whose `readyFrame` is absurd (20.6M and 14.9M against a frame of 3155) are
    # exactly the two whose ini `ReloadTime` is absurd - the MM variants at 1e23 - which is the
    # field being derived from the data rather than coinciding with it.
    #
    # **Worth reading rather than computing**, because the ini figure is the *undiscounted* one:
    # that measured jump was 30 seconds against a `ReloadTime` of 180, so a policy pricing the
    # cooldown from the data alone waits six times too long.
    module_data: int = 0x04
    module_ready_frame: int = 0x18
    module_data_template: int = 0x08
    # A module list longer than this is a bad read; the spellbook carries about 140.
    max_modules: int = 1 << 10

    # Object
    obj_template: int = 0x04
    obj_team: int = 0x31C  # Team*, resolved to a player via the prototype below
    # `Team` -> `TeamPrototype` -> `Player`, which is what resolves the teams a player owns
    # beyond their default one. Verified live at frame 22952: every one of the six default teams
    # resolves through this chain to the same index `player_default_team` gives, and it also
    # resolves all 41 objects that the default-team map alone left ownerless - 39 of them
    # Isengard's, including the superweapon-summoned crossbow battalion that was shooting a farm
    # down while reading as nobody's. See `_owner_of_team`.
    team_proto: int = 0x30
    proto_owner: int = 0x08
    # A pointer to a **NULL-terminated** array of `BehaviorModule*`. This is the hop
    # `live-object-model.md` §5 named as the one thing missing for a live consumer: production
    # state lives on a module, and this is how an object reaches its modules.
    obj_modules: int = OBJECT_MODULE_LIST
    # Completed OBJECT-scoped upgrades, same bitset layout as the player's masks. An object has
    # no in-progress mask; the player's carries that, unclearable.
    obj_upgrades_completed: int = 0x28C
    obj_pos_x: int = 0x14
    obj_pos_y: int = 0x24
    obj_pos_z: int = 0x34
    obj_cos: int = 0x08
    obj_sin: int = 0x18
    # The engine's `ModelConditionFlags` - a 19-dword bitset of the states an object is in,
    # named by a NULL-terminated table of 591 strings in the image. This is how the game itself
    # knows a structure is still going up (`ACTIVELY_BEING_CONSTRUCTED`), a building is working
    # its door animation, or a unit is attacking - and it sits inside `obj_span`, so reading it
    # costs no read of its own. Offsets are `sage_patch.patches.utils.model_conditions`, whose
    # production-condition patch writes to this same mask.
    obj_model_conditions: int = MODEL_CONDITION_MASK
    model_condition_words: int = MODEL_CONDITION_DWORDS
    the_model_condition_names: int = MODEL_CONDITION_NAMES
    model_condition_count: int = MODEL_CONDITION_COUNT

    # **What contains this object** - the horde a battalion member belongs to. `Object*`, or 0
    # for anything standing on its own, which includes the container itself.
    #
    # Found differentially against a live match rather than by disassembly: of every dword in a
    # member's first `0x400` bytes, this is the one holding its container's address, and it did
    # so for 22 of 23 members while no other offset managed more than 2. Corroborated across
    # four factions at once - every one of the 38 objects carrying it pointed at a real object
    # in the table, none stood more than 200 units from it, and the template pairs are all
    # `X -> XHorde`, including an `ImladrisBanner` inside a `BruchtalLancerHorde` where the
    # names differ but the membership is right.
    #
    # Almost certainly SAGE's `m_containedBy`, which is the more general "what am I inside" -
    # so a garrisoned or transported unit should report its holder here too. Only horde
    # membership has been observed, so only that is claimed.
    obj_contained_by: int = 0x27C
    # The engine's `ObjectStatusMaskType` - what the game itself asks about an object before it
    # acts on it, and the other half of the containment story. `HORDE_MEMBER` is what marks a
    # unit as belonging to a battalion at all, and `IS_LEAVING_FACTORY` is what marks one that
    # has not finished coming out of the building that made it, so a battalion caught mid-form
    # is readable here and nowhere else. Same 16-byte window as everything above, so it costs
    # no read of its own. Derivation in `sage_patch.addresses`.
    obj_status: int = OBJECT_STATUS
    status_words: int = OBJECT_STATUS_DWORDS
    the_object_status_names: int = OBJECT_STATUS_NAMES
    object_status_count: int = OBJECT_STATUS_COUNT
    # The second `ObjectID`, next to the object's own. The engine falls back to it when
    # `obj_contained_by` is null and treats what it names as this object's horde, so a unit that
    # has left its battalion still points at it here - which is the whole reason it is read.
    obj_producer_id: int = OBJECT_PRODUCER_ID
    # `next` and `prev` of one **global** doubly-linked list holding every live object, not any
    # kind of parent link. Measured: 317 of 318 objects link, the two are exact inverses for
    # every one of them, there is a single head and a single tail, and walking `next` from the
    # head visits the whole table. They read like horde membership only because a battalion's
    # members are created consecutively and so end up adjacent in the list.
    obj_list_next: int = 0x8C
    obj_list_prev: int = 0x90
    obj_body: int = 0x25C
    # How much of an `Object` one read takes. Sized to reach past the last field read inline -
    # the team pointer at `+0x31C` - so a single read serves the whole header, upgrade mask
    # included. Widening it costs bytes; narrowing it silently reintroduces per-field reads
    # through the fallback path.
    obj_span: int = 0x320

    # BodyModule
    body_health: int = 0x08
    body_max_health: int = 0x10

    # ThingTemplate
    tmpl_name: int = 0x64
    tmpl_side: int = 0x6C

    # ProductionUpdate - what a structure is currently making.
    #
    # The module is identified by its **primary vtable**, which is unique to the class, so this
    # needs none of the engine calls `getProductionUpdateInterface` makes and cannot mistake a
    # different module for this one. Units and upgrades share one queue, appended at the tail.
    production_update_vtable: int = PRODUCTION_UPDATE_VTABLE
    module_object: int = 0x08  # Object* back-pointer, used to check the walk landed correctly
    production_head: int = 0x28
    production_tail: int = 0x2C
    production_count: int = 0x34
    # ProductionEntry, 0x54 bytes. `kind` is 1 for a unit, 2 for an upgrade, 3 for a hero
    # revive; the unit kinds keep a `ThingTemplate*` and the upgrade kind an `UpgradeTemplate*`,
    # in different slots.
    entry_kind: int = 0x04
    entry_template: int = 0x08
    entry_upgrade: int = 0x0C
    entry_next: int = 0x48
    # Walk guards. A queue longer than this, or an object with more modules, means a corrupt
    # read rather than a real structure - refuse rather than spin.
    max_queue: int = 64
    max_modules: int = 64

    # AsciiString: {u32 refcount; u32 allocated; char chars[]}
    string_chars: int = 8


LAYOUT_ROTWK_201 = EngineLayout()

# Refuse to walk a list longer than this; a corrupt `next` pointer would otherwise spin.
_MAX_UPGRADES = 1 << 14
# The thing table is an order of magnitude larger - 11,143 on RotWK 2.01 + Edain.
_MAX_THINGS = 1 << 17


@dataclass(frozen=True)
class UpgradeDefinition:
    """One row of the engine's own upgrade table.

    `upgrade_id` is the engine's registration index, which is **the same number the replay
    order stream carries** and the same number that indexes the live bitsets. So one integer
    serves all three, and reading the table here means a live consumer needs no ini load to
    name an upgrade.
    """

    upgrade_id: int
    name: str
    player_scoped: bool


class MemorySource(Protocol):
    """Somewhere bytes can be read from by address."""

    def read(self, address: int, size: int) -> bytes | None: ...

    def close(self) -> None: ...


def find_game_processes(name: str = "game.dat") -> list[int]:
    """Pids whose executable matches `name`. Returns [] off Windows rather than raising."""
    if sys.platform != "win32":
        return []

    class _Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_char * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot in (0, -1):
        return []
    found: list[int] = []
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        ok = k32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.decode("latin-1").lower() == name.lower():
                found.append(int(entry.th32ProcessID))
            ok = k32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    return found


class ProcessMemory:
    """Access to another process, via `ReadProcessMemory`.

    **Read-only unless `writable=True`.** Write access is opt-in so that the ordinary
    observation path cannot modify the game even by mistake; only the bridge, which has to
    fill the patched command buffer, asks for it.

    The platform check is here rather than at import, so `sage_live` stays importable on a
    machine with no game and no Windows.
    """

    # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    _READ = 0x0010 | 0x0400
    # PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    _WRITE = 0x0020 | 0x0008

    def __init__(self, pid: int, writable: bool = False) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                f"ProcessMemory needs Windows; this is {sys.platform}. "
                "Use a LoopbackBackend, or run the policy against a game in a VM."
            )
        self.pid = pid
        self.writable = writable
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.restype = ctypes.c_void_p
        self._k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        for name in ("ReadProcessMemory", "WriteProcessMemory"):
            getattr(self._k32, name).argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            )
        access = self._READ | (self._WRITE if writable else 0)
        handle = self._k32.OpenProcess(access, 0, pid)
        if not handle:
            err = ctypes.get_last_error()
            hint = (
                " - the game runs as administrator, so this process must be elevated too"
                if err == 5
                else ""
            )
            raise PermissionError(f"OpenProcess({pid}) failed with error {err}{hint}")
        self._handle: int | None = handle

    def read(self, address: int, size: int) -> bytes | None:
        if self._handle is None or size <= 0:
            return None
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        ok = self._k32.ReadProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
        )
        if not ok or got.value != size:
            return None
        return bytes(buf)

    def write(self, address: int, data: bytes) -> bool:
        """Write `data` at `address`. False unless the handle was opened writable."""
        if self._handle is None or not self.writable or not data:
            return False
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        put = ctypes.c_size_t()
        ok = self._k32.WriteProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(put)
        )
        return bool(ok) and put.value == len(data)

    def close(self) -> None:
        if self._handle is not None:
            self._k32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None


class MemoryBackend:
    """Observation-only backend over a live process.

    Cannot issue orders: writing to the message stream means calling into the engine, which
    needs code running inside it. `send` records a diagnostic and accepts nothing, rather
    than silently dropping a policy's actions.
    """

    def __init__(
        self,
        source: MemorySource,
        layout: EngineLayout = LAYOUT_ROTWK_201,
        handshake: Handshake | None = None,
        expect: Handshake | None = None,
        read_production: bool = True,
    ) -> None:
        self.source = source
        self.layout = layout
        # Reading production state costs a module-list walk per object - one read for the array
        # plus one per module until the `ProductionUpdate` is found or the list ends. That is
        # the largest per-object cost here after the object itself, so a consumer polling every
        # frame and not asking "what is this building making" can turn it off.
        self.read_production = read_production
        # Declared rather than agreed. A caller-supplied handshake is used unchanged; the
        # default one is built at connect time out of what the running image actually says,
        # so `expect` has something real to gate on.
        self._declared = handshake
        self._handshake = handshake or Handshake(engine_build=BUILD, fog_of_war=False)
        self._identity: BuildIdentity | None = None
        self._expect = expect
        self._diagnostics = DiagnosticLog()
        self._connected = False
        self._latest: Observation | None = None
        self._upgrades: dict[int, UpgradeDefinition] | None = None
        self._upgrade_word_count: int | None = None
        self._things: tuple[str, ...] | None = None
        self._powers: tuple[str, ...] | None = None
        # Bit-order name tables by their address, so the two bitsets share one cache.
        self._bit_name_tables: dict[int, tuple[str, ...]] = {}
        # `{template address -> name}` for both registries, filled by the walks above and used
        # to name whatever a production queue entry points at.
        self._thing_at: dict[int, str] = {}
        self._upgrade_at: dict[int, str] = {}
        # Per-template caches. A template's strings and its module composition are fixed once
        # ini parsing is done, so both are read once per template rather than once per object.
        self._template_at: dict[int, tuple[str, str]] = {}
        self._template_produces: dict[int, bool] = {}
        # `{object id -> Object*}`, rebuilt by every `read_objects`. Not a per-template cache
        # like the two above: object ids are reused as objects die and are created, so this is
        # only meaningful for the table walk that filled it.
        self._object_at: dict[int, int] = {}
        # `{Player* -> index}`, rebuilt with the team map each walk. `_owner_of_team` needs it to
        # turn the `Player*` a team's prototype names back into the index everything else uses.
        self._players_by_pointer: dict[int, int] = {}
        # Teams whose prototype chain did not land on a known player. Remembered so a team that
        # cannot be resolved is not re-walked for every object standing on it.
        self._teams_unresolved: set[int] = set()

    @property
    def diagnostics(self) -> DiagnosticLog:
        return self._diagnostics

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def identity(self) -> BuildIdentity | None:
        """What the running image says it is, once connected."""
        return self._identity

    def connect(self) -> Handshake:
        """Identify the build, agree the handshake, and confirm a game is running.

        In that order, because each failure is more specific than the last and the first
        message that fits is the useful one: "this is not that build" is a better report than
        "TheGameLogic is null", which is what a wrong build looks like from the inside.
        """
        self._identity = self._identify()
        if self._declared is None:
            self._handshake = Handshake(
                engine_build=BUILD,
                data_checksum=self._identity.fingerprint,
                fog_of_war=False,
            )
        if self._expect is not None:
            ok, why = self._expect.accepts(self._handshake)
            if not ok:
                raise ConnectionRefused(why)
        if self._u32(self.layout.the_game_logic) in (None, 0):
            raise ConnectionRefused(
                "TheGameLogic is null - no game in progress, or the layout is for another build"
            )
        self._connected = True
        return self._handshake

    def _identify(self) -> BuildIdentity:
        """The running image, refused unless it is the build this layout describes."""
        identity = read_identity(self.source.read, IMAGE_BASE)
        if identity is None:
            raise ConnectionRefused(
                f"no PE image is mapped at {IMAGE_BASE:#010x}: this is not a game.dat process, "
                "the handle cannot read it (an unelevated shell), or the image was relocated - "
                "and a relocated image invalidates every address in the layout"
            )
        expected = self.layout.build_timestamp
        if expected and identity.timestamp != expected:
            raise ConnectionRefused(
                f"this is not the build the layout describes: the running game.dat is stamped "
                f"{identity.timestamp:#010x}, and these offsets were confirmed against "
                f"{expected:#010x}. Reading it anyway would not fail - it would report plausible "
                "nonsense - so pass an EngineLayout for this build, or set `build_timestamp` to 0 "
                "in --layout-json to read it unverified"
            )
        return identity

    def close(self) -> None:
        self._connected = False
        self.source.close()

    def _u32(self, address: int) -> int | None:
        raw = self.source.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def _i32(self, address: int) -> int | None:
        raw = self.source.read(address, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def _f32(self, address: int) -> float | None:
        raw = self.source.read(address, 4)
        return float(struct.unpack("<f", raw)[0]) if raw else None

    def _pointer(self, address: int) -> int | None:
        """A pointer field, or None when it is null or implausible."""
        value = self._u32(address)
        if value is None or not (_MIN_PTR <= value <= _MAX_PTR):
            return None
        return value

    def _ascii(self, address: int, limit: int = 128) -> str:
        """Follow an `AsciiString` field and read its characters."""
        data_ptr = self._pointer(address)
        if data_ptr is None:
            return ""
        raw = self.source.read(data_ptr + self.layout.string_chars, limit)
        if not raw:
            return ""
        return raw.split(b"\x00")[0].decode("latin-1", errors="replace")

    def _utf16(self, address: int, limit: int = 128) -> str:
        data_ptr = self._pointer(address)
        if data_ptr is None:
            return ""
        raw = self.source.read(data_ptr + self.layout.string_chars, limit)
        if not raw:
            return ""
        text = raw.decode("utf-16-le", errors="replace")
        return text.split("\x00")[0]

    def upgrade_table(self) -> dict[int, UpgradeDefinition]:
        """`{engine upgrade id -> definition}`, read from `TheUpgradeCenter` and cached.

        The table is fixed once the game has parsed its ini, so this is read once per backend.
        Reading it from the engine rather than from ini keeps this module data-free and makes
        the ids exact for whatever mod is loaded - `sage_live.utils.resolve` has to reconstruct the
        same numbering from ini and carries a `+3` offset to do it, which is precisely the
        three upgrades the engine registers itself (`Upgrade_Veterancy_VETERAN`, `_ELITE`,
        `_HEROIC`) before any definition is parsed. Those three have no ini definition at all.

        The list is prepended, so walking `upgrade_next` from the head yields reverse
        registration order; the id comes off each template rather than from the walk position,
        so the order does not matter here.
        """
        if self._upgrades is not None:
            return self._upgrades
        lay = self.layout
        table: dict[int, UpgradeDefinition] = {}
        centre = self._pointer(lay.the_upgrade_center)
        if centre is None:
            self._diagnostics.append(Diagnostic("TheUpgradeCenter is null; upgrades unnamed"))
            self._upgrades = table
            return table
        node = self._pointer(centre + lay.uc_list)
        seen: set[int] = set()
        while node is not None and node not in seen and len(seen) < _MAX_UPGRADES:
            seen.add(node)
            name = self._ascii(node + lay.upgrade_name)
            upgrade_id = self._i32(node + lay.upgrade_index)
            # id 0 is a real upgrade (`Upgrade_Veterancy_VETERAN`), so only negatives are junk.
            if name:
                self._upgrade_at[node] = name
            if name and upgrade_id is not None and upgrade_id >= 0:
                table[upgrade_id] = UpgradeDefinition(
                    upgrade_id=upgrade_id,
                    name=name,
                    player_scoped=self._i32(node + lay.upgrade_type) == 0,
                )
            node = self._pointer(node + lay.upgrade_next)
        expected = self._u32(centre + lay.uc_count)
        # One id is legitimately missing: the first-registered template reads -1 rather than 0.
        if expected is not None and len(seen) != expected:
            self._diagnostics.append(
                Diagnostic(f"walked {len(seen)} upgrade templates but the centre claims {expected}")
            )
        self._upgrades = table
        return table

    def thing_order(self) -> tuple[str, ...]:
        """Every `ThingTemplate` name in **registration order**, read from `TheThingFactory`.

        The index into this tuple is the 0-based registration index, so a replay/order id is
        `index + sage_replay.idspace.THING_OFFSET`. That the offset is 1 is corroborated here
        rather than assumed: index 0 walks out as `DefaultThingTemplate`, which is exactly what
        an id space starting at 1 puts first.

        **The list is prepended**, so walking `tmpl_next` from the head yields reverse
        registration order and this reverses it. That matters for the failure mode: the walk
        reaches one template fewer than `tf_count` claims, and because the reversal anchors
        index 0 at the first-registered template, a shortfall at the *tail* (the newest
        registration) shifts nothing. A gap in the middle would shift every id after it, so
        this is checked, not assumed - the diagnostic below fires if the count disagrees.

        Cached: the table is fixed once ini parsing is done, and it runs to five figures.
        """
        if self._things is not None:
            return self._things
        lay = self.layout
        factory = self._pointer(lay.the_thing_factory)
        if factory is None:
            self._diagnostics.append(Diagnostic("TheThingFactory is null; thing names unavailable"))
            self._things = ()
            return self._things

        # One read per node covers both the name pointer and the next pointer.
        span = lay.tmpl_next + 4
        node = self._pointer(factory + lay.tf_list)
        walked: list[str] = []
        seen: set[int] = set()
        while node is not None and node not in seen and len(seen) < _MAX_THINGS:
            seen.add(node)
            blob = self.source.read(node, span)
            if blob is None:
                break
            name_ptr = struct.unpack_from("<I", blob, lay.tmpl_name)[0]
            name = ""
            if _MIN_PTR <= name_ptr <= _MAX_PTR:
                chars = self.source.read(name_ptr + lay.string_chars, 128)
                if chars:
                    name = chars.split(b"\x00")[0].decode("latin-1", errors="replace")
            walked.append(name)
            # Kept so a pointer held by something else - a production queue entry - can be
            # resolved to a name by identity rather than by a second guess at a layout.
            self._thing_at[node] = name
            nxt = struct.unpack_from("<I", blob, lay.tmpl_next)[0]
            node = nxt if _MIN_PTR <= nxt <= _MAX_PTR else None

        expected = self._u32(factory + lay.tf_count)
        if expected is not None and len(walked) != expected:
            self._diagnostics.append(
                Diagnostic(
                    f"walked {len(walked)} thing templates but the factory claims {expected}; "
                    "ids are trustworthy only if the missing entries are the newest ones"
                )
            )
        self._things = tuple(reversed(walked))
        return self._things

    def power_order(self) -> tuple[str, ...]:
        """Every `SpecialPower` name in registration order, from `TheSpecialPowerStore`.

        The index is the 0-based registration index, so an order id is
        `index + sage_replay.idspace.POWER_OFFSET`. Index 0 walks out as `DefaultSpecialPower`,
        which is what a 1-based id space puts first - the same corroboration `thing_order` has.

        **Corroborated exactly.** Measured against a live RotWK 2.01 + Edain match
        (2026-07-31): this walk reads 1,566 powers and the ini reconstruction reads 1,566, and
        they agree **position by position on all 1,566**, with no empty name and no duplicate.
        The two are independent - one walks the engine's own vector, the other parses ini - so
        that is a stronger agreement than either gives alone, and stronger than the thing
        table's, which diverges in its tail.

        Unlike the other registries this is a vector, not a list, so there is no count field to
        cross-check the walk against; the bound below is a sanity limit, not a checksum.
        """
        if self._powers is not None:
            return self._powers
        lay = self.layout
        store = self._pointer(lay.the_special_power_store)
        if store is None:
            self._diagnostics.append(Diagnostic("TheSpecialPowerStore is null; powers unnamed"))
            self._powers = ()
            return self._powers
        begin = self._pointer(store + lay.sps_vector)
        end = self._u32(store + lay.sps_vector + 4)
        if begin is None or end is None or end < begin:
            self._diagnostics.append(Diagnostic("the special-power vector is unreadable"))
            self._powers = ()
            return self._powers
        count = (end - begin) // 4
        if not (0 < count <= lay.max_powers):
            self._diagnostics.append(Diagnostic(f"implausible special-power count {count}"))
            self._powers = ()
            return self._powers
        raw = self.source.read(begin, count * 4)
        if raw is None:
            self._powers = ()
            return self._powers
        names: list[str] = []
        for template in struct.unpack(f"<{count}I", raw):
            if not (_MIN_PTR <= template <= _MAX_PTR):
                names.append("")
                continue
            names.append(self._ascii(template + lay.power_name))
        self._powers = tuple(names)
        return self._powers

    def _bit_names(self, table: int, declared: int, label: str) -> tuple[str, ...]:
        """A bit-order name table: a NULL-terminated `const char*[]` in static data.

        The engine keeps both of the bitsets read here this way, so this is the one kind of
        registry that needs no heap walk at all - and neither can drift, because the same
        tables are what the game's own ini parser resolves a name against.

        The count is checked rather than trusted: the table is walked to its terminator and
        compared against the bit count the engine's own loops use, since a table shorter than
        the count is exactly what `sage_patch`'s production-condition patch warns about - the
        single-bit-name helper indexes it with no bound check.
        """
        cached = self._bit_name_tables.get(table)
        if cached is not None:
            return cached
        names: list[str] = []
        for index in range(declared + 1):
            pointer = self._pointer(table + index * 4)
            if pointer is None:
                break
            raw = self.source.read(pointer, 64)
            if raw is None:
                break
            names.append(raw.split(b"\x00")[0].decode("latin-1", errors="replace"))
        if names and len(names) != declared:
            self._diagnostics.append(
                Diagnostic(f"walked {len(names)} {label} names but this build declares {declared}")
            )
        self._bit_name_tables[table] = tuple(names)
        return self._bit_name_tables[table]

    def model_condition_names(self) -> tuple[str, ...]:
        """The engine's `ModelConditionFlags` names, in bit order, read from the image."""
        lay = self.layout
        return self._bit_names(
            lay.the_model_condition_names, lay.model_condition_count, "model-condition"
        )

    def object_status_names(self) -> tuple[str, ...]:
        """The engine's `ObjectStatus` names, in bit order, read from the image."""
        lay = self.layout
        return self._bit_names(
            lay.the_object_status_names, lay.object_status_count, "object-status"
        )

    def _flags_at(
        self, blob: bytes | None, obj_ptr: int, base: int, words: int, names: tuple[str, ...]
    ) -> frozenset[str]:
        """Decode one of an object's bitsets into names.

        Costs no read of its own: both masks live inside the object header `obj_span` already
        covers. Names are only looked up once a bit is actually set, so an object in no
        interesting state pays for nothing.
        """
        span = words * 4
        if blob is not None and base + span <= len(blob):
            raw: bytes | None = blob[base : base + span]
        else:
            raw = self.source.read(obj_ptr + base, span)
        if not raw:
            return frozenset()
        bits = int.from_bytes(raw, "little")
        if not bits or not names:
            return frozenset()
        found: list[str] = []
        while bits:
            lowest = bits & -bits
            index = lowest.bit_length() - 1
            if index < len(names):
                found.append(names[index])
            bits ^= lowest
        return frozenset(found)

    def _upgrade_words(self) -> int:
        """How many dwords of a bitset can hold every upgrade this build defines.

        Derived from the engine's own count rather than assumed. The two player masks sit 0x90
        apart, which is more than the 0x7C that 976 upgrades need, so the arrays are wider than
        the ids in use - reading only as far as the count means a stray high bit in unused space
        can never be decoded as an upgrade.

        Cached with the table: every object in a snapshot asks for it, and the answer cannot
        change while the game is running.
        """
        if self._upgrade_word_count is not None:
            return self._upgrade_word_count
        centre = self._pointer(self.layout.the_upgrade_center)
        count = self._u32(centre + self.layout.uc_count) if centre is not None else None
        if count is None or not (0 < count <= _MAX_UPGRADES):
            count = max(self.upgrade_table(), default=0) + 1
        self._upgrade_word_count = (count + 31) // 32
        return self._upgrade_word_count

    def _upgrades_at(
        self,
        base_ptr: int,
        base: int,
        player_scope: bool | None = None,
        blob: bytes | None = None,
    ) -> frozenset[str]:
        """Decode one upgrade bitset into code names.

        `player_scope` filters by the definition's scope: the player's in-progress mask records
        object-scoped upgrades too and never clears them, so reporting those would mean claiming
        a battalion upgrade is pending for the rest of the match.

        `blob` is the already-read header the mask sits inside, so an object's mask costs no
        read of its own. The layout's `obj_span` is sized to contain it.
        """
        words = self._upgrade_words()
        if blob is not None and base + words * 4 <= len(blob):
            raw: bytes | None = blob[base : base + words * 4]
        else:
            raw = self.source.read(base_ptr + base, words * 4)
        if raw is None:
            return frozenset()
        table = self.upgrade_table()
        names: list[str] = []
        bits = int.from_bytes(raw, "little")
        while bits:
            lowest = bits & -bits
            definition = table.get(lowest.bit_length() - 1)
            if definition is not None and (
                player_scope is None or definition.player_scoped == player_scope
            ):
                names.append(definition.name)
            bits ^= lowest
        return frozenset(names)

    def _sciences_at(self, base_ptr: int) -> frozenset[int]:
        """The ids in a player's held-science vector - see `player_sciences`.

        Empty is an ordinary answer rather than a failure: a source that never recorded these
        bytes reads as unreadable, and every seat legitimately holds a handful.

        Bounded by the science id space rather than trusted, because the three pointers are all
        this has to go on: an implausible length is a bad read, and walking one would spend
        seconds turning garbage into a set of numbers that looks exactly like data.
        """
        lay = self.layout
        begin = self._pointer(base_ptr + lay.player_sciences)
        end = self._u32(base_ptr + lay.player_sciences + 4)
        if begin is None or end is None or end < begin:
            return frozenset()
        count = (end - begin) // 4
        if not (0 < count <= lay.max_sciences):
            if count:
                self._diagnostics.append(Diagnostic(f"implausible science count {count}"))
            return frozenset()
        raw = self.source.read(begin, count * 4)
        if raw is None:
            return frozenset()
        return frozenset(struct.unpack(f"<{count}i", raw))

    def read_players(self) -> tuple[PlayerState, ...]:
        lay = self.layout
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            self._diagnostics.append(Diagnostic("ThePlayerList is null"))
            return ()
        count = self._u32(pl + lay.pl_count) or 0
        if count > lay.pl_max_players:
            self._diagnostics.append(Diagnostic(f"implausible player count {count}"))
            count = lay.pl_max_players
        players: list[PlayerState] = []
        for index in range(count):
            ptr = self._pointer(pl + lay.pl_array + index * 4)
            if ptr is None:
                continue
            name = self._ascii(ptr + lay.player_name)
            side = self._ascii(ptr + lay.player_side)
            # The neutral placeholder slot carries no name and no side; it is not a player.
            if not name and not side:
                continue
            players.append(
                PlayerState(
                    index=index,
                    name=name or self._utf16(ptr + lay.player_display_name),
                    faction=side,
                    resources=self._i32(ptr + lay.player_resources) or 0,
                    resources_collected=self._i32(ptr + lay.player_resources_collected) or 0,
                    power_points=self._i32(ptr + lay.player_power_points) or 0,
                    command_points=(
                        self._i32(ptr + lay.player_command_points_used) or 0,
                        # Base plus bonus, because neither alone is the ceiling the engine
                        # checks - see the layout note on `player_command_points_bonus`.
                        (self._i32(ptr + lay.player_command_points_cap) or 0)
                        + (self._i32(ptr + lay.player_command_points_bonus) or 0),
                    ),
                    sciences=self._sciences_at(ptr),
                    upgrades=self._upgrades_at(ptr, lay.player_upgrades_completed, True),
                    upgrades_in_progress=self._upgrades_at(
                        ptr, lay.player_upgrades_in_progress, True
                    ),
                )
            )
        return tuple(players)

    def local_player_index(self) -> int:
        lay = self.layout
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            return 0
        local = self._pointer(pl + lay.pl_local_player)
        count = min(self._u32(pl + lay.pl_count) or 0, lay.pl_max_players)
        for index in range(count):
            if self._pointer(pl + lay.pl_array + index * 4) == local:
                return index
        return 0

    def power_cooldowns(self, object_id: int) -> dict[str, int]:
        """`{power name -> the frame it is next usable on}` for one object's special powers.

        **The engine's own cooldown, which is not the ini's.** `SpecialPower.ReloadTime` is the
        undiscounted figure and Edain scales it per player, so a policy computing readiness from
        the data waits too long - measured at 30 seconds of real recharge against a declared 180.
        Reading it also survives the two things a local clock cannot: a consumer that restarted
        mid-match, and a cast made by anything other than that consumer.

        Called with the player's `SpellBookMp` object to price the spellbook; it works on any
        object carrying special-power modules, so a hero's abilities answer the same way.

        Empty is an ordinary answer - an object with no such modules, or one whose id is not in
        the last table walk. **The id must come from that walk**: ids are reused as objects die,
        so this resolves through the map `read_objects` filled rather than scanning for it.
        """
        lay = self.layout
        address = self._object_at.get(object_id)
        if address is None:
            return {}
        modules = self._pointer(address + lay.obj_modules)
        if modules is None:
            return {}
        found: dict[str, int] = {}
        for index in range(lay.max_modules):
            module = self._pointer(modules + index * 4)
            if module is None:
                # A NULL terminates the list, which is what bounds this walk in practice.
                break
            data = self._pointer(module + lay.module_data)
            if data is None:
                continue
            template = self._pointer(data + lay.module_data_template)
            if template is None:
                # Not a special-power module: every other module family leaves this unset, and
                # the engine's own recharge path bails on exactly this test.
                continue
            name = self._ascii(template + lay.power_name)
            ready = self._i32(module + lay.module_ready_frame)
            if name and ready is not None:
                found[name] = ready
        return found

    def read_objects(self) -> tuple[GameObject, ...]:
        lay = self.layout
        gl = self._pointer(lay.the_game_logic)
        if gl is None:
            self._diagnostics.append(Diagnostic("TheGameLogic is null"))
            return ()
        begin = self._pointer(gl + lay.gl_table_begin)
        end = self._u32(gl + lay.gl_table_end)
        if begin is None or end is None or end <= begin:
            self._diagnostics.append(Diagnostic("object table bounds are unreadable"))
            return ()
        slots = (end - begin) // 4
        if slots > _MAX_TABLE_SLOTS:
            self._diagnostics.append(Diagnostic(f"implausible object table of {slots} slots"))
            return ()

        raw = self.source.read(begin, slots * 4)
        if raw is None:
            self._diagnostics.append(Diagnostic("object table is unreadable"))
            return ()

        # Two passes: ids live on the table entry but horde links point at the Object, so a
        # parent's id is only knowable once every object pointer has been indexed.
        entries: list[tuple[int, int]] = []
        id_of: dict[int, int] = {}
        for entry_ptr in struct.unpack(f"<{slots}I", raw):
            if not (_MIN_PTR <= entry_ptr <= _MAX_PTR):
                continue
            # The id and the object pointer are adjacent, so one read serves both.
            head = self.source.read(entry_ptr + lay.entry_id, lay.entry_object - lay.entry_id + 4)
            if head is None:
                continue
            object_id, obj_ptr = struct.unpack_from("<II", head)
            if not (_MIN_PTR <= obj_ptr <= _MAX_PTR):
                continue
            entries.append((entry_ptr, obj_ptr))
            id_of[obj_ptr] = object_id
            # The inverse, kept for the walks that start from an id rather than from the table -
            # `power_cooldowns` is one. Free here and a 12,289-slot scan anywhere else.
            self._object_at[object_id] = obj_ptr

        owner_of = self._team_owners()
        objects: list[GameObject] = []
        for entry_ptr, obj_ptr in entries:
            obj = self._read_object(entry_ptr, obj_ptr, id_of, owner_of)
            if obj is not None:
                objects.append(obj)
        return tuple(objects)

    def _team_owners(self) -> dict[int, int]:
        """`{Team* -> player index}`, inverted from each player's own team pointer.

        An `Object` names its owner by `Team*`, and a `Team` carries no back-pointer to its
        `Player` (its first 0x400 bytes hold none), so the map has to be built from the player
        side. Verified against a live match: every player's team matched the objects grouped
        under it - the creeps' team held exactly the Mordor and Wild objects, the local
        player's held the Men ones.

        This seeds the map with each player's *default* team; `_owner_of_team` resolves the rest
        on demand through the team's prototype, and memoises the answer back into this dict.
        """
        lay = self.layout
        self._players_by_pointer = {}
        self._teams_unresolved = set()
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            return {}
        count = min(self._u32(pl + lay.pl_count) or 0, lay.pl_max_players)
        owners: dict[int, int] = {}
        for index in range(count):
            player = self._pointer(pl + lay.pl_array + index * 4)
            if player is None:
                continue
            self._players_by_pointer[player] = index
            team = self._pointer(player + lay.player_default_team)
            if team is not None:
                owners.setdefault(team, index)
        return owners

    def _owner_of_team(self, team: int, owners: dict[int, int]) -> int | None:
        """The player index owning `team`, following its prototype when it is not a default team.

        **A player owns more than one team, and the extra ones are not decoration.** SAGE gives
        each player a default team and creates others as the match needs them - a superweapon's
        summons arrive on one - so a map built only from `player_default_team` leaves real units
        ownerless. Reading that as "nobody" is what let an Isengard crossbow battalion shoot a
        farm down while every decision that asks whose it is answered "no one's".

        The route is `Team+0x30 -> TeamPrototype`, `TeamPrototype+0x08 -> Player`. Found by
        scanning a summoned battalion's team for any pointer whose target held a known `Player*`,
        and **checked the only way that means anything**: run against the six teams the default
        map already resolves, it returns the same index for every one of them. On the same frame
        it resolves all 41 objects that read as ownerless without it - 39 Isengard, 2 ours -
        with none left over.

        Memoised into `owners`, so a team costs two reads once rather than two per object on it.
        None only when the chain breaks or lands on a `Player*` that is not in the player list,
        which stays "unresolved" rather than being guessed at.
        """
        known = owners.get(team)
        if known is not None:
            return known
        # **Both misses are memoised, and that is what keeps this off the per-object budget.**
        # An object costs three reads; walking the prototype for every one of them would add two
        # more, and a team that does not resolve would pay them again on the next object and the
        # next. A null team never resolves and is answered without reading anything at all.
        if not team or team in self._teams_unresolved:
            return None
        proto = self._pointer(team + self.layout.team_proto)
        player = self._pointer(proto + self.layout.proto_owner) if proto else None
        index = self._players_by_pointer.get(player) if player else None
        if index is None:
            self._teams_unresolved.add(team)
        else:
            owners[team] = index
        return index

    def _body_values(self, body: int) -> tuple[float | None, float | None]:
        """Current and maximum hit points, in one read where the span is readable.

        Falls back to reading each field on its own, for the same reason the object header
        does: a span crossing into an unmapped page fails as a whole while each field inside it
        reads perfectly, and a recorded snapshot holds only the ranges its capture touched.
        """
        lay = self.layout
        span = lay.body_max_health - lay.body_health + 4
        raw = self.source.read(body + lay.body_health, span)
        if raw is not None and len(raw) >= span:
            return (
                float(struct.unpack_from("<f", raw, 0)[0]),
                float(struct.unpack_from("<f", raw, span - 4)[0]),
            )
        return self._f32(body + lay.body_health), self._f32(body + lay.body_max_health)

    def _template_info(self, template: int) -> tuple[str, str] | None:
        """`(name, Side)` for a `ThingTemplate`, cached by address.

        Four reads per object became four reads per *template*: a match holds hundreds of
        objects across a few dozen templates, and a template's strings never change once ini
        parsing is done. Keyed by pointer because templates are allocated once and never move.

        None means the pointer did not land on a `ThingTemplate` - a template name is a single
        ini identifier, so anything with a space or a dot in it says the chain went wrong and
        the whole reading is unsafe rather than merely odd.
        """
        cached = self._template_at.get(template)
        if cached is None:
            name = self._ascii(template + self.layout.tmpl_name)
            if not name or " " in name or "." in name:
                self._template_at[template] = ("", "")
                return None
            cached = (name, self._ascii(template + self.layout.tmpl_side))
            self._template_at[template] = cached
        return cached if cached[0] else None

    def _read_object(
        self, entry_ptr: int, obj_ptr: int, id_of: dict[int, int], owner_of: dict[int, int]
    ) -> GameObject | None:
        lay = self.layout
        # One read for the whole header instead of a dozen. The fallback is not defensive
        # decoration: an object whose header straddles into an unmapped page fails the wide
        # read and reads perfectly well field by field, and a recorded snapshot only holds the
        # ranges its capture touched.
        blob = self.source.read(obj_ptr, lay.obj_span)

        def u32(offset: int) -> int | None:
            if blob is not None:
                return int(struct.unpack_from("<I", blob, offset)[0])
            return self._u32(obj_ptr + offset)

        def f32(offset: int) -> float:
            if blob is not None:
                return float(struct.unpack_from("<f", blob, offset)[0])
            return self._f32(obj_ptr + offset) or 0.0

        def pointer(offset: int) -> int | None:
            value = u32(offset)
            return value if value is not None and _MIN_PTR <= value <= _MAX_PTR else None

        template = pointer(lay.obj_template)
        if template is None:
            return None
        named = self._template_info(template)
        if named is None:
            return None
        name, side = named

        # Not every object has a body: inert map markers (wall hubs, farm spots) carry a
        # pointer at this offset whose contents are uninitialised, reading as denormal
        # floats. A body is only believed when its maximum is a plausible hit-point figure,
        # so max_health == 0 means "no body", not "dead".
        health, max_health = 1.0, 0.0
        body = pointer(lay.obj_body)
        if body is not None:
            current, maximum = self._body_values(body)
            if current is not None and maximum is not None and maximum >= 1.0 and current >= 0.0:
                health = max(0.0, min(1.0, current / maximum))
                max_health = maximum

        upgrades = self._upgrades_at(obj_ptr, lay.obj_upgrades_completed, False, blob=blob)
        return GameObject(
            object_id=id_of.get(obj_ptr, 0),
            template_name=name,
            template_side=side,
            position=(f32(lay.obj_pos_x), f32(lay.obj_pos_y), f32(lay.obj_pos_z)),
            angle=math.atan2(f32(lay.obj_sin), f32(lay.obj_cos)),
            health=health,
            max_health=max_health,
            owner_index=self._owner_of_team(pointer(lay.obj_team) or 0, owner_of),
            # Object-scoped only. A structure or battalion upgrade is recorded nowhere else -
            # not in the template name, not on the player - so without this an upgrade the
            # policy paid for is indistinguishable from one it never bought.
            upgrades=upgrades,
            conditions=self._flags_at(
                blob,
                obj_ptr,
                lay.obj_model_conditions,
                lay.model_condition_words,
                self.model_condition_names(),
            ),
            status=self._flags_at(
                blob, obj_ptr, lay.obj_status, lay.status_words, self.object_status_names()
            ),
            # The container this object is inside, resolved through the address->id map the
            # first pass built. `None` when it stands alone, which is why the walk is two-pass:
            # the pointer names an `Object`, and only the table knows that object's id.
            parent_id=id_of.get(pointer(lay.obj_contained_by) or 0),
            # An id, not a pointer, so it needs no map - and unlike `parent_id` it is not
            # cleared when the object leaves what it names. A stale one is the point: it is how
            # the engine still finds a horde for a unit that is no longer in it.
            producer_id=u32(lay.obj_producer_id) or None,
            production=(
                self._read_production(obj_ptr, template, pointer(lay.obj_modules))
                if self.read_production
                else ()
            ),
        )

    @property
    def alive(self) -> bool:
        """Whether the process is still there, by the cheapest read that proves it.

        `TheGameLogic` is a static inside the mapped image, so the read succeeds for as long
        as the process does - whatever value it holds.
        """
        return self._u32(self.layout.the_game_logic) is not None

    def _game_logic(self) -> int | None:
        """The `GameLogic` pointer, telling a dead process apart from a null global.

        **A vanished process does not read as zeroes - it does not read at all.** Every field
        then falls back to its default and the observation comes back empty, which is
        indistinguishable from a match that ended. `ReadProcessMemory` failing at a static
        address inside the image is the signal, and it is only visible here, before the
        defaults are applied.
        """
        value = self._u32(self.layout.the_game_logic)
        if value is None:
            raise GameExited(
                f"the game is gone: reading TheGameLogic at "
                f"{self.layout.the_game_logic:#010x} failed. The process exited, crashed, or "
                "the handle was closed - this is not a match that ended"
            )
        return value if _MIN_PTR <= value <= _MAX_PTR else None

    def _production_module(self, array: int) -> tuple[int | None, bool]:
        """The `ProductionUpdate` in a module array, and whether the walk reached a conclusion.

        Walks the NULL-terminated module array at `Object+0x24C` and matches on each module's
        primary vtable. The engine does this by asking every module's second vtable for its
        production interface - a call, which a reader outside the process cannot make - but a
        vtable address is unique to its class, so comparing the pointer answers the same
        question without executing anything.

        The second half of the answer is what makes the per-template cache safe: "walked the
        whole list and it is not there" may be remembered, "a read failed halfway" may not.
        """
        lay = self.layout
        raw = self.source.read(array, lay.max_modules * 4)
        if raw is None:
            return None, False
        for module in struct.unpack(f"<{lay.max_modules}I", raw):
            if module == 0:  # the terminator: the list really does end without one
                return None, True
            if not (_MIN_PTR <= module <= _MAX_PTR):
                return None, False
            vtable = self._u32(module)
            if vtable is None:
                return None, False
            if vtable == lay.production_update_vtable:
                return module, True
        return None, True

    def _read_production(
        self, obj_ptr: int, template: int, array: int | None
    ) -> tuple[ProductionItem, ...]:
        """What this object is currently making, in queue order.

        Empty for the overwhelming majority of objects, which carry no production module at
        all - so "not producing" and "cannot produce" are deliberately the same answer: both
        mean an order sent here will do nothing.

        Names are resolved by **pointer identity** against the two registries this backend
        already walks. An entry pointing at something neither registry knows is reported with
        an empty name rather than a guessed one, so a layout that drifts degrades to "something
        is queued" instead of inventing a template.

        **Most objects can skip the walk entirely.** Which behaviour modules an object carries
        comes from its `ThingTemplate`, so once one `GondorFighter` has been walked and found
        to have no production module, no other `GondorFighter` needs walking - and in a real
        match the overwhelming majority of objects are units and scenery. Only a *conclusive*
        walk is remembered; a read that failed partway teaches nothing.
        """
        lay = self.layout
        if array is None or self._template_produces.get(template) is False:
            return ()
        module, conclusive = self._production_module(array)
        if module is None:
            if conclusive:
                self._template_produces[template] = False
            return ()
        self._template_produces[template] = True
        # The module names its owner. If this disagrees, the module array was not what we
        # thought it was, and everything read past here would be fiction.
        if self._pointer(module + lay.module_object) != obj_ptr:
            self._diagnostics.append(
                Diagnostic(
                    f"a ProductionUpdate at {module:#x} does not point back at the object "
                    f"{obj_ptr:#x} it was reached from; the module list layout is wrong"
                )
            )
            return ()

        items: list[ProductionItem] = []
        node = self._pointer(module + lay.production_head)
        seen: set[int] = set()
        while node is not None and node not in seen and len(items) < lay.max_queue:
            seen.add(node)
            kind = self._i32(node + lay.entry_kind)
            if kind == 2:
                # Both registry walks are cached and are triggered here rather than up front,
                # so an observation of a game where nothing is producing never pays for them.
                self.upgrade_table()
                name = self._upgrade_at.get(self._u32(node + lay.entry_upgrade) or 0, "")
                items.append(ProductionItem("upgrade", name))
            elif kind in (1, 3):
                self.thing_order()
                name = self._thing_at.get(self._u32(node + lay.entry_template) or 0, "")
                items.append(ProductionItem("unit" if kind == 1 else "revive", name))
            else:
                items.append(ProductionItem("unknown"))
            node = self._pointer(node + lay.entry_next)

        declared = self._u32(module + lay.production_count)
        if declared is not None and declared != len(items):
            self._diagnostics.append(
                Diagnostic(
                    f"walked {len(items)} production entries but the module counts {declared}"
                )
            )
        return tuple(items)

    def frame(self) -> int:
        gl = self._game_logic()
        if gl is None:
            return 0
        return self._u32(gl + self.layout.gl_frame) or 0

    def read_shroud(self, players: Sequence[int]) -> ShroudGrid | None:
        """The visibility grid for `players`, or None when there is no readable one.

        None is the ordinary answer at the menu, where the grid collapses to 1x1. It is not an
        error, so it records no diagnostic; what would be an error is treating an absent grid as
        "everything is visible", which is why `Observation.under_fog` refuses to filter without
        one rather than filtering with an empty one.
        """
        lay = self.layout
        return read_shroud(
            self._u32,
            self._f32,
            self.source.read,
            lay.the_shroud_manager,
            lay.shroud_impl,
            {
                "origin_x": lay.shroud_origin_x,
                "origin_y": lay.shroud_origin_y,
                "cell_size": lay.shroud_cell_size,
                "inv_cell_size": lay.shroud_inv_cell_size,
                "cells_x": lay.shroud_cells_x,
                "cells_y": lay.shroud_cells_y,
                "cells": lay.shroud_cells,
                "fog_enabled": lay.shroud_fog_enabled,
            },
            players,
        )

    def observe(self) -> Observation:
        # Ordered so the liveness check runs before anything can quietly default.
        self._game_logic()
        players = self.read_players()
        # Every seat, not just the local one: `under_fog` takes a viewer, and a caller checking
        # what an *opponent* can see is exactly how you tell a working filter from one that
        # happens to hide everything. A seat costs one `u16` per cell, ~21 KB on a 104x104 map.
        return Observation(
            frame=self.frame(),
            local_player=self.local_player_index(),
            players=players,
            objects=self.read_objects(),
            # False because `objects` is still the whole map. The grid rides along so a consumer
            # can apply the filter; `under_fog` is what sets this True.
            fogged=False,
            shroud=self.read_shroud([p.index for p in players]),
        )

    def poll(self) -> Observation | None:
        if not self._connected:
            self._diagnostics.append(Diagnostic("poll before connect"))
            return None
        self._latest = self.observe()
        return self._latest

    def step(self, timeout: float | None = None) -> Observation | None:
        """Wait for the logic frame to advance, then observe.

        This does **not** hold the engine: it watches the frame counter and returns when it
        moves. That is enough for a bot, but it is not the deterministic stepping an RL
        rollout needs - only a backend running inside the process can provide that.
        """
        if not self._connected:
            self._diagnostics.append(Diagnostic("step before connect"))
            return None
        start_frame = self.frame()
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.frame() == start_frame:
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.001)
        return self.poll()

    def send(self, orders: Sequence[Order]) -> int:
        if orders:
            self._diagnostics.append(
                Diagnostic(
                    "MemoryBackend is observation-only; issuing orders needs a bridge "
                    "running inside the game"
                )
            )
        return 0
