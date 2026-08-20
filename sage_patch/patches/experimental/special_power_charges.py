"""Charges on a special power: several casts banked behind a short cooldown, then a long one.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/special-power-charges.md``.

**What a mod writes.** Three new keys on the `SpecialPower` block, all inert unless `ChargeNumber`
is set:

.. code-block:: none

    SpecialPower SpecialAbilityWarChant
      ReloadTime                      = 120000   ; unchanged keyword: time to regain ONE charge
      ChargeNumber                    = 3        ; how many casts are banked
      ReloadTimeBetweenCharge         = 15000    ; the short cooldown between two banked casts
      ReplenishAllChargesOnReloadTime = No       ; Yes: one ReloadTime refills the whole bank
    End

`ReloadTime` keeps its name and its units and changes meaning only for a power that declares
`ChargeNumber`: it becomes the refill period, and **the refill clock starts the moment the first
charge goes missing**, not when the bank empties.

**Why this is cheap.** The engine's cooldown is an *absolute frame*, not a countdown - nothing ticks
a special power while it recharges, and nothing has to. A charge bank does not need a per-frame
driver either: the refill deadline is a second absolute frame, and the charge count is recovered
from it by integer division at the only two moments anyone asks. So there is **no sweep**, unlike
`recharge-rescale`, and `isReady` is not patched:

* with charges left, `readyFrame` holds the short cooldown;
* with the bank empty, `readyFrame` is set **to the refill deadline**.

One field expresses both rules, so `ControlBar::getCommandAvailability`, both click arms, the AI and
the button's pie clock all keep working untouched. `getPercentReady` is
`1 - (readyFrame - now) / duration` and the hook writes both fields together, the way
`startPowerRecharge` does, so the clock fills over whichever wait is actually in force.

**Where the hook goes, and the two wrong answers before it.** `startPowerRecharge` is where a
cooldown is armed, and the engine arms cooldowns from **fourteen** sites. Hooking the function
spends a charge at all fourteen - including the module constructor, so every charge power began the
match one short, and the `OnTriggerRechargeSpecialPower` walk, which arms a *different* power.
Hooking instead the one call that looks like *the* cast, `doSpecialPower`'s call on its own
interface at `0x008979C2`, misses every ability written the way most targeted hero abilities in
Edain are: a `SpecialPowerModule` with `UpdateModuleStartsAttack = Yes` beside a
`WeaponFireSpecialAbilityUpdate`, where the engine's own guard at `0x008979B1` hands the recharge
to the update module and that call never runs.

So the discrimination is **on the caller, not on the call**: the hook is at
:data:`RECHARGE_HOOK`, the five bytes that open the full-recharge arm, and it reads the return
address at `[ebp+4]` to exclude the two arms that are provably not a use
(:data:`MODULE_CTOR_RETURN`, :data:`TRIGGER_WALK_RETURN`). Everything else is a use, whichever
module flavour drove it. That works because of what the function is: it **never clears** a
cooldown, only arms one, so "went on cooldown" is the same event the player watches the pie start
for.

`edi` already holds `max(1, ftol(ReloadTime * m))` - the refill interval, computed by the engine
with whatever modifiers are in force - so the short cooldown is that same ratio applied to
`ReloadTimeBetweenCharge` in integers. This patch runs no float arithmetic of its own on the
simulation path and cannot disagree with the engine about how long a refill takes.

**Where the state lives.** Nine bytes of `SpecialPowerTemplate`, which has two - so the struct grows
from `0x88` to `0x94` across its three `push 0x88` allocations, all `push imm32` and therefore
same-length edits. Per module, six bytes of padding that is neither read nor `Xfer`'d: a **24-bit**
absolute refill deadline at interface `+0x19..+0x1B` and a spent-charge count at `+0x21`. Two
`mov byte` -> `mov dword` widenings in the base constructor zero both.

**The readout.** One line on a special-power button's description saying how many charges are left
and, while a refill is pending, how long until it lands. Silent unless the mod declares the key -
`TOOLTIP:SpecialPowerCharges` (`%d`, `%d`) when the bank is full of pending nothing, and
`TOOLTIP:SpecialPowerChargesRecharging` (`%d`, `%d`, `%.1f`) while a refill is running. The tooltip
is composed once per hover and never refreshed
(:mod:`~sage_patch.patches.description_timers` §2), so the seconds are a snapshot taken when the
tooltip appeared, not a countdown.

Determinism
-----------
The charge count gates whether a power fires, so this is **simulation state**: every peer must run
the same patched binary and replays do not cross. The only writer is the cast, on the logic thread
inside `doSpecialPower`; the tooltip runs the same fold routine read-only, and that fold is a
pure function of `(spent, deadline, interval, now)` which is idempotent under intermediate
evaluation, so a client that hovers a button cannot drag its state away from a peer that never did.

Savegames
---------
Neither new module field is in the module's `Xfer` (`0x0089679D` transfers `+0x14`..`+0x30` and
none of the padding), so **a loaded game brings every charge power back at a full bank** with no
refill cycle running. `duration`/`readyFrame` reload correctly and keep whatever cooldown was in
flight. Adding the two would need a version bump on a function whose version byte is already
compared twice, which breaks savegame interchange with unpatched clients in both directions.

Composition
-----------
* **`recharge-rescale` conflicts.** Its per-frame sweep tests `ftol(ReloadTime * m) == duration` and
  rescales when they differ; a charged power's `duration` is the *short* cooldown, so the sweep
  would rewrite it every frame. Teaching that sweep to skip `ChargeNumber != 0` is one compare, but
  it is a change to that patch.
* **`hero-mana` conflicts twice** - it grows `SpecialPowerTemplate` to `0x8C` for its own field, and
  it takes the same description case at `0x00808675`.
* **`cooldown-through-death` composes**: it spends the interior padding at `+0x5A`/`+0x5B`, which
  this patch does not touch, and both read the field table live through
  :func:`~.utils.field_tables.resolve_table`. Its state table snapshots `(readyFrame, duration,
  deathFrame)` and not the bank, so a revived hero returns with a restored cooldown and a full bank.
* **`description-timers` composes**, on disjoint bytes - it owns the builder's tail
  (`0x008086AE`), this owns the special-power case (`0x00808675`).
* **`trigger-recharge-list` composes**, and cleanly: `OnTriggerRechargeSpecialPower` reaches
  `startPowerRecharge(1.0)` through `0x00897A35`, which this patch does not hook, so arming another
  power's cooldown does **not** spend a charge from its bank. That is the right reading - a forced
  recharge is not a cast - and it falls out of hooking the cast rather than the recharge.

What is not covered
-------------------
* **`SharedSyncedTimer` templates** keep their cooldown on the `Player` (`0x006AD1B0`), so
  `startPowerRecharge` returns before the hook. That is three templates in the whole game
  (`SuperweaponSpawnOrcs`, `SpecialPowerRevealArea`, `SuperweaponPartTheHeavens`) and **not** the
  spellbook: a spellbook is an ordinary `Object` whose spells are ordinary `SpecialPowerModule` /
  `OCLSpecialPower` / `PlayerUpgradeSpecialPower` behaviours, all three of which run the base
  constructor this patch widens and carry the vtable it hooks.
* **The `SpecialPowerUpdateModule` family** - `DeflectSpecialPower`, `SiegeDeployHordeSpecialPower`
  and the base - dispatch to the other `startPowerRecharge` (`0x00991500`), which keeps no
  duration. They ignore `ChargeNumber`: the keys parse, nothing reads them.
* **The partial-recharge arm** (`0x00896F16`, reached with an argument below `1.0` - the script
  engine's "advance this cooldown by a fraction") moves `readyFrame` and leaves the bank alone. A
  fraction of a charged cooldown is not a defined idea and this patch does not invent one.
* **Nothing that clears a cooldown is hooked** - `setReadyFrame` (the script actions and
  `HeroDie::onDie`) and the thirteen other `startPowerRecharge` sites all keep stock behaviour.
  They do not have to be: `fold` notices after the fact. A power whose bank is empty holds
  `readyFrame` *at* its refill deadline, so a `readyFrame` in the past while the deadline is still
  ahead can only mean something restored the cooldown, and `fold` treats that as a refill landing
  early. So "this ability resets that cooldown" hands back a charge as well as the cast, which is
  what it has to mean for a charged power.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    DESCRIPTION_OBJECT_EBP_OFFSET,
    DESCRIPTION_PLAYER_EBP_OFFSET,
    DESCRIPTION_SPECIAL_POWER_CASE,
    DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
    DESCRIPTION_TEXT_EBP_OFFSET,
    DESCRIPTION_UNIT_COST_BODY,
    FIELD_PARSE_STRIDE,
    FLOAT_ONE,
    GAME_LOGIC_FRAME,
    GAME_TEXT_FORMAT_SLOT,
    GET_FINAL_OVERRIDE,
    GUI_COMMAND_SPECIAL_POWER,
    INI_PARSE_BOOL,
    INI_PARSE_INT,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
    THE_GAME_LOGIC,
    THE_GAME_TEXT,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_CONCAT_WIDE,
    WIDE_NEWLINE,
)
from ...asm import JAE, JB, JE, JG, JGE, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table

__all__ = [
    "ANCHORS",
    "KEY_CHARGES",
    "KEY_CHARGES_RECHARGING",
    "KEYWORD_CHARGE_NUMBER",
    "KEYWORD_RELOAD_BETWEEN",
    "KEYWORD_REPLENISH_ALL",
    "NEW_TEMPLATE_SIZE",
    "SECTION_NAME",
    "SpecialPowerChargesPatch",
    "build_table",
    "rewritten_module_ctor_flag",
    "rewritten_module_ctor_held",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".spchrg"

#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds the rebuilt
#: field table, the two localization keys and the routines; nothing in it is written at runtime,
#: but the section is marked writable for the same reason every other cave in this package is - the
#: engine's own image is, and a read-only cave buys nothing here.
_CHARACTERISTICS = 0xE0000060

# --- the INI surface -------------------------------------------------------------------------

KEYWORD_CHARGE_NUMBER = "ChargeNumber"
KEYWORD_RELOAD_BETWEEN = "ReloadTimeBetweenCharge"
KEYWORD_REPLENISH_ALL = "ReplenishAllChargesOnReloadTime"

#: The localization keys the description line is fetched under. Neither is declared by stock data,
#: and a key the string table does not define produces **no line at all** - which is what makes the
#: readout a no-op on unmodified data.
KEY_CHARGES = "TOOLTIP:SpecialPowerCharges"
KEY_CHARGES_RECHARGING = "TOOLTIP:SpecialPowerChargesRecharging"

#: `INI::parseDurationUnsignedInt` - the parse function `ReloadTime` itself uses, which reads an
#: `Int` of **milliseconds**, multiplies by `[0x00D9F610]` (frames per millisecond) and `ftol`s the
#: product into the field. `ReloadTimeBetweenCharge` reuses it verbatim, which is what makes the
#: cave's arithmetic a copy of `startPowerRecharge`'s rather than a unit conversion.
INI_PARSE_DURATION = 0x0073A429

# --- SpecialPowerTemplate --------------------------------------------------------------------

#: The three new fields, appended past `UnitCostDeathType` at `+0x84`. The struct is packed solid -
#: its only interior padding is the two bytes at `+0x5A`/`+0x5B`, which `cooldown-through-death`
#: spends - so nine bytes have to come from the end and `sizeof` grows to `0x94`.
TEMPLATE_CHARGE_NUMBER = 0x88
TEMPLATE_RELOAD_BETWEEN = 0x8C
TEMPLATE_REPLENISH_ALL = 0x90
NEW_TEMPLATE_SIZE = 0x94

#: Fields the cooldown formula reads, unchanged from `startPowerRecharge`'s own reads, plus the
#: `SharedSyncedTimer` bool the cast arm fails closed on: those templates keep their cooldown on
#: the `Player` (`0x006AD1B0`), so the module has no `duration` to read the refill interval out of.
#: Three `SpecialPower` blocks in the whole game set it, and none of them is a spellbook spell.
TEMPLATE_FLAGS = 0x18
TEMPLATE_RELOAD_TIME = 0x20
TEMPLATE_SHARED_SYNCED_TIMER = 0x59

#: `Flags` bit 5, `RESPECT_RECHARGE_TIME_DISCOUNT`, tested at the only instruction in the binary
#: that reads it (`0x00896EBA`).
RESPECT_RECHARGE_TIME_DISCOUNT_SHIFT = 5

#: The constructor's last field store, `mov dword [esi+0x84], ebx`. Six bytes, not a branch target,
#: and `ebx` is the constructor's zero throughout - so the cave replays it and zeroes the three new
#: dwords behind it. `hero-mana` zeroes its own grown tail at `operator new` instead; taking the
#: constructor is one site rather than three and leaves the allocations to the size edit alone.
TEMPLATE_CTOR_TAIL = 0x007B200D
TEMPLATE_CTOR_TAIL_BYTES = bytes.fromhex("899e84000000")
TEMPLATE_CTOR_TAIL_RESUME = 0x007B2013

# --- SpecialPowerModuleInterface -------------------------------------------------------------

#: The subobject at module `+0x10`. `+0x04` and `+0x08` are the pair `startPowerRecharge` writes
#: and `getPercentReady` divides; `+0x18` is the byte it clears at the end of every recharge, and
#: the three bytes behind that byte are free - not written by the constructor, not in the `Xfer`.
SPI_DURATION = 0x04
SPI_READY_FRAME = 0x08
SPI_FLAG = 0x18

#: The **24-bit absolute refill deadline**, read as `[iface+0x18] >> 8` and written back with the
#: flag byte preserved. `0` means no refill cycle is running, which is unambiguous because a live
#: deadline is always `now + interval` with `interval >= 1`. `0x00FFFFFF` logic frames is over 900
#: hours at the engine's 5 fps - past the point where the frame counter is the least of the
#: problems - and a dword would need four contiguous free bytes where the module has two runs of
#: three.
SPI_DEADLINE_SHIFT = 8

#: The spent-charge count, in the tail padding behind the "held" latch at `+0x20`. `sizeof` is
#: `0x34` and every derived module places its own fields at `0x34` and above, so `+0x21..+0x23` is
#: interior to the base subobject on all 23 flavours.
SPI_SPENT = 0x21

SPI_VTABLE = 0x00C64FF0
SPI_VTABLE_TEMPLATE_SLOT = 0x18  # getSpecialPowerTemplate
SPI_VTABLE_RECHARGE_SLOT = 0x3C  # startPowerRecharge - the flavour discriminator

#: `SpecialAbilityUpdate::startPowerRecharge`, the implementation in 23 of the 26 special-power
#: vtables - the one whose ready frame is at interface `+0x08` and whose duration is at `+0x04`.
START_POWER_RECHARGE = 0x00896E31

#: The base module constructor's two byte stores, widened to dwords in place - one opcode bit each,
#: same length. The first zeroes `+0x28..+0x2B` (the recharge flag plus the deadline), the second
#: `+0x30..+0x33` (the held latch plus the spent count). `ebx` is zero throughout the constructor,
#: which is what both stores already write.
MODULE_CTOR_FLAG = 0x00897447
MODULE_CTOR_FLAG_BYTES = bytes.fromhex("885e28")  # mov byte [esi+0x28], bl
MODULE_CTOR_HELD = 0x0089744D
MODULE_CTOR_HELD_BYTES = bytes.fromhex("885e30")  # mov byte [esi+0x30], bl

#: **The hook**, and the second thing a running game had to teach this patch.
#:
#: `startPowerRecharge` is where a cooldown is armed, and the engine arms cooldowns from
#: **fourteen** places - a scan of `.text` for `fld1` reaching a call through interface slot
#: `+0x3C`, plus the one direct `call rel32`. The first build hooked the function and spent a
#: charge at every one of them, so a single cast emptied the bank. The second hooked
#: `doSpecialPower`'s call on its own interface, at `0x008979C2`, on the reasoning that it is *the*
#: cast - and it is, for a `SpecialPowerModule` that drives itself. It is **not** reached at all
#: when the module sets `UpdateModuleStartsAttack = Yes`, which is `ModuleData+0xC`, which is the
#: byte in the engine's own guard three instructions earlier:
#:
#: .. code-block:: none
#:
#:     008979b1  cmp byte [ebx+0xc], 0     ; UpdateModuleStartsAttack
#:     008979b5  jne 0x8979c5              ;   Yes -> the update module arms it, later, elsewhere
#:
#: That pairing - a `SpecialPowerModule` with `UpdateModuleStartsAttack = Yes` beside a
#: `WeaponFireSpecialAbilityUpdate` naming the same template - is how most targeted hero abilities
#: in Edain are written, so hooking the one call meant charges did nothing for most of them.
#:
#: **So the discrimination is on the caller, not on the call.** The hook is back inside
#: `startPowerRecharge`, at the five bytes that open its full-recharge arm, and it asks
#: `[ebp+4]` - the return address, which the function's own `push ebp` / `mov ebp, esp` makes
#: available throughout - whether this arm is one of the two that are provably **not** a use:
#: the base module constructor and the `OnTriggerRechargeSpecialPower` walk. Everything else is a
#: use, whichever module flavour drove it.
#:
#: That is the right shape because of what the function is: `startPowerRecharge` **never clears a
#: cooldown**, it only ever arms one, so "the power went on cooldown" is the same event the player
#: watches the pie start for. Two arms are not uses; the rest are, and this patch does not have to
#: know which module class each of them belongs to.
#:
#: At the window `esi` is the interface, `edi` is `max(1, ftol(ReloadTime * m))` - already the
#: refill interval - and every callee-saved register survives the two calls the cave makes. It is
#: a `jbe` target, which a `jmp rel32` replacing the whole instruction is fine to be.
RECHARGE_HOOK = 0x00896F75
RECHARGE_HOOK_BYTES = bytes.fromhex("a12c41de00")  # mov eax, [TheGameLogic]
#: Where the displaced instruction's successor is, for the arm that declines to do anything.
RECHARGE_STOCK_RESUME = 0x00896F7A
#: `mov byte [esi+0x18], 0` - the join every arm of `startPowerRecharge` falls into.
RECHARGE_DONE = 0x00896F8E

#: The two return addresses that mean "this cooldown was armed, but nobody used the power".
#:
#: `0x00897476` returns into the **base module constructor** (`call 0x00896E31` at `0x00897471`),
#: which arms a power declared to start on cooldown - before the match, for every such power, so
#: charging it would put every charge ability one short at spawn.
#:
#: `0x00897A38` returns into `doSpecialPower`'s `OnTriggerRechargeSpecialPower` walk
#: (`call [eax+0x3c]` at `0x00897A35`), which arms a **different** power's cooldown because this
#: one was used - "using this ability also puts that one on cooldown". Charging it would spend from
#: a bank whose power never fired. See ``../../docs/trigger-recharge-list.md``.
MODULE_CTOR_RETURN = 0x00897476
TRIGGER_WALK_RETURN = 0x00897A38

#: The two call sites those return addresses belong to, anchored so that a build which moved either
#: one fails to apply rather than silently charging the constructor again.
MODULE_CTOR_CALL = 0x00897471
MODULE_CTOR_CALL_BYTES = bytes.fromhex("e8bbf9ffff")  # call 0x00896E31
TRIGGER_WALK_CALL = 0x00897A35
TRIGGER_WALK_CALL_BYTES = bytes.fromhex("ff503c")  # call [eax+0x3c]

#: `doSpecialPower`'s `UpdateModuleStartsAttack` guard: `mov ebx, [edi+4]` (the `ModuleData`),
#: `cmp byte [ModuleData+0xC], 0`, the `jne` past the whole recharge, and the `lea` / `fld1` that
#: set up the call an earlier build of this patch hooked. Anchored - though nothing here writes it
#: - because it is *why* the hook is on the caller rather than the call: this branch is the engine
#: choosing which of two modules arms the cooldown, and a build that spelled it differently would
#: want this patch re-read rather than re-applied.
DO_SPECIAL_POWER_GUARD = 0x008979AE

# --- the engine routines the cave calls ------------------------------------------------------

#: `Object::getSpecialPowerModule(SpecialPowerTemplate *)` - `__thiscall`, `ret 4`, returns the
#: module's **special-power interface** (its `[eax]` is the interface vtable) or NULL.
GET_SPECIAL_POWER_MODULE = 0x0068C26D

#: `Object::getModifierMultiplier(type, out, ctx, flag)` - `__thiscall` plus four stack arguments,
#: `ret 0x10`, seeds `*out` at 1.0 and multiplies. It does not preserve `ecx`.
GET_MODIFIER_MULTIPLIER = 0x0068C82D
MODIFIER_TYPE_RECHARGE_TIME = 0x0C

#: `Player`'s spell-recharge modifier: `__thiscall`, no arguments, leaves `Player+0x718` on the FPU
#: stack.
PLAYER_RECHARGE_MODIFIER = 0x006AAAD2

#: `ftol`, and the constant the engine adds when an `fild`'d dword was meant as unsigned. Both are
#: copied from the recharge maths rather than simplified away: the two multiplies happen in an x87
#: register and folding them would round the intermediate, which is a duration one frame off the
#: engine's own.
FTOL = 0x00A3CFA4
FLOAT_U32_FIXUP = 0x00BD8698

#: `UnicodeString::~UnicodeString` - `__thiscall`, no arguments. The line the readout builds is a
#: temporary of its own, which the stock idiom never needs.
UNICODE_STRING_DESTRUCT = 0x004367B0

#: **The logic frame rate**, as an `Int` - it is **5**, not the 30 four bytes above it. Picking the
#: wrong one is a silent factor-of-six error in every second this patch prints;
#: :mod:`~sage_patch.patches.description_timers` derives it in full.
LOGIC_FRAMES_PER_SECOND = 0x00D9F608

#: `CommandButton::m_specialPower`.
COMMAND_BUTTON_SPECIAL_POWER = 0x44

#: Where the special-power case falls out to when the GUI command is not `0x18`.
DESCRIPTION_CASE_NOT_TAKEN = 0x008086AA

#: Everything the cave calls or compares against, by address and by first bytes. A patch whose job
#: is calling engine functions with the right arguments has no way to notice that one of them
#: moved - it would simply call whatever now lives there. :data:`START_POWER_RECHARGE` is here for
#: a second reason: the readout *compares a vtable slot against it*, and if that function moved the
#: comparison would answer "not this flavour" for every power in the game.
ANCHORS: dict[int, bytes] = {
    GET_FINAL_OVERRIDE: bytes.fromhex("8bc18b500485d274"),
    GET_SPECIAL_POWER_MODULE: bytes.fromhex("837c24040075"),
    GET_MODIFIER_MULTIPLIER: bytes.fromhex("e874fcffff85c075"),
    PLAYER_RECHARGE_MODIFIER: bytes.fromhex("d98118070000c3"),
    FTOL: bytes.fromhex("558bec83ec2083e4"),
    UNICODE_STRING_CONCAT: bytes.fromhex("8b4424088b0085c0"),
    UNICODE_STRING_APPEND: bytes.fromhex("8b4424048b0085c074060fb7"),
    UNICODE_STRING_CONCAT_WIDE: bytes.fromhex("568b74240885f6578bf9740a"),
    UNICODE_STRING_DESTRUCT: bytes.fromhex("6aff68f80eb70064a100000000506489250000000083ec08"),
    START_POWER_RECHARGE: bytes.fromhex("558bec83ec0c568bf1"),
    DO_SPECIAL_POWER_GUARD: bytes.fromhex("8b5f04807b0c00750e8d4f10d9e8"),
    MODULE_CTOR_CALL: MODULE_CTOR_CALL_BYTES,
    TRIGGER_WALK_CALL: TRIGGER_WALK_CALL_BYTES,
    INI_PARSE_DURATION: bytes.fromhex("558bec518b4d086a00"),
    0x008969CA: bytes.fromhex("8b41f48b4008c3"),  # getSpecialPowerTemplate, interface slot +0x18
}

#: The cast-time arithmetic the cave transcribes, at the two instructions that carry its whole
#: meaning: the `RESPECT_RECHARGE_TIME_DISCOUNT` test and the `ReloadTime` read. If a build encodes
#: either differently, the transcription is describing a formula that build does not use.
RECHARGE_FORMULA_ANCHORS: dict[int, bytes] = {
    0x00896EBA: bytes.fromhex("8b4018c1e805a801"),
    0x00896EE3: bytes.fromhex("8b4020"),
}

#: What the `SpecialPower` field table has to say before this patch touches it - a far stronger
#: build check than the table's base address, which another patch may legitimately have moved.
FINGERPRINT: dict[str, int] = {
    "ReloadTime": TEMPLATE_RELOAD_TIME,
    "Flags": TEMPLATE_FLAGS,
    "UnitCost": 0x80,
    "UnitCostDeathType": 0x84,
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
    return off


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))


def rewritten_module_ctor_flag() -> bytes:
    """``mov byte [esi+0x28], bl`` widened to ``mov dword [esi+0x28], ebx``.

    One opcode bit, three bytes for three, so there is no hook and no displaced instruction. It
    zeroes the recharge flag exactly as before and the deadline behind it as well - which it has to,
    because `operator new` does not zero the block and a deadline that started as heap garbage would
    change behaviour on data that never named `ChargeNumber`."""
    return bytes([0x89]) + MODULE_CTOR_FLAG_BYTES[1:]


def rewritten_module_ctor_held() -> bytes:
    """``mov byte [esi+0x30], bl`` widened the same way, zeroing the spent count behind the held
    latch. `sizeof` is `0x34`, so the dword store stays inside the base subobject."""
    return bytes([0x89]) + MODULE_CTOR_HELD_BYTES[1:]


def build_table(
    entries: tuple[Entry, ...], charge_va: int, reload_va: int, replenish_va: int
) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the three new rows, the terminator.

    The live rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are - and only the three new rows point into the cave.
    """
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", charge_va, INI_PARSE_INT, 0, TEMPLATE_CHARGE_NUMBER)
    table += struct.pack("<IIII", reload_va, INI_PARSE_DURATION, 0, TEMPLATE_RELOAD_BETWEEN)
    table += struct.pack("<IIII", replenish_va, INI_PARSE_BOOL, 0, TEMPLATE_REPLENISH_ALL)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.

