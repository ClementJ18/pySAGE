# A model condition for "this building is producing"

Recovered against RotWK 2.01 `game.dat` build `2.01.2614.37001`, 2026-07-30. Static analysis
only; the runtime checks at the end are **open**.

**What it adds.** One `ModelConditionFlags` bit, named by the caller (default `PRODUCING`), held
true for exactly as long as a structure's production queue is non-empty — training a unit,
researching an upgrade, or both. Two opt-in extras ride the same trigger: a `WeaponSetFlags` name
(§10) and a `LocomotorSetType` name (§11), neither installed unless asked for. Implemented by
[`patches/production_condition.py`](../patches/production_condition.py).

```ini
; anywhere a model condition is accepted
ModelConditionState = PRODUCING
  Animation = GBFurnace_A_PRD
  Flags     = LOOPING
End
```

## 1. The gap this fills

`ProductionUpdate` already drives `DOOR_1_OPENING` → `WAITING_OPEN` → `CLOSING`, which looks like
the signal — but those run *after* a unit finishes, as the buffer during which it walks out. They
say "a unit just completed", not "a unit is being trained". `ModelConditionUpgrade` likewise fires
on an upgrade's **completion**. Neither expresses queue-non-empty, and neither covers research at
all. There is no stock condition for it.

Confirmed in the binary rather than assumed: `ProductionUpdate::update` sets bit **218**
(`JUST_BUILT`) at `0x008A2B9F` and clears it at `0x008A2D8B`, both on the completion path.

## 2. `ModelConditionFlags` — 591 names in 19 dwords

| address | what | width |
|---|---|---|
| `0x00D9FAD8` | the NULL-terminated name table, **591** entries | `0x93C` |
| `0x00444D95` | `getBitNames()` → `mov eax, 0xd9fad8` | |
| `0x00444DF5` | `getBitCount()` → `mov eax, 0x24f` (591) | |
| `0x00444D7D` / `0x00444D9B` | copy / compare | `0x4C` |
| `0x004B3783` / `0x004B3797` | `any()` / flip-all | `0x13` dwords |
| `0x006632E9` | `testForAny(other)` | `0x13` dwords |
| `0x00444DFB` | name-from-single-bit — **no bound check** | |
| `0x004B8D87` | `xfer` — packs the mask into **74 bytes** | |

19 dwords is 608 bit slots for 591 names, so **17 slots are already allocated and unnamed**.
Nothing grows to hold a 592nd condition.

**The bit lives on the logic-side `Object` at `+0x10C`.** Settled from the
`DisableOnModelCondition` gate at `0x00942490`, which tests `arg1 + 0x10C` where `arg1` is
unambiguously an `Object` — it reads `+0x04` as `ThingTemplate*` and dispatches on the module at
`+0x260`. Corroborated structurally: `0x10C + 19*4 = 0x158`, exactly where the second `Matrix3D`
copy in [`live-object-model.md`](live-object-model.md) begins.

> This closes the open question in [`ai-revive-gate.md`](ai-revive-gate.md) §Scope, which recorded
> the `+0x10C` mask as "not pinned down as the `Drawable` (client) or the `Object` (logic)" and
> deferred the nine model-condition-gated revive slots on that uncertainty. It is the `Object`, so
> gating the AI on it would **not** desync.

### 2a. Serialisation — three paths, and what actually bounds a new condition

> ⚠ **The 74-byte packer is not the savegame.** It is one of three branches and it is not the
> save/load one, so a second condition is *not* a savegame format change. Reading `0x004B8D87`
> alone suggests otherwise — it has no mode check inside it — so follow its single caller.

`ModelConditionFlags::xfer` is `0x004BAEE4`. After `xferVersion` it branches twice:

| branch | selected by | representation |
|---|---|---|
| **blob** | `[Xfer+0x10]` true | 591 bits packed byte-granular into **74 bytes**, `xferUser(buf, 0x4a)` (`0x004B8D87`) |
| **save** | else, `[Xfer+0x08]` true | `countBits()` (`0x004B5D5A`), then one **name string per set bit** |
| **load** | else | memset the mask, read the count, then resolve that many names (`0x004B5DA2` → the parser at `0x004B3B5B`) |

So **savegames store model conditions as a list of names, not as a bit layout.** They carry no
length constant and no count bound, and the load path resolves each name through the very table
this patch extends. Adding conditions therefore does **not** change the savegame format — for one
new condition or for seventeen.

The 74-byte constant lives only in the blob branch, which is *not* save/load. It is most likely
`XferCRC` (that is what a compact deterministic byte image is for, and save/load is demonstrably
the other branch) — **inferred, not proven**; the `[Xfer+0x10]` implementations were not walked.

What that leaves as the real bound:

- **74 bytes is 592 bits exactly**, so bit 591 — the one this patch names — is the last bit the
  blob includes. It needs no constant widened.
- Bits **592–607** are still free in the 19-dword mask and would parse, set, draw and
  save/load correctly, but would fall **outside the blob** unless the two `push 0x4a` are widened.
  The packer's stack buffer is already `sub esp, 0x4c` (76 bytes = 608 bits), so no buffer grows.
- Beyond **608** the mask itself must grow, and `Object+0x10C` is immediately followed by `+0x158`
  — that is an `Object` layout change, not a byte patch.

**One sharp consequence for the patch as shipped.** The load path aborts on a name it cannot
resolve — `0x004BAFDC` falls into `int3` at `0x004BB022`. A save taken while *any* object has
`PRODUCING` set therefore **fatally fails to load on an unpatched binary**, rather than degrading.
A save taken with nothing producing loads fine.

### 2b. You may not need this patch to get a *condition*

The stock table already carries **75 `USER_1`…`USER_75`** conditions — the engine's own
data-driven extension slots, and the `UseUSERModelcondition` module field is its hook for one.

Sweeping `.text` for single-bit `or`/`and`/`test` against `Object+0x10C..0x158` finds **no engine
code that sets or tests any `USER_*` bit**. Two traps made that harder than it sounds, and both
are worth not repeating:

- **Bulk masks swamp the signal.** Counting every set bit of every immediate marks 501 of 591
  conditions as "engine-driven", because a group clear like `and …, 0xF0FFFFFF` touches 28 bits at
  once. Only immediates with exactly one bit set (`or`/`test`) or one bit clear (`and`) name a
  single condition.
- **The displacement range is ambiguous.** `ThingTemplate`'s `KindOf` mask also lives around
  `+0x10C`, so `test byte [eax+0x123], 2` looks like a model-condition read until you notice `eax`
  came from `[reg+0x04]` — the template, not the object. Every apparent `USER_*` hit was one of
  these.

A raw scan of the shipped `.big` archives finds Edain referencing 49 of the 75, leaving **~26
free** (38, 39, 43–49, 54–59, 61–67, 71–74). That is a byte scan over archives including binary
map data, so treat it as approximate and re-check before claiming a specific slot.

**So bits are not the scarce resource — triggers are.** If you need another condition that INI can
already drive, take a free `USER_*` and patch nothing. This patch exists because no amount of INI
can express "the queue is non-empty".

## 3. The name table, and why the parser needs no patch

The INI name→bit parser at `0x004B3B5B` is **terminator-driven, not count-driven**:

```
004b3b5f: cmp  dword [0xd9fad8], edi   ; edi = 0
004b3b65: mov  esi, 0xd9fad8
004b3b6c: strcmp(token, [esi]) ; match -> return edi
004b3b7e: add  esi, 4 ; inc edi ; if [esi] != 0 loop
004b3b87: or   eax, -1                 ; not found
```

