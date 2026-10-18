# `SpecialPowerRefundUpgrade`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`).

This is the write-up for **`special-power-refund-upgrade`** and its editor twin
**`special-power-refund-upgrade-wb`**,
[`patches/special_power_refund_upgrade.py`](../patches/special_power_refund_upgrade.py), with tests
in
[`tests/sage_patch/test_special_power_refund_upgrade.py`](../../tests/sage_patch/test_special_power_refund_upgrade.py).

```sh
sage-patch apply special-power-refund-upgrade --in game.dat.backup --out game.dat
sage-patch apply special-power-refund-upgrade-wb --in Worldbuilder.exe --out Worldbuilder_patched.exe
```

**Status: built and static-verified, not run in a game.** Both halves apply, verify and are
detected on the real binaries: the repo's `game.dat`, a `game.dat` carrying Edain's full patch set,
and RotWK 2.01's `Worldbuilder.exe` with and without `grant-science-upgrade-wb`. Apply has been run
under an emulator against stand-ins for the engine lookups (§5). §7 is the in-game checklist still
to run.

**What it does:** an upgrade module that gives part of a spellbook power's cooldown back, or,
with `RestartCooldown = Yes`, starts that cooldown over (§3.4).

```ini
Behavior = SpecialPowerRefundUpgrade ModuleTag_MerchantRefund
    TriggeredBy   = Upgrade_MerchantLeaves
    ConflictsWith = Upgrade_MerchantOrder
    SpecialPower  = SpellBookSummonTravellingMerchant
    RefundPercent = 50%
End
```

When the module fires, the named power on the owning player's spellbook comes ready sooner by
`RefundPercent` of the cooldown it is running. The case it was written for: a summon that is only
worth its cooldown if the player then does something with it, and that should cost less when they
did not.

The restart mode is for the opposite case: a power whose result the player can hand back, such as
a permanent summon with a "send away" upgrade button on the summoned object. Sending it away
should put the power back on cooldown, even though the cooldown from the original cast finished
long ago:

```ini
Behavior = SpecialPowerRefundUpgrade ModuleTag_SendAwayCooldown
    TriggeredBy     = Upgrade_SendAwayEnt
    SpecialPower    = SpellBookSummonEnt
    RestartCooldown = Yes
End
```

Put it on the summoned object, beside whatever removes the object on the same upgrade. Upgrade
modules fire at once and object removal waits for the end of the frame, so the module still finds
its object and owner.

## 1. Why INI cannot do this today

`SpecialAbilityUpdate::startPowerRecharge` (`0x00896E31`) computes a cooldown once, when the power
fires, and stores an absolute ready frame ([`recharge-rescale.md`](recharge-rescale.md) §1). The
INI tools that touch a cooldown all act at that moment or replace it wholesale:

| tool | what it does | why it is not a refund |
|---|---|---|
| `SpellRechargeModifierUpgrade` | scales the **next** recharge that starts | the one running is already a frame number |
| `OnTriggerRechargeSpecialPower` | **starts** the named power's cooldown | the opposite direction ([`trigger-recharge-list.md`](trigger-recharge-list.md)) |
| `SpecialPowerTimerRefreshSpecialPower` | makes powers ready | all or nothing, and not one named spell |

`startPowerRecharge` does have a partial arm, taken when its argument is below `1.0`
(`0x00896F16`..`0x00896F73`). It is not what this patch uses: it re-derives the ready frame from
`getPercentReady`, does nothing when that is exactly `0`, and nothing in INI reaches it.

## 2. The engine already has the operation

Map scripts can move a cooldown. Four script actions do it, and one of them is aimed at exactly the
object this module needs:

| action | id | handler | what it writes |
|---|---|---|---|
| `NAMED_SET_SPECIAL_POWER_COUNTDOWN` | 169 | `0x007C495B` | `now + seconds` on a named unit's power |
| `NAMED_ADD_SPECIAL_POWER_COUNTDOWN` | 170 | `0x007C4A34` | `readyFrame + seconds` on a named unit's power |
| `PLAYER_SET_SPECIAL_POWER_COUNTDOWN` | 578 | `0x007C49BC` | `now + seconds` on a power of the player's **spellbook** |

`PLAYER_SET_SPECIAL_POWER_COUNTDOWN`, annotated:

```
007c49c9  call 0x49f474            ; player name -> key
007c49d5  call 0x6a8466            ; -> Player*
007c49e0  call 0x6ad0f8            ; Player -> its spellbook Object*          (PLAYER_GET_SPELLBOOK_OBJECT)
007c49eb  push ecx / mov ecx, esp
007c49f1  push dword [ebp+0xc]
007c49f4  call 0x435f30            ; copy the power name into the argument slot
007c49f9  mov  ecx, [0xde878c]     ; TheSpecialPowerStore
007c49ff  call 0x69c146            ; -> SpecialPowerTemplate*, NULL if unknown
007c4a0b  call 0x68c26d            ; Object::getSpecialPowerModule(template) -> interface, or NULL
007c4a14  mov  ecx, [0xd9f608] / imul ecx, [ebp+0x10] / add ecx, [TheGameLogic+0x40]
007c4a2c  call dword [edx+0x20]    ; setReadyFrame(now + seconds * fps)
```