_EBP_TEXT = _i8(DESCRIPTION_TEXT_EBP_OFFSET)
_EBP_OBJECT = _i8(DESCRIPTION_OBJECT_EBP_OFFSET)
_EBP_PLAYER = _i8(DESCRIPTION_PLAYER_EBP_OFFSET)


def _emit_fold(a: Asm) -> None:
    """``fold(iface, tmpl, interval, now) -> eax = spent', edx = deadline'``. Stdcall, `ret 0x10`.

    **The one routine both callers share, and it writes nothing.** Given the two stored frames it
    answers what the bank would be at `now`:

    .. code-block:: none

        if deadline == 0 or spent == 0:       nothing pending
        elif now >= deadline:                 granted = 1 + (now - deadline) / interval
        elif the bank is empty and the power is already ready:
                                              granted = 1, and the cycle restarts from now
        else:                                 granted = 0

        if ReplenishAllChargesOnReloadTime or granted >= spent:
                                              spent' = 0;               deadline' = 0
        else:                                 spent' = spent - granted; deadline' advances

    `deadline` advancing by whole multiples of `interval` is what makes the answer independent of
    *when* it was asked, which is what lets the client-side readout run it without the simulation
    caring.

    **The middle arm is the "something restored this cooldown" case.** A power whose bank is empty
    holds `readyFrame` *at* the refill deadline, so the only thing that can make it castable before
    then is code outside this patch - a script action, `HeroDie`'s recharge-by-dying, one of the
    thirteen other `startPowerRecharge` sites. Left alone, the restore would hand back the cast
    without handing back the charge, and the bank would drain one use per restore. Treating it as
    a refill landing early is the reading that makes "this ability resets that cooldown" mean the
    same thing for a charged power as for an ordinary one. It cannot misfire on a power with
    charges left, because there `readyFrame` is an ordinary short cooldown and the test requires
    `spent == ChargeNumber`.

    Preserves `ebx`, `esi` and `edi`, which both callers keep things in.
    """
    a.label("fold")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    # [esp]=edi [esp+4]=esi [esp+8]=ebx [esp+0xc]=ret [esp+0x10]=iface .. [esp+0x1c]=now
    a.emit(0x8B, 0x74, 0x24, 0x10)  # mov esi, [esp+0x10]        the interface
    a.emit(0x8B, 0x7C, 0x24, 0x18)  # mov edi, [esp+0x18]        the interval
    a.emit(0x0F, 0xB6, 0x46, SPI_SPENT)  # movzx eax, byte [esi+0x21]   spent
    a.emit(0x8B, 0x5E, SPI_FLAG)  # mov ebx, [esi+0x18]
    a.emit(0xC1, 0xEB, SPI_DEADLINE_SHIFT)  # shr ebx, 8                the deadline

    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "f_out")  # no cycle running: nothing to grant
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "f_clear")  # a cycle with nothing spent cannot be right; end it
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "f_out")  # a zero interval would fault the divide
    a.emit(0x8B, 0x4C, 0x24, 0x1C)  # mov ecx, [esp+0x1c]        now
    a.emit(0x3B, 0xCB)  # cmp ecx, ebx
    a.jcc(JAE, "f_due")

    # Not due - unless something outside this patch cleared the cooldown while the bank was empty.
    a.emit(0x8B, 0x54, 0x24, 0x14)  # mov edx, [esp+0x14]        the template
    a.emit(0x3B, 0x82, _u32(TEMPLATE_CHARGE_NUMBER))  # cmp eax, [edx+0x88]
    a.jcc(JB, "f_out")  # charges remain: an ordinary short cooldown, nothing happened
    a.emit(0x3B, 0x4E, SPI_READY_FRAME)  # cmp ecx, [esi+8]
    a.jcc(JB, "f_out")  # still on the refill's own clock: nothing happened
    a.emit(0x80, 0xBA, _u32(TEMPLATE_REPLENISH_ALL), 0x00)  # cmp byte [edx+0x90], 0
    a.jcc(JNE, "f_clear")
    a.emit(0x48)  # dec eax                                      one charge back
    a.jcc(JE, "f_clear")
    a.emit(0x8B, 0xD9)  # mov ebx, ecx
    a.emit(0x03, 0xDF)  # add ebx, edi                           the cycle restarts from now
    a.jmp("f_out")

    a.label("f_due")
    a.emit(0x8B, 0x54, 0x24, 0x14)  # mov edx, [esp+0x14]        the template
    a.emit(0x80, 0xBA, _u32(TEMPLATE_REPLENISH_ALL), 0x00)  # cmp byte [edx+0x90], 0
    a.jcc(JNE, "f_clear")  # ReplenishAllChargesOnReloadTime: the whole bank comes back

    # granted = 1 + (now - deadline) / interval, in integers. `ecx` is `now` and `ebx` the
    # deadline, so nothing stack-relative is read while the saved count is pushed.
    a.emit(0x2B, 0xCB)  # sub ecx, ebx                           now - deadline
    a.emit(0x50)  # push eax                                     the spent count
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0xF7, 0xF7)  # div edi
    a.emit(0x40)  # inc eax                                      granted
    a.emit(0x59)  # pop ecx                                      the spent count
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JAE, "f_clear")  # granted >= spent: the bank is full again
    a.emit(0x2B, 0xC8)  # sub ecx, eax                           spent -= granted
    a.emit(0xF7, 0xE7)  # mul edi                                edx:eax = granted * interval
    a.emit(0x03, 0xD8)  # add ebx, eax                           deadline += that
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.jmp("f_out")

    a.label("f_clear")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x33, 0xDB)  # xor ebx, ebx

    a.label("f_out")
    a.emit(0x8B, 0xD3)  # mov edx, ebx                           deadline', before ebx is restored
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x10, 0x00)  # ret 0x10