So extending the table makes the new token parse everywhere a model condition is accepted —
`ModelConditionState`, `DisableOnModelCondition`, `HideSubObject`, … — with **zero parser edits**.
That is the one place this patch is cheaper than [`cah-factions`](cah-faction-limit.md), which
needed a parser wrapper.

The table cannot grow in place (a `DamageFX` attribute table starts at `0x00DA0418`), so it is
copied to a cave with one extra entry and its **16** references repointed. All 16 hold the bare
base; unlike the CAH side table, **nothing references it at an offset**, so there are no
end-of-table loop bounds to keep in step.

## 4. The ten count sites, and why they move with the table

Every site encoding 591, classified — 25 raw `0x24f` dwords appear in `.text`, but 15 are jump
displacements:

| instruction VA | what it bounds |
|---|---|
| `0x00444DF5` | `getBitCount()` |
| `0x00446103` | name-joining loop → calls `0x00444DFB` |
| `0x00448959` | debug dump; indexes the table, mask at `+0x258` |
| `0x004495C7` | INI writer loop; indexes the table |
| `0x004B8DCE` | **`xfer`** — the packer above |
| `0x004BAF80` | name-joining loop → calls `0x00444DFB` |
| `0x007C6452` | animation-state parse loop |
| `0x007C64F8` | animation-state parse loop |
| `0x008BA785` | mask-to-string builder |
| `0x008E2C1F` | **the validating setter** — `if (bit < 0 \|\| bit >= 591) return;` |

All ten are `imm32`, so all are in-place byte patches of the same length.

Two of them are load-bearing in opposite directions. `0x008E2C1F` rejects any index ≥ the count,
so missing it means the patch installs, verifies, and silently does nothing. And `0x00446103` /
`0x004BAF80` walk `0..count` calling `0x00444DFB`, which indexes the table with **no bound
check** — so raising the count *without* extending the table hands a NULL string pointer to
`AsciiString` concatenation. **The table and the count are one edit or neither**;
`test_the_count_and_the_table_must_move_together` asserts `verify` notices if they drift.

## 5. `ProductionUpdate` — one queue, both kinds

The module's constructor at `0x008A1819` stores five vtables, which gives the subobject layout:

| offset | what |
|---|---|
| `module+0x00` | primary vtable (`0x00C67EF4`) |
| `module+0x04` | `ModuleData*` |
| `module+0x08` | **`Object*`** |
| `module+0x10` | `UpdateModule` subobject → vtable `0x00C67E2C`, slot 0 = `update` |
| `module+0x20` | `ProductionInterface` subobject → vtable `0x00C67DB0` |
| `module+0x28` | **production queue head**, or NULL |

`ProductionEntry` is `0x54` bytes (`push 0x54; call 0x42F6E0` at `0x008A1078`), with `+0x04` the
kind, `+0x0C` the payload and `+0x48` the next pointer.

The head offset is confirmed three independent ways: `cancelUpgrade` walks it as `[iface+8]`
(`0x008A116C`), and both `0x008A072F` and `0x008A0669` read `[module+0x28]` with the module base
in `ecx`. `Object*` at `module+0x08` likewise agrees between `[iface-0x18]` in the interface
methods and `[esi-8]` in `update`.

**Units and upgrades share the one list**, which is why one bit satisfies both halves of the
requirement: `queueUpgrade` (`0x008A0FDA`) consults `TheUpgradeCenter` (`0x00DE45A0`) and prepends
a kind-2 entry to the same queue `update` walks. Splitting into two conditions would only mean
walking the list and testing `+0x04` — but that costs a second bit, which §2a prices.

## 6. Why the hook is `update`'s entry, and nothing else

`ProductionUpdate::update` is `0x008A1B9F` (slot 0 of the `UpdateModule` vtable at `0x00C67E2C`).
It is the natural site because it already does this work — three calls to the propagate helper
`0x0068B53C`, with the `Object` in `edi` throughout:

```
008a1c5d: or  dword [edi+0x134], 0x1000   ; bit 332 = UPGRADE_ECONOMY_BONUS
008a1c77: call 0x68b53c
008a2b9f: or  byte  [ecx+0x127], 4        ; bit 218 = JUST_BUILT
```

Resolving those byte/mask pairs back through `+0x10C` to real condition names is what
cross-validates the whole model: `UPGRADE_ECONOMY_BONUS` is exactly
`SetBonusModelConditionOnSpeedBonus`, and `JUST_BUILT` is exactly what a completion tick sets.

**A set-or-clear at the entry is sufficient because `update` never sleeps.** It has exactly one
`ret`, at `0x008A2F1F`, reached from one exit block:

```
008a2f0e: mov ecx, [ebp-0xc] ; pop edi ; xor eax, eax ; pop esi ; inc eax   ; -> returns 1
```

An `UpdateSleepTime` of 1 means "run me again next frame", unconditionally. Had it slept when the
queue emptied, an entry hook would leave the bit **stuck on forever** — the tick that drains the
queue still sees a non-empty queue on entry, and there would be no later tick to clear it. That
was the one design risk, and the single-exit `inc eax` retires it; the alternative was hooking the
completion site and the cancel path as well.

## 7. The cave

`0x008A1B9F`'s first instruction is `mov eax, 0xba2088` — an SEH-prologue load, and **exactly 5
bytes**, so a `jmp rel32` displaces it whole. The cave runs *before* the prologue, which sets the
constraints: leave the stack as found, preserve `ecx` (the `this` the prologue still needs), and
touch only `eax`/`ecx`/`edx` — `ebx`/`esi`/`edi` are callee-saved and `update` has not pushed them
yet, so corrupting them here would corrupt the **caller's** copies.

```asm
push ecx                              ; `this`
mov  eax, [ecx-8]                     ; Object *
test eax, eax          ; jz done
cmp  dword [ecx+0x18], 0              ; queue head
jz   clear
test dword [eax+0x154], 0x8000        ; already set?
jnz  done
or   dword [eax+0x154], 0x8000
jmp  propagate
clear:
test dword [eax+0x154], 0x8000        ; already clear?
jz   done
and  dword [eax+0x154], 0xffff7fff
propagate:
mov  ecx, eax
call 0x0068b53c                       ; Object::onModelConditionFlagsChanged
done:
pop  ecx
mov  eax, 0xba2088                    ; the displaced instruction
jmp  0x008a1ba4
```

Bit 591 is dword 18 of the mask: `0x10C + 18*4 = 0x154`, mask `0x8000` — the last dword, ending
exactly at `0x158`.

The read-before-write is not micro-optimisation. Without it every producing building would push
its mask to the `Drawable` on every logic frame; the engine's own two condition writes inside
`update` test first for the same reason.

## 8. Determinism, and what that costs

The mask is on the logic-side `Object` and is part of what the engine CRCs, so **every peer must
run the same patched binary**. That is stricter than the other bundled patches, which are
data-shape changes:

- a patched and an unpatched client **desync** the moment a building starts producing;
- a replay recorded on one will not play back on the other.

Nothing in the order stream changes, so [`order_space_map.md`](../../sage_replay/order_space_map.md)
is untouched. Savegames are unaffected in *layout* (§2a) — a stock save loads into a patched
binary and back.

## 10. The optional `WeaponSetFlag` (`--weapon-set-flag`)

**What it adds.** One `WeaponSetFlags` name, set on the object for as long as the queue is
non-empty, so a producer can carry a different loadout while it is busy:

```ini
WeaponSet
  Conditions = None
  Weapon     = PRIMARY GondorFortressArrow
End
WeaponSet
  Conditions = PRODUCING
  Weapon     = PRIMARY GondorFortressArrowWeak   ; distracted
End
```

### 10a. The table, and why it costs less than a model condition