| address | what | convention |
|---|---|---|
| `0x006AD0F8` | `Player` -> its spellbook object, cached by `ObjectID` at `Player+0x710` | `__thiscall`, no arguments |
| `0x0069C146` | `SpecialPowerStore::findSpecialPowerTemplate(AsciiString)` | `__thiscall` on `[0x00DE878C]`, `ret 4`; the name is **by value** and the callee destroys it |
| `0x0068C26D` | `Object::getSpecialPowerModule(const SpecialPowerTemplate *)` | `__thiscall`, `ret 4`; walks `Object+0x24C` |
| interface slot `+0x20` | `setReadyFrame` (`0x0099344A`): `mov eax, [esp+4]` / `mov [ecx+8], eax` / `ret 4` | `__thiscall` |

`setReadyFrame` is one store. The cooldown's own length, at interface `+0x04`, is left as it was,
and `getPercentReady` is `1 - (readyFrame - now) / duration`, recomputed on every call. So moving
the ready frame moves the button clock by the same share and it carries on from there.

A module that makes the same three lookups and the same write therefore behaves like the script
action, with no new game logic. What it adds is where the new frame comes from: a share of the
running cooldown instead of a number of seconds.

## 3. The module

It is [`grant-science-upgrade`](grant-science-upgrade.md)'s registration skeleton: a
`TooltipUpgrade` layout twin, so the stock `UpgradeMux` evaluates `TriggeredBy` / `ConflictsWith` /
`RequiresAllTriggers` / `RequiresAllConflictingTriggers`, and copied vtables in which only Apply
(`+0x28`) and Unapply (`+0x20`) differ. That write-up asked the third user of the skeleton to
extract it, and this is the third: it now lives in
[`patches/utils/tooltip_twin.py`](../patches/utils/tooltip_twin.py), and `grant-science-upgrade`
is built from it too. Its output did not change by a byte.

### 3.1 Where the three fields live

| field | parser | ModuleData offset |
|---|---|---|
| `SpecialPower` | stock `AsciiString` parser `0x0042EE5E` | `+0x138` |
| `RefundPercent` | `INI::parsePercentToReal` `0x0042EEFA` | `+0x140` |
| `RestartCooldown` | `INI::parseBool` `0x0042E558` (one byte; the rest is padding) | `+0x144` |

Tooltip's `ModuleData` is `0x140` bytes and ends in **two** `AsciiString`s. Its constructor
(`0x0065563C`) assigns the empty string to both:

```
00655656  lea ecx, [esi+0x138] ... 00655679  call 0x436030
00655667  lea ebx, [esi+0x13c] ... 00655681  call 0x436030
```

`grant-science-upgrade.md` calls `+0x13C` unused, which is true of that module, but the slot is not
free: it is a string with a destructor, and a float stored there would be released as a buffer when
the `ModuleData` is destroyed. So this module's factory asks `operator new` for `0x148` bytes, runs
Tooltip's constructor, and zeroes the last eight (`and dword [esi+0x140], 0` /
`and dword [esi+0x144], 0`). Nothing else has to
change: the engine's `operator new` (`0x0042F6E0`) is a plain heap allocation freed without a size,
and Tooltip's destructor never looks past `+0x13C`.

`parsePercentToReal` reads one token and multiplies by `0.01` (`fmul [0x00BE5600]` at `0x0042EB21`)
before the store, so `50%` is `0.5`.

### 3.2 Apply

`ecx` = `UpgradeMux*`; `Object*` at `[mux-8]` and `ModuleData*` at `[mux-0xC]`. As emitted:

```asm
push ebx / push esi / push edi
mov  esi, ecx
mov  edi, [esi-8]              ; Object*
test edi, edi / je done
mov  ebx, [esi-0Ch]            ; ModuleData*
cmp  dword [ebx+138h], 0 / je done      ; no SpecialPower line
mov  ecx, edi
call 0068B678h                 ; Object::getControllingPlayer
test eax, eax / je done
mov  ecx, eax
call 006AD0F8h                 ; -> the spellbook object
test eax, eax / je done
mov  edi, eax
push ecx / mov ecx, esp        ; the by-value name's slot
lea  eax, [ebx+138h] / push eax
call 00435F30h                 ; AsciiString copy constructor
mov  ecx, [0DE878Ch]
call 0069C146h                 ; findSpecialPowerTemplate
test eax, eax / je done        ; unknown power
push eax / mov ecx, edi
call 0068C26Dh                 ; getSpecialPowerModule
test eax, eax / je done
mov  esi, eax                  ; the interface

mov  eax, [esi]
cmp  dword [eax+3Ch], 00896E31h / jne done   ; only the layout with a duration (3.3)
mov  ecx, esi / call [eax+18h]               ; getSpecialPowerTemplate
test eax, eax / je done
mov  ecx, eax / call 00688D3Ch               ; final override
cmp  byte [eax+59h], 0 / jne done            ; SharedSyncedTimer
cmp  dword [esi+0Ch], 0 / jne done           ; paused

mov  eax, [0DE412Ch]
mov  edi, [eax+40h]            ; now
mov  eax, [esi+8]
cmp  eax, edi / jbe done       ; already ready
cmp  dword [esi+4], 0 / jle done
fild dword [esi+4]             ; duration
fmul dword [ebx+140h]          ; * RefundPercent
call 00A3CFA4h                 ; ftol -> the refund, in frames
test eax, eax / jle done
mov  ecx, [esi+8] / sub ecx, edi   ; frames left
cmp  eax, ecx / jae ready_now
mov  ecx, eax                  ; min(refund, frames left)
ready_now:
mov  eax, [esi+8] / sub eax, ecx
push eax / mov ecx, esi / mov eax, [esi]
call [eax+20h]                 ; setReadyFrame
done:
pop edi / pop esi / pop ebx / ret
```

The refund is `ftol(duration * RefundPercent)`, the same `fild` / `fmul` / `ftol` shape the engine
uses for the cooldown itself, so it truncates as the engine does and is the same on every machine.
`duration` is what `startPowerRecharge` stored, with every discount that applied at the cast
already in it. A refund is therefore a share of the cooldown actually running, not of the
template's `ReloadTime`.

The name is resolved when the module fires, as the script action does. Resolving at parse time
would mean a template pointer in a slot with an `AsciiString` destructor. The cost is that an
unknown name does nothing in game; `sage-lint` reports it instead, because `ini_surface` types
`SpecialPower` as `Ref:specialpowers`.

### 3.3 What Apply leaves alone, and why

| case | test | reason |
|---|---|---|
| the power is ready | `readyFrame <= now` | there is nothing to refund, and a ready frame further in the past changes nothing |
| a refund of zero or less | `ftol(...) <= 0` | this module never lengthens a cooldown; `RefundPercent` absent is `0` |
| a paused power | interface `+0x0C != 0` | the pause path owns `readyFrame` while it is paused (`0x00896756`) |
| a `SharedSyncedTimer` power | template `+0x59` | its timer lives on the `Player` (`0x006AD1B0`), not at interface `+0x08` |
| the second cooldown layout | slot `+0x3C != 0x00896E31` | those three module types keep `readyFrame` at `+0x04` and no duration ([`recharge-rescale.md`](recharge-rescale.md) §7.1) |
| no power of that name on the spellbook | a NULL from any lookup | nothing to act on |

The layout test is the module's own `startPowerRecharge`, the discriminator `recharge-rescale` §5.1
uses, and it fails closed: a vtable holding neither known implementation is skipped.

### 3.4 `RestartCooldown`

Once the module for the named power is found on the spellbook, a set `RestartCooldown` takes a
branch ahead of everything in §3.3:

```asm
cmp  byte [ebx+144h], 0 / je refund
push 3F800000h                 ; 1.0f
mov  ecx, esi / mov eax, [esi]
call [eax+3Ch]                 ; startPowerRecharge(1.0), ret 4
jmp  done
```

That is the module's own `startPowerRecharge`, called the way a cast calls it and the way stock
`OnTriggerRechargeSpecialPower` calls it on another module (`0x00897A2A`..`0x00897A35`: `fld1`,
`fstp [esp]`, `call [eax+0x3C]`, with the interface in `ecx`). So the cooldown restarts at full
length from now, with the discounts that apply today (`recharge-rescale.md` §1).

None of §3.3's checks apply, because none of them protect a call the engine makes itself:

- **A ready power** is the case the mode exists for.
- **A power that never recharged** gets its length from the template, not from a stored duration.
- **A `SharedSyncedTimer` power** is sent to the player's timer by `startPowerRecharge`
  (`0x00896E71`).
- **The second cooldown layout** has its own implementation behind the same slot.
- **A paused power** gets what a cast during the pause would get.

`RestartCooldown` wins over `RefundPercent` when a block writes both.

## 4. Hook sites