def _emit_cast(a: Asm) -> None:
    """The cast, hooked onto `startPowerRecharge`'s full-recharge arm.

    Entered with `esi` = the interface, `edi` = the refill interval the engine has just computed,
    and `ebp` = the function's own frame. `esi` and the stack have to survive: the epilogue three
    instructions past the join pops `ebx`/`edi`/`esi` and `leave`s. `eax`, `ecx` and `edx` are
    free, and the two calls made here are MSVC `__thiscall`s, which preserve `ebx`, `esi`, `edi`
    and `ebp`.
    """
    a.label("cast")
    # Which caller armed this cooldown decides whether anybody used the power. Two did not.
    a.emit(0x8B, 0x45, 0x04)  # mov eax, [ebp+4]                 the return address
    a.emit(0x3D, _u32(MODULE_CTOR_RETURN))  # cmp eax, <the constructor>
    a.jcc(JE, "c_stock")
    a.emit(0x3D, _u32(TRIGGER_WALK_RETURN))  # cmp eax, <the OnTriggerRecharge walk>
    a.jcc(JE, "c_stock")

    # The template, exactly as `startPowerRecharge` itself resolves it twice over.
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0xFF, 0x50, SPI_VTABLE_TEMPLATE_SLOT)  # call [eax+0x18]   getSpecialPowerTemplate
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "c_stock")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "c_stock")
    a.emit(0x8B, 0x88, _u32(TEMPLATE_CHARGE_NUMBER))  # mov ecx, [eax+0x88]     ChargeNumber
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JLE, "c_stock")  # not a charge power: the stock five bytes, verbatim

    # [esp]=template [esp+4]=N [esp+8]=short [esp+0xc]=now [esp+0x10]=interval
    a.emit(0x83, 0xEC, 0x14)  # sub esp, 0x14
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.emit(0x89, 0x4C, 0x24, 0x04)  # mov [esp+4], ecx
    a.emit(0x89, 0x7C, 0x24, 0x10)  # mov [esp+0x10], edi

    # short = max(1, ReloadTimeBetweenCharge * interval / ReloadTime): the modifier the engine
    # baked into `interval` applied to the other keyword, in integers, with the standard
    # pre-division overflow guard because a `div` whose quotient does not fit raises #DE. Doing it
    # this way rather than with a second `fild`/`fmul`/`ftol` keeps every number this patch writes
    # derived from one the engine computed, so the two cannot disagree by a ULP.
    a.emit(0x8B, 0x80, _u32(TEMPLATE_RELOAD_BETWEEN))  # mov eax, [eax+0x8c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JLE, "c_short_min")
    a.emit(0x8B, 0x0C, 0x24)  # mov ecx, [esp]
    a.emit(0x8B, 0x49, TEMPLATE_RELOAD_TIME)  # mov ecx, [ecx+0x20]      ReloadTime, frames
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JLE, "c_short_have")  # nothing to scale by: the keyword's own frames
    a.emit(0xF7, 0xE7)  # mul edi                                edx:eax = between * interval
    a.emit(0x3B, 0xD1)  # cmp edx, ecx
    a.jcc(JAE, "c_short_raw")  # the quotient would not fit
    a.emit(0xF7, 0xF1)  # div ecx
    a.jmp("c_short_have")

    a.label("c_short_raw")
    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
    a.emit(0x8B, 0x80, _u32(TEMPLATE_RELOAD_BETWEEN))  # mov eax, [eax+0x8c]

    a.label("c_short_have")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JG, "c_short_ok")
    a.label("c_short_min")
    a.emit(0xB8, _u32(1))  # mov eax, 1                          the engine's own >= 1 clamp
    a.label("c_short_ok")
    a.emit(0x89, 0x44, 0x24, 0x08)  # mov [esp+8], eax

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x89, 0x44, 0x24, 0x0C)  # mov [esp+0xc], eax         now

    # Fold the refills that have landed since the last cast, then write the result back.
    a.emit(0x50)  # push eax                                     now
    a.emit(0xFF, 0x74, 0x24, 0x14)  # push dword [esp+0x14]      interval
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push dword [esp+8]         the template
    a.emit(0x56)  # push esi                                     the interface
    a.call("fold")  # -> eax = spent', edx = deadline'

    # Spend one charge. The cap can only be reached by a cast that did not come through
    # `readyFrame`, and clamping is cheaper than reasoning about it.
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x3B, 0x4C, 0x24, 0x04)  # cmp ecx, [esp+4]
    a.jcc(JAE, "c_capped")
    a.emit(0x41)  # inc ecx
    a.label("c_capped")
    a.emit(0x88, 0x4E, SPI_SPENT)  # mov [esi+0x21], cl

    # The refill clock starts the moment the first charge goes missing, so it is seeded only when
    # no cycle is already running.
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JNE, "c_cycle_running")
    a.emit(0x8B, 0x54, 0x24, 0x0C)  # mov edx, [esp+0xc]
    a.emit(0x03, 0x54, 0x24, 0x10)  # add edx, [esp+0x10]        now + interval
    a.label("c_cycle_running")

    # readyFrame: the short cooldown while charges remain, else max(deadline, now + short).
    a.emit(0x8B, 0x44, 0x24, 0x0C)  # mov eax, [esp+0xc]
    a.emit(0x03, 0x44, 0x24, 0x08)  # add eax, [esp+8]
    a.emit(0x3B, 0x4C, 0x24, 0x04)  # cmp ecx, [esp+4]
    a.jcc(JB, "c_ready")  # charges remain
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JAE, "c_ready")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label("c_ready")
    a.emit(0x89, 0x46, SPI_READY_FRAME)  # mov [esi+8], eax
    a.emit(0x2B, 0x44, 0x24, 0x0C)  # sub eax, [esp+0xc]
    a.emit(0x89, 0x46, SPI_DURATION)  # mov [esi+4], eax         duration = readyFrame - now

    # The deadline goes back into +0x19..+0x1B with the recharge flag at +0x18 preserved.
    a.emit(0x0F, 0xB6, 0x46, SPI_FLAG)  # movzx eax, byte [esi+0x18]
    a.emit(0xC1, 0xE2, SPI_DEADLINE_SHIFT)  # shl edx, 8
    a.emit(0x0B, 0xC2)  # or eax, edx
    a.emit(0x89, 0x46, SPI_FLAG)  # mov [esi+0x18], eax
    a.emit(0x83, 0xC4, 0x14)  # add esp, 0x14
    a.jmp_absolute(RECHARGE_DONE)

    a.label("c_stock")
    a.emit(RECHARGE_HOOK_BYTES)  # the displaced instruction, verbatim
    a.jmp_absolute(RECHARGE_STOCK_RESUME)