| fact | address | how it was established |
|---|---|---|
| name table, 104 entries + NULL | `0x00DA1328` | walked to the terminator |
| eight references, all bare imm32 in `.text` | `0x0068CD7A`, `0x0068CE1F`, `0x0068CE24`, `0x006C906F`, `0x006C90AF`, `0x006C911A`, `0x00881635`, `0x008816B5` | every dword in the image holding the base |
| `getBitCount` → 104 | `0x0068CC34` | `push 0x68; pop eax; ret` |
| `Object`'s mask | `Object+0x38C` | `getWeaponSetFlags` @`0x0068BE7D` is `lea eax,[ecx+0x38c]; ret` |
| mask width, 4 dwords = 128 bits | — | the whole-mask helpers loop `push 4; pop edx` |
| `setWeaponSetFlags(mask)` | `0x0068DECA` | ORs 4 dwords at `+0x38C`, then calls `WeaponSet::updateWeaponSet` @`0x006C99E2` |
| `clearWeaponSetFlags(mask)` | `0x006911B7` | AND-NOTs, same reselect call |

Unlike `ModelConditionFlags` (§4), **no count bounds anything on the path that makes a new flag
work**. The INI token resolves through `INI::scanIndexList` (`0x0042B914`), which walks to the
NULL; `getBitFromName` (`0x0068CE19`) walks to the NULL; and selection is pure mask arithmetic:
`ThingTemplate::findWeaponTemplateSet` (`0x0073F6B9`) scores each declared set with two popcount
helpers — `0x0073C77B` counts bits set in both, `0x0073C7D2` counts bits the set wants and the
object lacks — and **both loop over 4 dwords flat**. Bit 104 therefore participates in selection
with nothing patched but the table.

### 10b. Why the count is asserted and never raised

Exactly two things read `getBitCount`, and a new flag wants to be in neither:

- `0x00690F40` and `0x0069120E` walk bits `0..103` against the weaponset→model-condition map at
  `0x00C16958`, which holds **104 entries**. Raising the count without extending that map reads
  past it. (`0x0069120E`, inside `clearWeaponSetFlags`, is also why bit 104 is a *safe* bit to
  clear: the loop that clears same-indexed model conditions never reaches it.)
- `xfer` bounds the saved bit list by it, so bit 104 is **not written to a savegame**.

The second is the reason all three blocks in the cave are **level-triggered**. The model-condition
bit *is* saved (by name, §2a); the weapon-set bit is not. An edge-triggered hook would come back
from a load with the condition set, the flag lost, and no transition left to notice — so each
block guards on its own state and the three re-agree on the first frame after a load.

## 11. The optional `LocomotorSetType` (`--locomotor-set`)

**What it adds.** One `LocomotorSetType` name, chosen on the object's AI while the queue is
non-empty and given back as `SET_NORMAL` afterwards:

```ini
Behavior = AIUpdate ModuleTag_03
  Locomotor = SET_NORMAL    MordorWorkshopLoco
  Locomotor = SET_PRODUCING MordorWorkshopSlowLoco
End
```

### 11a. An enum, not a bitmask — so the question is storage, not spare bits

| fact | address | how it was established |
|---|---|---|
| name table, 17 entries + NULL | `0x00DA0530` | walked to the terminator |
| eight references | `0x005E9B07`, `0x0066E9F9`, `0x008816FC`, `0x0089A6B4` in `.text`; `0x00C0F628`, `0x00C2E028`, `0x00C2E038`, `0x00C5BCC8` as `userData` in INI field descriptors | every dword holding the base |
| the per-set locomotors | `ThingTemplate+0x3AC` (size at `+0x3B0`) | a `std::map` keyed by the set index: `operator[]` @`0x005E983D` from the parser @`0x0073FB3F`, find @`0x0073DD59` |
| a second map keyed the same way | `ThingTemplate+0x3A0` | find @`0x0073DD2A` |
| `chooseLocomotorSet` | vtable slot `+0x238` on `Object+0x260` | the engine's own call at `0x0089A6BC` |
| the current set | `AIUpdate+0x1F4` | `cmp eax,[esi+0x1f4]` at `0x006680C6` |