The registration stub replays the six arguments of the `addModule` call it displaces, so which
stock module it wraps does not matter, only that no other patch wraps the same one.
`object-image-upgrade` owns `TooltipUpgrade`'s call and `grant-science-upgrade` owns
`AudioLoopUpgrade`'s. Both halves of this patch wrap the **next** one, `RemoveUpgradeUpgrade`'s:

| binary | call | asserted before it |
|---|---|---|
| `game.dat` | `0x0065A862` (`SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL`), `e8 97 c8 ff ff` | `push 0x6505C4`, `push 0x65058C`, `mov ecx, edi`, `mov [ebp-4], 0xD7` |
| `Worldbuilder.exe` | `0x00C75C89` (`WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL`), `e8 32 e0 01 00` | `push 0xC8B8B0`, `push 0xC8B840`, `mov ecx, [ebp-0x4E8]` |

The three patches share callees (the Tooltip factories and constructor) but no edited bytes, and
apply in any order.

The editor half is parser-only: Tooltip's stock runtime factory and the editor's own `ModuleData`
constructor, field-table builder and parsers (`AsciiString` `0x006D4C30`, percent `0x006D4D20`, the
parser its `RepairHealthPercentPerSecond` rows name). Its `ModuleData` grows to `0x148` as the
game's does, because the percent parser writes the same four bytes. The editor's Bool parser has
not been located, and the editor never reads `RestartCooldown`, so that row uses the editor's
`AsciiString` parser. It accepts the token and keeps a string in the four bytes, which Tooltip's
destructor never frees: a few bytes per block, once, when the editor loads. Without it Worldbuilder cannot
parse the block and closes during its loading screen.

## 5. What the emulator run checks

`TestApply` maps the patched cave, the engine's own `ftol`, `getFinalOverride` and `setReadyFrame`
bytes, and stand-ins for the four lookups, then runs Apply:

- half of a 7200-frame cooldown with 5400 frames left leaves 1800, and the duration is untouched;
- the refund scales with `RefundPercent`, stops at ready, and follows a shorter started cooldown;
- `7201 * 50%` refunds 3600 frames, not 3601;
- every row of §3.3, an empty `SpecialPower`, an unknown name, and a missing player, spellbook or
  object change nothing;
- `ebx`, `esi`, `edi` and the stack come back as they went in.

`TestRestart` puts a recorder in interface slot `+0x3C` and checks that `RestartCooldown = Yes`:

- makes exactly one `startPowerRecharge(1.0)` call on the power's interface;
- does so whether the power is ready, recharging, never recharged, paused or on a shared timer;
- ignores any `RefundPercent`;
- does nothing for an unknown power or a missing player, spellbook or module.

What it cannot check is the engine side of each lookup. That is §7.

## 6. Behaviour

- **One refund per firing.** A module fires once per object, as any upgrade module does. A summoned
  object that carries it refunds once per summon.
- **Never taken back.** Unapply is neutral. Losing the upgrade or the object leaves the cooldown
  where the refund put it.
- **The spellbook is the controlling player's when the module fires.**
- **Spellbook powers only.** The module looks on the player's spellbook object, as the script action
  does. A hero's own ability is not reachable; that is a different lookup, not attempted here.
- **Save games:** the ready frame is already in the module's `Xfer`. The module's fired state is
  stock `UpgradeMux` state.
- **Desync / replays:** simulation state, changed the same way on every peer by the same binary.
- **`special-power-charges`:** a refund that makes a charged power ready reads to that patch as a
  refill that landed early ([`special-power-charges.md`](special-power-charges.md) §3.1). Not
  tested together.
- **`description-timers`:** its remaining-time line reads `readyFrame`, so it should follow the
  refund. Not checked.

## 7. To check in a game

1. With `TriggeredBy` met while the power recharges, the spell's button clock jumps forward by the
   refund and the spell becomes castable that much sooner.
2. With the power ready, nothing happens, and the next cast recharges for its full length.
3. `ConflictsWith` naming a **player** upgrade the owner holds: the module must not fire. The
   stock mux is assumed to test player upgrades here; this is the one behaviour the intended use
   depends on that has not been confirmed.
4. `RefundPercent = 100%` makes the power ready at once, and no further.
5. A spell recharging under a `SpellRechargeModifierUpgrade` discount is refunded a share of its
   shortened cooldown.
6. Save mid-cooldown after a refund, reload: the remaining time is the refunded one and no second
   refund fires.
7. A skirmish AI owner's spell is refunded too.
8. With an unknown `SpecialPower` name, the game loads and the module does nothing.
9. `RestartCooldown = Yes` on a summoned object, triggered by its send-away upgrade: summon,
   wait out the cooldown, send the object away. The spell's button goes back on cooldown for its
   full length, with any `SpellRechargeModifierUpgrade` discount applied.
9. Worldbuilder with `special-power-refund-upgrade-wb` loads a mod whose INI uses the block, and
   places the object.