def _emit_interval(a: Asm) -> None:
    """``interval(tmpl)``: `max(1, ftol(ReloadTime * m))` in `eax`, recomputed at hover time.

    `ebx` is the final-override template and the description builder's frame is still `ebp`, which
    is where the `Object` and the `Player` come from. Transcribed from `startPowerRecharge`
    (`0x00896E87`..`0x00896F07`) rather than derived, so the readout cannot disagree with the cast
    about how long a refill takes.
    """
    a.label("interval")
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0xC7, 0x04, 0x24, _u32(0x3F800000))  # mov dword [esp], 1.0f      the multiplier
    a.emit(0xC7, 0x44, 0x24, 0x04, _u32(0x3F800000))  # mov dword [esp+4], 1.0f   the discount

    a.emit(0x8B, 0x4D, _EBP_OBJECT)  # mov ecx, [ebp-0x1c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "i_no_object")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8D, 0x44, 0x24, 0x08)  # lea eax, [esp+8]           -> the multiplier local
    a.emit(0x50)  # push eax
    a.emit(0x6A, MODIFIER_TYPE_RECHARGE_TIME)  # push 0xc
    a.call_absolute(GET_MODIFIER_MULTIPLIER)  # ret 0x10, and it eats ecx

    a.label("i_no_object")
    a.emit(0x8B, 0x53, TEMPLATE_FLAGS)  # mov edx, [ebx+0x18]
    a.emit(0xC1, 0xEA, RESPECT_RECHARGE_TIME_DISCOUNT_SHIFT)  # shr edx, 5
    a.emit(0xF6, 0xC2, 0x01)  # test dl, 1
    a.jcc(JE, "i_no_discount")
    a.emit(0x8B, 0x4D, _EBP_PLAYER)  # mov ecx, [ebp-0x20]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "i_no_discount")
    a.call_absolute(PLAYER_RECHARGE_MODIFIER)  # fld [Player+0x718]
    a.emit(0xD8, 0x05, _u32(FLOAT_ONE))  # fadd dword [1.0f]
    a.emit(0xD9, 0x5C, 0x24, 0x04)  # fstp dword [esp+4]

    a.label("i_no_discount")
    a.emit(0x8B, 0x43, TEMPLATE_RELOAD_TIME)  # mov eax, [ebx+0x20]
    a.emit(0x50)  # push eax
    a.emit(0xDB, 0x04, 0x24)  # fild dword [esp]
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "i_positive")
    a.emit(0xD8, 0x05, _u32(FLOAT_U32_FIXUP))  # fadd dword [2^32]
    a.label("i_positive")
    a.emit(0xD8, 0x4C, 0x24, 0x04)  # fmul dword [esp+4]         the player discount
    a.emit(0xD8, 0x0C, 0x24)  # fmul dword [esp]                 the attribute multiplier
    a.call_absolute(FTOL)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JG, "i_out")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.label("i_out")
    a.emit(0xC3)  # ret