**Nothing indexes a fixed-size array with a `LocomotorSetType`.** The four single-valued fields
(`ComboLocomotorSet`, `AttackLocomotorType`, `ReturnForAmmoLocomotorType`, `ForcedLocomotorSet`)
store a plain int, and the per-set locomotors live in a tree keyed by that int. An eighteenth
value costs a table relocation and nothing else — no count, no array, no struct growth. It is the
cheapest of the three tables by some distance.

### 11b. The fallback is what makes driving it safe

`chooseLocomotorSet` (`0x006680B2`) is a no-op in every case worth worrying about:

- it returns early when the set asked for is already current;
- it refuses outright while the forced-locomotor flag at `+0x3C9` is set;
- it delegates to `setLocomotorSet` (`0x00667FC9`), which returns false — **changing nothing** —
  when `findLocomotorTemplateVector` hands back NULL, i.e. when the template declares no locomotor
  for that set.

So an object whose INI never mentions the new set is untouched by a hook that asks for it every
frame, and the cave's own guards (no AI module at `Object+0x260`; the set already current) keep
the common cases down to a load and a compare. On the way out it reverts **only if the current set
is still the one it installed**, so a `SET_PANIC` chosen meanwhile is not stomped.

One asymmetry worth stating plainly: while the queue is non-empty this *outranks* sets the engine
chooses, because it re-asserts every frame. That is the feature as specified — "producing" is a
state, not an event — but it does mean a producing object cannot be panicked out of its producing
locomotor.

### 11c. What it is useful on

Only an object with **both** a `ProductionUpdate` and an `AIUpdate` carrying locomotors, which no
stock BFME structure is. This half is for mobile producers; on a normal building the cave's first
locomotor guard (`[Object+0x260]` is NULL) makes it free and inert.

## 9. What is verified, and what is not

Verified statically, and asserted by
[`tests/sage_patch/test_production_condition.py`](../../tests/sage_patch/test_production_condition.py):
the cave's encoding, that it reads the derived offsets, that both paths guard before writing, that
its only call is the propagate helper and its only exit the return into `update`, the 592-entry
table, all 16 repointed references, all 10 raised bounds, the build fingerprint and the vtable
dispatch check. Applying and verifying composes with every other bundled patch in all 24 orders.

With the extras on, the same tests cover: the added blocks' encoding and that `eax` is saved
across every call they add, that each guards on its own state at its own offset, the two rebuilt
tables keeping every existing index, the mask constant naming exactly the new flag, all sixteen
further repointed references — and that the weapon-set count at `0x0068CC34` is left **exactly**
as it was (§10b). With both off, the cave is byte-for-byte what it was before they existed, which
is asserted rather than assumed.

**Open — needs the game running:**

1. **The condition actually appearing in-game.** Nothing here has been observed firing.
2. **That bits 591–607 are genuinely untouched.** Storage width is proven six ways and every
   enumerating loop stops at the count, but "no code writes the spare bits" is a negative that
   only a runtime check buys: set the bit, tick a frame, confirm nothing else moved.
3. **The `xfer` load path.** `0x004B8D87` only packs; its counterpart was not located. §2a argues
   the blob length cannot change, but a savegame round-trip is required, not optional.
4. **Multiplayer determinism**, which follows from §8 but has not been played.
5. **The two extras firing.** `updateWeaponSet` rebuilding an object's `Weapon`s on the transition
   resets reload and aim state — expected, and the same cost the engine pays for
   `WEAPONSET_PLAYER_UPGRADE`, but unobserved. Likewise `chooseLocomotorSet` returning false for a
   template that declares no locomotor for the set is read off `0x00667FC9`, not watched.

Until 1–4 are done this is a static result, in the same sense
[`ai-revive-gate.md`](ai-revive-gate.md) is.