def _emit_line(a: Asm) -> None:
    """``line(key, charges, total, frames, want_seconds)``. Stdcall, `ret 0x14`. Appends one line
    to the description the builder keeps at `ebp-0x18`, or nothing at all.

    `ebp` is the description builder's frame throughout the cave - nothing here touches it - so the
    description is reachable by the same displacement the builder's own folds use. Three locals live
    below `esp`: the fetch's `exists` out-parameter, the fetched format string (it has to survive
    the separator's `concat`), and the line being built.
    """
    a.label("line")
    a.emit(0x83, 0xEC, 0x0C)  # sub esp, 0xc
    # [esp]=exists [esp+4]=fmt [esp+8]=the line  [esp+0xc]=ret
    # [esp+0x10]=key [esp+0x14]=charges [esp+0x18]=total [esp+0x1c]=frames [esp+0x20]=want_seconds
    a.emit(0x83, 0x24, 0x24, 0x00)  # and dword [esp], 0
    a.emit(0x83, 0x64, 0x24, 0x08, 0x00)  # and dword [esp+8], 0   an empty UnicodeString

    # TheGameText->fetch(key, &exists). `__thiscall`, `ret 8`, and the string it returns is not
    # owned by the caller - which is why the stock sites destroy nothing.
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x51)  # push ecx                                     -> &exists
    a.emit(0xFF, 0x74, 0x24, 0x14)  # push dword [esp+0x14]      the key
    a.emit(0x8B, 0x0D, _u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GAME_TEXT_FORMAT_SLOT)  # call [eax+0x44]
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax

    # The whole line is dropped when the string table has no such key, separator included.
    a.emit(0x83, 0x3C, 0x24, 0x00)  # cmp dword [esp], 0
    a.jcc(JE, "n_drop")

    # The engine's own "is there anything to separate from" test, from the two folds at
    # `0x008080AE` and `0x008080FB`.
    a.emit(0x8B, 0x4D, _EBP_TEXT)  # mov ecx, [ebp-0x18]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "n_no_separator")
    a.emit(0x66, 0x83, 0x79, 0x04, 0x00)  # cmp word [ecx+4], 0
    a.jcc(JE, "n_no_separator")
    a.emit(0x68, _u32(WIDE_NEWLINE))  # push <L"\n">
    a.emit(0x8D, 0x4D, _EBP_TEXT)  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_CONCAT_WIDE)  # thiscall, ret 4

    a.label("n_no_separator")
    # `UNICODE_STRING_CONCAT` **replaces** its destination - it ends in a `vswprintf` into a scratch
    # buffer and then `set`s - so the line is built in a local of its own and joined to the
    # description with `concat`. Formatting straight into `ebp-0x18` would delete the description.
    a.emit(0x8B, 0x44, 0x24, 0x14)  # mov eax, [esp+0x14]        charges
    a.emit(0x8B, 0x54, 0x24, 0x18)  # mov edx, [esp+0x18]        total
    a.emit(0x8B, 0x4C, 0x24, 0x04)  # mov ecx, [esp+4]           the format string
    a.emit(0x83, 0x7C, 0x24, 0x20, 0x00)  # cmp dword [esp+0x20], 0
    a.jcc(JE, "n_no_seconds")

    # A `double` vararg, the way `CONTROLBAR:UnderConstructionDesc` passes one at `0x00677E62`.
    a.emit(0xDB, 0x44, 0x24, 0x1C)  # fild dword [esp+0x1c]      the frame count
    a.emit(0xDA, 0x35, _u32(LOGIC_FRAMES_PER_SECOND))  # fidiv dword [logic fps]  -> seconds
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0xDD, 0x1C, 0x24)  # fstp qword [esp]                 the last argument, pushed first
    a.emit(0x52)  # push edx                                     total
    a.emit(0x50)  # push eax                                     charges
    a.emit(0x51)  # push ecx                                     the format string
    a.emit(0x8D, 0x4C, 0x24, 0x1C)  # lea ecx, [esp+0x1c]        -> the line local
    a.emit(0x51)  # push ecx                                     the destination
    a.call_absolute(UNICODE_STRING_CONCAT)  # cdecl
    a.emit(0x83, 0xC4, 0x18)  # add esp, 0x18   the double, two ints, the format's two arguments
    a.jmp("n_built")

    a.label("n_no_seconds")
    a.emit(0x52)  # push edx                                     total
    a.emit(0x50)  # push eax                                     charges
    a.emit(0x51)  # push ecx                                     the format string
    a.emit(0x8D, 0x4C, 0x24, 0x14)  # lea ecx, [esp+0x14]        -> the line local
    a.emit(0x51)  # push ecx
    a.call_absolute(UNICODE_STRING_CONCAT)  # cdecl
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10   two ints and the format's two arguments

    a.label("n_built")
    a.emit(0x8D, 0x44, 0x24, 0x08)  # lea eax, [esp+8]           -> the line
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x4D, _EBP_TEXT)  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_APPEND)  # concat(const UnicodeString &), thiscall, ret 4
    # And release the buffer it took. `n_drop` skips this deliberately: it is reached before the
    # format, with the local still the zero it was initialised to and owning nothing.
    a.emit(0x8D, 0x4C, 0x24, 0x08)  # lea ecx, [esp+8]
    a.call_absolute(UNICODE_STRING_DESTRUCT)  # ~UnicodeString, thiscall, no arguments

    a.label("n_drop")
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0xC2, 0x14, 0x00)  # ret 0x14


def _emit_description(a: Asm) -> None:
    """The readout, hooked onto the description builder's special-power case.

    The case is entered with `ecx` = the button's GUI command and `eax` = the `CommandButton`; the
    stock body three bytes along dereferences `[eax+0x44]`, so reading the button out of `eax` here
    is exactly as safe as what the engine does with it. `pushad` because the case falls through into
    stock code that wants both registers back.
    """
    a.label("description")
    a.emit(0x83, 0xF9, GUI_COMMAND_SPECIAL_POWER)  # cmp ecx, 0x18   the displaced compare
    a.jcc(JE, "d_special_power")
    a.jmp_absolute(DESCRIPTION_CASE_NOT_TAKEN)  # the displaced `jne`

    a.label("d_special_power")
    a.emit(0x60)  # pushad
    a.emit(0x83, 0xEC, 0x14)  # sub esp, 0x14
    # [esp]=now [esp+4]=N [esp+8]=the interface [esp+0xc], [esp+0x10] spare
    a.emit(0x8B, 0x58, COMMAND_BUTTON_SPECIAL_POWER)  # mov ebx, [eax+0x44]  the raw template
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "d_out")
    a.emit(0x8B, 0x4D, _EBP_OBJECT)  # mov ecx, [ebp-0x1c]       the Object
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "d_out")
    a.emit(0x53)  # push ebx
    a.call_absolute(GET_SPECIAL_POWER_MODULE)  # ret 4 -> the special-power interface, or NULL
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "d_out")
    # Fail closed on the other implementation of `startPowerRecharge`: its ready frame is at +0x04
    # and it has none of the state below.
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x81, 0x7A, SPI_VTABLE_RECHARGE_SLOT, _u32(START_POWER_RECHARGE))  # cmp [edx+0x3c], ..
    a.jcc(JNE, "d_out")
    a.emit(0x89, 0x44, 0x24, 0x08)  # mov [esp+8], eax           the interface

    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "d_out")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                           the final-override template
    a.emit(0x8B, 0x88, _u32(TEMPLATE_CHARGE_NUMBER))  # mov ecx, [eax+0x88]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JLE, "d_out")  # not a charge power: no line
    a.emit(0x89, 0x4C, 0x24, 0x04)  # mov [esp+4], ecx           N

    a.call("interval")  # -> eax
    a.emit(0x8B, 0xF8)  # mov edi, eax                           the interval
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax                   now

    a.emit(0x50)  # push eax                                     now
    a.emit(0x57)  # push edi                                     interval
    a.emit(0x53)  # push ebx                                     the template
    a.emit(0xFF, 0x74, 0x24, 0x14)  # push dword [esp+0x14]      the interface
    a.call("fold")  # -> eax = spent', edx = deadline'   (writes nothing)

    a.emit(0x8B, 0x4C, 0x24, 0x04)  # mov ecx, [esp+4]           N
    a.emit(0x2B, 0xC8)  # sub ecx, eax                           charges left = N - spent'
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "d_full")

    a.emit(0x2B, 0x14, 0x24)  # sub edx, [esp]                   frames until the next charge
    a.emit(0x6A, 0x01)  # push 1                                 want_seconds
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]       N
    a.emit(0x51)  # push ecx
    a.emit(0x68, _u32(a.label_va("key_recharging")))  # push <TOOLTIP:...Recharging>
    a.call("line")
    a.jmp("d_out")

    a.label("d_full")
    a.emit(0x6A, 0x00)  # push 0                                 want_seconds
    a.emit(0x6A, 0x00)  # push 0                                 no frames to report
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]       N
    a.emit(0x51)  # push ecx
    a.emit(0x68, _u32(a.label_va("key_charges")))  # push <TOOLTIP:SpecialPowerCharges>
    a.call("line")

    a.label("d_out")
    a.emit(0x83, 0xC4, 0x14)  # add esp, 0x14
    a.emit(0x61)  # popad
    a.jmp_absolute(DESCRIPTION_UNIT_COST_BODY)  # on into the stock UnitCost line


def _emit(a: Asm, entries: tuple[Entry, ...]) -> None:
    """The whole cave: its data, then its routines.

    Data comes first so that the code emitted after it can name a string or the table by its final
    address - `Asm.label_va` can only answer for a label that has already been placed.
    """
    a.label("key_charges")
    a.emit(KEY_CHARGES.encode("ascii") + b"\x00")
    a.label("key_recharging")
    a.emit(KEY_CHARGES_RECHARGING.encode("ascii") + b"\x00")
    for keyword in (KEYWORD_CHARGE_NUMBER, KEYWORD_RELOAD_BETWEEN, KEYWORD_REPLENISH_ALL):
        a.label(f"kw_{keyword}")
        a.emit(keyword.encode("ascii") + b"\x00")
    while len(a.buf) % 4:  # the table's dwords want alignment; costs at most three bytes
        a.emit(0x00)

    a.label("table")
    a.emit(
        build_table(
            entries,
            a.label_va(f"kw_{KEYWORD_CHARGE_NUMBER}"),
            a.label_va(f"kw_{KEYWORD_RELOAD_BETWEEN}"),
            a.label_va(f"kw_{KEYWORD_REPLENISH_ALL}"),
        )
    )

    a.label("ctor")
    a.emit(TEMPLATE_CTOR_TAIL_BYTES)  # the displaced store, first
    for offset in (TEMPLATE_CHARGE_NUMBER, TEMPLATE_RELOAD_BETWEEN, TEMPLATE_REPLENISH_ALL):
        a.emit(0x89, 0x9E, _u32(offset))  # mov dword [esi+off], ebx    ebx is the ctor's zero
    a.jmp_absolute(TEMPLATE_CTOR_TAIL_RESUME)

    a.label("copy")
    # `ebp` is the *source* template in the copy constructor, not a frame pointer, and `eax` is the
    # scratch register the copies either side of this use.
    for offset in (TEMPLATE_CHARGE_NUMBER, TEMPLATE_RELOAD_BETWEEN, TEMPLATE_REPLENISH_ALL):
        a.emit(0x8B, 0x85, _u32(offset))  # mov eax, [ebp+off]
        a.emit(0x89, 0x83, _u32(offset))  # mov [ebx+off], eax
    a.emit(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES)  # the displaced epilogue

    _emit_cast(a)
    _emit_description(a)
    _emit_interval(a)
    _emit_line(a)
    _emit_fold(a)


class SpecialPowerChargesPatch(Patch):
    """Bank several casts of a special power behind a short cooldown, with a long refill."""

    name = "special-power-charges"
    author = "officialNecro"
    experimental = True
    description = (
        "Give a special power charges: SpecialPower ChargeNumber = N banks N casts behind "
        "ReloadTimeBetweenCharge (a short cooldown), and ReloadTime becomes the time to regain "
        "one charge, running from the moment the first charge goes missing. "
        "ReplenishAllChargesOnReloadTime = Yes returns the whole bank at once instead. A power "
        "that does not set ChargeNumber is unaffected. The button description gains a charge "
        "readout once the mod adds its .str/.csf key - TOOLTIP:SpecialPowerCharges taking two "
        "%d, and TOOLTIP:SpecialPowerChargesRecharging taking two %d and a %.1f of seconds"
    )

    # --- applying ---------------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        # Before the anchors, because applying rewrites bytes several of them cover: a second run
        # would otherwise fail as "not the build this patch was derived against", which is true of
        # the bytes and misleading about the cause.
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(
                f"this image already carries a {SECTION_NAME} section - the patch is already "
                "applied, and applying it twice would install a second copy of all three fields"
            )
        self._check_anchors(data)
        self._check_dispatch(data)
        entries = self._check_table(data, self._resolve(data))

        base_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: self._assemble(base, entries).finish(),
            _CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, base_va, entries):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _assemble(base_va: int, entries: tuple[Entry, ...]) -> Asm:
        a = Asm(base_va)
        _emit(a, entries)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self, data: bytes | bytearray, base_va: int, entries: tuple[Entry, ...]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        ``(file offset, expected, replacement, note)`` - one list, so :meth:`apply` writes exactly
        what :meth:`verify` asserts."""
        a = self._assemble(base_va, entries)
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                _offset(data, MODULE_CTOR_FLAG),
                MODULE_CTOR_FLAG_BYTES,
                rewritten_module_ctor_flag(),
                "SpecialPowerModule ctor -> the refill deadline starts at zero",
            ),
            (
                _offset(data, MODULE_CTOR_HELD),
                MODULE_CTOR_HELD_BYTES,
                rewritten_module_ctor_held(),
                "SpecialPowerModule ctor -> the spent count starts at zero",
            ),
            (
                _offset(data, TEMPLATE_CTOR_TAIL),
                TEMPLATE_CTOR_TAIL_BYTES,
                _jmp(TEMPLATE_CTOR_TAIL, a.label_va("ctor"))
                + b"\x90" * (len(TEMPLATE_CTOR_TAIL_BYTES) - 5),
                f"SpecialPowerTemplate ctor -> the {SECTION_NAME} field defaults",
            ),
            (
                _offset(data, SPECIAL_POWER_TEMPLATE_COPY_TAIL),
                SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
                _jmp(SPECIAL_POWER_TEMPLATE_COPY_TAIL, a.label_va("copy"))
                + b"\x90" * (len(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES) - 5),
                f"SpecialPowerTemplate copy ctor -> the {SECTION_NAME} field copies",
            ),
            (
                _offset(data, RECHARGE_HOOK),
                RECHARGE_HOOK_BYTES,
                _jmp(RECHARGE_HOOK, a.label_va("cast")),
                f"startPowerRecharge's full arm -> the {SECTION_NAME} charge machine",
            ),
            (
                _offset(data, DESCRIPTION_SPECIAL_POWER_CASE),
                DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
                _jmp(DESCRIPTION_SPECIAL_POWER_CASE, a.label_va("description")),
                f"the description's special-power case -> the {SECTION_NAME} readout",
            ),
        ]
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            edits.append(
                (
                    _offset(data, push_va),
                    b"\x68" + _u32(SPECIAL_POWER_TEMPLATE_SIZE),
                    b"\x68" + _u32(NEW_TEMPLATE_SIZE),
                    f"SpecialPowerTemplate allocation 0x{push_va:08x} -> 0x{NEW_TEMPLATE_SIZE:x}",
                )
            )
        table_ref = _u32(a.label_va("table"))
        for ref_va, opcode in zip(
            SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = _offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"SpecialPower field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    # --- the checks applying refuses on ------------------------------------------------------

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `SpecialPower` field table's base VA, as the image currently holds it.

        Read from the two references that name it rather than from the stock constant, so the patch
        appends to whatever is live - which is what makes it compose with `cooldown-through-death`,
        and what makes applying it twice fail cleanly instead of installing a second copy."""
        return resolve_table(
            data,
            SPECIAL_POWER_FIELD_TABLE_REFS,
            SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
            "SpecialPower",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every window this patch reads but never writes still holds its stock bytes.

        A build where one of them moved would still take the patch and still verify - and then call
        whatever now lives at the address, or compare a vtable slot against a function that is no
        longer there."""
        for va, want in {**ANCHORS, **RECHARGE_FORMULA_ANCHORS}.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"0x{va:08x} holds {'nothing mapped' if got is None else got.hex()}, expected "
                    f"{want.hex()} - this is not the build this patch was derived against"
                )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the interface vtable still names `startPowerRecharge` at the slot the
        readout tests. That test is the only thing keeping the readout off a layout whose ready
        frame is somewhere else, so a moved slot has to be a refusal rather than a guess."""
        slot_va = SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT
        target = struct.unpack_from("<I", data, _offset(data, slot_va))[0]
        if target != START_POWER_RECHARGE:
            raise ValueError(
                f"vtable slot 0x{slot_va:08x} dispatches to 0x{target:08x}, not "
                f"0x{START_POWER_RECHARGE:08x} - the flavour test would match nothing"
            )

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build, for the three keywords and
        for anything that has already grown the struct.

        A duplicate row would parse - the reader takes the first match - so the field would exist
        and silently do nothing."""
        entries = read_field_table(data, table_va)
        by_name = {_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: SpecialPower.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        for keyword in (KEYWORD_CHARGE_NUMBER, KEYWORD_RELOAD_BETWEEN, KEYWORD_REPLENISH_ALL):
            if keyword in by_name:
                raise ValueError(
                    f"SpecialPower already has a {keyword!r} field - this patch is already "
                    "applied, or another patch has added the same field"
                )
        highest = max(offset for _n, _f, _u, offset in entries)
        if highest >= TEMPLATE_CHARGE_NUMBER:
            raise ValueError(
                f"the SpecialPower table already uses offset {highest:#x}, at or past the "
                f"{TEMPLATE_CHARGE_NUMBER:#x} this patch adds - another patch has already grown "
                "SpecialPowerTemplate (hero-mana does), and the two would share a field"
            )
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            off = _offset(data, push_va)
            allocation = bytes(data[off : off + 5])
            if allocation != b"\x68" + _u32(SPECIAL_POWER_TEMPLATE_SIZE):
                raise ValueError(
                    f"the SpecialPowerTemplate allocation at 0x{push_va:08x} holds "
                    f"{allocation.hex()}, not a push of {SPECIAL_POWER_TEMPLATE_SIZE:#x} - the "
                    "struct has already been grown, or this is not the expected build"
                )
        return entries

    # --- reading it back ----------------------------------------------------------------------

    def ini_surface(self) -> Engine:
        """The three fields this patch adds to `SpecialPower`. The constructor zeroes all three, so
        `ChargeNumber` defaults to 0 - which is stock behaviour, and what makes them opt-in.

        `ReloadTimeBetweenCharge` is declared `Int` for the same reason `ReloadTime` is: what a mod
        writes is an integer of milliseconds, and the conversion to frames happens inside the parse
        function, past anything `sage_ini` models."""
        return Engine(
            fields=(
                FieldDelta("SpecialPower", KEYWORD_CHARGE_NUMBER, "Int", 0, self.name),
                FieldDelta("SpecialPower", KEYWORD_RELOAD_BETWEEN, "Int", 0, self.name),
                FieldDelta("SpecialPower", KEYWORD_REPLENISH_ALL, "Bool", False, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch. Reads only via ``struct`` and the
        section table, so it needs no disassembler.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying another patch's section too verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        try:
            live = read_field_table(data, self._resolve(data))
            preceding = entries_before(data, live, KEYWORD_CHARGE_NUMBER)
            if preceding is None:
                return [f"the live SpecialPower table does not name {KEYWORD_CHARGE_NUMBER!r}"]
            a = self._assemble(section_va, preceding)
            problems = self._verify_cave(data, a, section_va, vsize)
            problems += self._verify_live_rows(data, live, a)
            problems += self._verify_sites(data, a)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    @staticmethod
    def _verify_cave(data: bytes | bytearray, a: Asm, section_va: int, vsize: int) -> list[str]:
        code = a.finish()
        if len(code) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the routines"]
        off = _offset(data, section_va)
        if bytes(data[off : off + len(code)]) != code:
            return [f"the {SECTION_NAME} cave is not what this patch builds"]
        return []

    @staticmethod
    def _verify_live_rows(data: bytes | bytearray, live: tuple[Entry, ...], a: Asm) -> list[str]:
        """All three fields are still parsed, out of whatever table the engine now reads.

        Deliberately *not* "the references still name this patch's own table". A later patch that
        rebuilds the same table copies these rows into its own and repoints the references at that;
        what has to hold is that the live table still carries them, pointing at the keyword strings
        in this cave and writing the offsets this cave's code reads."""
        problems: list[str] = []
        wanted = (
            (KEYWORD_CHARGE_NUMBER, INI_PARSE_INT, TEMPLATE_CHARGE_NUMBER),
            (KEYWORD_RELOAD_BETWEEN, INI_PARSE_DURATION, TEMPLATE_RELOAD_BETWEEN),
            (KEYWORD_REPLENISH_ALL, INI_PARSE_BOOL, TEMPLATE_REPLENISH_ALL),
        )
        for keyword, parse_fn, offset in wanted:
            row = next((entry for entry in live if _cstring(data, entry[0]) == keyword), None)
            if row is None:
                problems.append(f"the live SpecialPower table no longer parses {keyword!r}")
            elif (row[0], row[1], row[3]) != (a.label_va(f"kw_{keyword}"), parse_fn, offset):
                problems.append(
                    f"the live {keyword!r} row is not this patch's field at "
                    f"SpecialPower+0x{offset:02x} (holds name 0x{row[0]:08x}, fn 0x{row[1]:08x}, "
                    f"offset 0x{row[3]:02x})"
                )
        return problems

    def _verify_sites(self, data: bytes | bytearray, a: Asm) -> list[str]:
        problems: list[str] = []
        checks: list[tuple[int, bytes, str]] = [
            (
                MODULE_CTOR_FLAG,
                rewritten_module_ctor_flag(),
                "the module ctor does not zero the refill deadline",
            ),
            (
                MODULE_CTOR_HELD,
                rewritten_module_ctor_held(),
                "the module ctor does not zero the spent count",
            ),
            (
                TEMPLATE_CTOR_TAIL,
                _jmp(TEMPLATE_CTOR_TAIL, a.label_va("ctor"))
                + b"\x90" * (len(TEMPLATE_CTOR_TAIL_BYTES) - 5),
                "the template ctor is not hooked to the field defaults",
            ),
            (
                SPECIAL_POWER_TEMPLATE_COPY_TAIL,
                _jmp(SPECIAL_POWER_TEMPLATE_COPY_TAIL, a.label_va("copy")),
                "the template copy ctor is not hooked to the field copies",
            ),
            (
                RECHARGE_HOOK,
                _jmp(RECHARGE_HOOK, a.label_va("cast")),
                "startPowerRecharge's full arm is not hooked to the charge machine",
            ),
            (
                DESCRIPTION_SPECIAL_POWER_CASE,
                _jmp(DESCRIPTION_SPECIAL_POWER_CASE, a.label_va("description")),
                "the description's special-power case is not hooked to the readout",
            ),
        ]
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            checks.append(
                (
                    push_va,
                    b"\x68" + _u32(NEW_TEMPLATE_SIZE),
                    f"the allocation at 0x{push_va:08x} still asks for the ungrown struct",
                )
            )
        for va, want, complaint in checks:
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {complaint} (holds {got.hex()})")
        return problems


def _cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    """The NUL-terminated ASCII string at ``va``, or None if it is unmapped or not one."""
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    if end < 0:
        return None
    try:
        return bytes(data[off : off + end]).decode("ascii")
    except UnicodeDecodeError:
        return None
