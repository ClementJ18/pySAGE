# An aura that never comes back — the `passive-aura-revive` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read out of the installed
`game.dat`.

**Verdict:** two modules, five bytes and eight. Both `PassiveAreaEffectBehavior::update` and
`AttributeModifierAuraUpdate::update` park themselves at the sleep-forever sentinel the first time
they tick on a dead object, and nothing in the engine wakes an update module when an object is
revived — so an aura on a structure that survives death as rubble is gone for the rest of the game
once the structure is rebuilt. The patch returns each module's ordinary sleep on that arm instead.
The passive module takes five bytes and no cave; the aura module takes an 87-byte cave, because its
sentinel is shared with a second arm on which sleeping forever is correct, and because it has to be
given the construction gate its sibling already has - without which it would resume when a rebuild
*starts* rather than when it finishes. **Static-verified**: it
applies, verifies and disassembles as intended, and both sites are confirmed against the real
binary. The resumption itself has not been watched in a running game; what a running game has
settled is the `ecx` contract in §6.2, which the first build got wrong and crashed on.

## 1. The symptom

A castle keep or camp citadel carries an aura — `IntaktesBollwerk` on a Gondor keep, `FeelGoodSaruman`
on the Isengard citadel. The keep is destroyed, goes to rubble, and the aura correctly stops. The
keep is rebuilt, and the aura never returns. Reloading a save does not bring it back; only building
a new keep does.

The structures this happens to are the ones that **survive their own death**. `KeepObjectDie` plus
`RubbleRiseUpdate` is how a keep becomes rubble instead of a hole, and `SelfRepairFromRubbleLoop` in
the same object is the repair that brings it back. The object never leaves the world, so it is the
same `Object`, with the same modules, that comes back — which is exactly why the module's state
matters.

## 2. Finding the update

The module registers at `0x0065A92B` (`newModule` `0x0064C403`, `newModuleData` `0x0064C43B`,
interface mask `1`), and its name string sits at `0x00C0AD50`. The instance constructor is
`0x00887CF3`, `0x28` bytes, and writes three vptrs:

```
00887d21  mov dword [esi],      0xc60c38   ; the module's primary vtable
00887d27  mov dword [esi+0x0c], 0xc67300
00887d2e  mov dword [esi+0x10], 0xc60c28   ; the UpdateModule sub-object
```

`0x00C60C28` is a three-slot vtable, and slot 0 is `0x00887DF7`. That is the update: its `this` is
the sub-object at module `+0x10`, so it opens by reaching back past it —

```
00887dfd  mov ebx, [esi-0x8]    ; the Object
00887e01  mov edi, [esi-0xc]    ; the ModuleData
```

— which matches the constructor's layout (`+0x04` module data, `+0x08` object) and is the same
`this-0x10` idiom [`lifetime-extend-upgrade.md`](lifetime-extend-upgrade.md) records for
`LifetimeUpdate`. `getModuleName` (`0x00887D63`, `mov eax, 0xC0AD50 ; ret`) ties the whole vtable
back to `PassiveAreaEffectBehavior` by name rather than by position.

## 3. The three gates, and why one of them is different

The sleep the update returns lives in a scratch dword in its own frame, written at the top from
`ModuleData+0x10` (`PingDelay`, floored at 1):

```
00887e04  mov eax, [edi+0x10]        ; PingDelay
00887e07  test eax, eax
00887e09  mov [esp+0x10], eax        ; the sleep this call will return
00887e0d  jne 0x00887e17
00887e0f  mov dword [esp+0x10], 1    ; PingDelay 0 means every frame, not never
```

`[esp+0x10]` names that slot for the whole body: the prologue pushes five registers
(`ecx`, `ebx`, `ebp`, `esi`, `edi`) and every call in the function is callee-balanced, so `esp` does
not move again until the epilogue pops them at `0x00887EC2`.

Three conditions then stand between the update and the scan.

| gate | site | returns |
|---|---|---|
| `UpgradeRequired` is set and the object does not hold it | `0x00887E43` | `[esp+0x10]` |
| the object is still being **built** | `0x00887E59` | `[esp+0x10]` |
| the object is effectively dead | `0x00887E62` | `0x3FFFFFFF` |

The middle gate is worth naming precisely, because §6.2 transcribes it:

```
00887e45  mov  ecx, ebx              ; the Object
00887e47  call 0x0068c3e6            ; Object::getGettingBuiltBehavior -> iface or NULL
00887e4c  test eax, eax
00887e4e  je   0x00887e6b            ;   none -> testStatus(UNDER_CONSTRUCTION)
00887e50  mov  edx, [eax]
00887e52  mov  ecx, eax
00887e54  call [edx+0x2c]            ;   isStillBuilding()
00887e57  test al, al
00887e59  jne  0x00887ebe            ; still going up -> the ordinary sleep
```

A rebuild out of rubble is a build: `KeepObjectDie` keeps the object, and a
`GettingBuiltBehavior` with `RebuildTimeSeconds` puts it back up. So this gate, and **not** the
effectively-dead flag, is what says a structure is finished - which matters in §6.2 because the
sibling module does not have it.

The first two return the ordinary sleep, so the module is scheduled again and the condition gets
another look — which is the only reason an upgrade-gated aura ever switches on at all, given that
this module is not an upgrade module and never hears about `giveUpgrade`. The third does not:

```
00887e5b  test byte [ebx+0x458], 1   ; effectively dead?
00887e62  je   0x00887e76            ;   no  -> scan and re-apply
00887e64  mov  eax, 0x3fffffff       ;   yes -> UPDATE_SLEEP_FOREVER
00887e69  jmp  0x00887ec2            ;          return it
```

`Object+0x458` bit 0 is the effectively-dead flag, written by `Object::setEffectivelyDead`
(`0x0068D950`); [`cooldown-through-death.md`](cooldown-through-death.md) §1.2 and
[`healing-damage-nuggets.md`](healing-damage-nuggets.md) both name it. `0x3FFFFFFF` is the
sleep-forever sentinel [`fire-at-attacker.md`](fire-at-attacker.md) records, and `setWakeFrame`
(`0x00850C32`) turns a returned delta into `TheGameLogic`'s wake frame for the module.

## 4. Why nothing wakes it again

Three candidate wake sources, none of which fires.

**Revival does not touch the modules.** `Object::setEffectivelyDead(FALSE)` (`0x0068DA1B`, the
clear arm) clears the bit, notifies the partition manager and calls `0x0068B44B`, which forwards to
the drawable at `[obj+0xa4]`. It never walks `[obj+0x24C]`, the module array.

**Nor does the repair that calls it.** A structure leaves rubble through its body's damage-state
walk: `0x008C5388` selects the state and `0x008C4CF4` enters it, and that function is where
`setEffectivelyDead` is called with the answer to `health <= 0` —

```
008c4d31  call [eax+0x60]            ; body->getHealth()
008c4d3a  jb   0x008c4d40
008c4d3c  mov  al, 1                 ; health <= 0
008c4d42  push eax
008c4d45  call 0x0068d950            ; setEffectivelyDead(dead)
```

— and then goes on to animations and audio. No module is woken on either arm. The same is true of
the other in-place revive in the engine: `RespawnUpdate` restores a hero's health through the body's
vtable `+0x58` and wakes nothing (see [`cooldown-through-death.md`](cooldown-through-death.md) §1.2).

**The upgrade path cannot reach it.** `PassiveAreaEffectBehavior` registers with interface mask `1`
and carries no `UpgradeMux`, which is why `UpgradeRequired` is a string it polls rather than a
trigger it is woken for. So the mechanism that re-arms an `AttributeModifierAuraUpdate` when an
upgrade arrives does not apply here.

The module's only wake source was its own return value, and the dead arm gave that up.

### The sibling module, and why it costs a cave

`AttributeModifierAuraUpdate` has the same sentinel one gate earlier:

```
0089f441  test byte [esi+0x458], 1     ; effectively dead?
0089f44f  je   0x0089f459
0089f451  cmp  byte [edi+0x16a], bl    ; RunWhileDead
0089f457  je   0x0089f474
0089f474  mov  eax, 0x3fffffff
```

`RunWhileDead` (`ModuleData+0x16A`, default `No`) is an escape hatch `PassiveAreaEffectBehavior`
does not have — but it is the wrong one for this problem, because `Yes` keeps the aura *applied*
through the death rather than making it resume after it. The defect there is the same one, and the
patch fixes it too — but not in the same five bytes. That sentinel is shared with the module's
designed idle state, so the two arms have to be split apart first; and this module has **no
construction gate**, so restoring it to the schedule without adding one would bring the aura back
on the first frame of a rebuild. §8.2 is the whole reading; §6.2 is what was built.

## 5. What breaks in practice

Only a module on an object that dies **and stays**. When the engine deletes the object, the module
goes with it and the parked wake frame is meaningless — which is why this is invisible on an
ordinary building that leaves a rebuild hole and comes back as a new `Object`.

In the Edain tree, forty-four objects carry a `PassiveAreaEffectBehavior` alongside `KeepObjectDie`
or `RubbleRiseUpdate`. Almost all of them are keeps and citadels: `GondorCastleBaseKeep`,
`RohanCastleBaseKeep`, `IsengardFortressCitadel`, `MordorCastleKeep`, `AngmarCastleBaseKeep`,
`BruchtalCastleBaseKeep`, and their camp and War-of-the-Ring variants.

The aura's disappearance while in rubble needs no explanation of its own: each ping re-applies the
modifier with an expiry a `PingDelay` ahead (`0x00887C94` calls `0x00804FCC` with
`TheGameLogic->frame + PingDelay`), so a bonus that stops being re-upped lapses on its own. That is
the behaviour a mod wants. What it does not want is that it never starts again.

## 6. The patch

### 6.1 `PassiveAreaEffectBehavior` — five bytes, no cave

Return the ordinary sleep on the dead arm, in the five bytes the sentinel occupied:

| site | stock | patched |
|---|---|---|
| `0x00887E64` | `b8 ff ff ff 3f` — `mov eax, 0x3fffffff` | `8b 44 24 10 90` — `mov eax, [esp+0x10]` ; `nop` |

The `jmp 0x00887EC2` two bytes on is untouched and still carries `eax` to the same epilogue, so no
control flow changes and no address moves. The `nop` is there only so the rewrite covers the site
exactly.

The dead arm still returns **before** the scan, so nothing is applied while the object is dead and
the rubble behaviour is unchanged. What changes is that the module keeps its place in the schedule,
so the first tick after the flag clears sees a live object and resumes.

**Cost.** A dead object that stays in the world runs the three gates every `PingDelay` frames
instead of nothing — a string-empty test, an upgrade lookup, an interface walk and two bit tests.
Only objects carrying this module are affected, and only while dead.

**Anchors.** The patch refuses a build where any of these has moved: the constructor's
`mov dword [esi+0x10], 0xC60C28` (`0x00887D2E`), `getModuleName` (`0x00887D63`), the `PingDelay`
read and slot store (`0x00887E04`), the dead test that abuts the rewritten instruction
(`0x00887E5B`), the normal return and its five pops (`0x00887EBE`), slot 0 of the update vtable
(`0x00C60C28`), and the module-name string itself (`0x00C0AD50`).

### 6.2 `AttributeModifierAuraUpdate` — the gate block and a cave

§8.2 is why this one cannot be five bytes. Two reasons, and the second decides the size:

- the sentinel it would rewrite is also the correct answer for an aura still waiting on its
  `TriggeredBy` upgrade, so the arms have to be split;
- the module has no construction gate, so restoring it to the schedule on its own would resume the
  aura the frame the rubble starts rising. `ActiveBody::internalChangeHealth` (`0x008C31A5`)
  rewrites the effectively-dead flag from `health <= 0` at `0x008C32B1`, so that flag clears on the
  **first** repair tick, and the body's damage state leaves `RUBBLE` at the same instant
  (`0x008C1B79` returns `3` only for `health == 0`). Nothing else on the object distinguishes
  "rubble" from "rebuilt". Only `GettingBuiltBehavior::isStillBuilding` stays true for the rest of
  the rebuild — which is exactly the gate `PassiveAreaEffectBehavior` already has (§3).

So the whole gate block is displaced into the cave, which re-emits it with that gate in front:

| site | stock | patched |
|---|---|---|
| `0x0089F441` (24 bytes) | the dead test, `push edi`, the two loads, and the `RunWhileDead` `cmp`/`je` | `e9` *rel32* to the cave, then 19 `nop` |

```
.aurevi:
  push edi                   ; the three displaced instructions, unchanged
  mov  edi, [ecx-0xc]
  mov  [ebp-0x14], ecx
  mov  ecx, esi              ; transcribed from PassiveAreaEffectBehavior @0x00887E45
  call 0x0068c3e6            ; Object::getGettingBuiltBehavior
  test eax, eax
  je   no_module
  mov  edx, [eax]
  mov  ecx, eax
  call [edx+0x2c]            ; isStillBuilding()
  jmp  answer
no_module:
  push 2                     ; OBJECT_STATUS_UNDER_CONSTRUCTION
  mov  ecx, esi
  call 0x0044ddec            ; Object::testStatus
answer:
  test al, al
  jne  ordinary_sleep        ; still going up -> wait, and look again
  test byte [esi+0x458], 1   ; stock: effectively dead?
  je   scan
  cmp  byte [edi+0x16a], 0   ; stock: RunWhileDead
  jne  scan                  ; Yes -> keep applying through the death, unchanged
ordinary_sleep:
  jmp  0x0089f6bd            ; RefreshDelay + id % 5
scan:
  mov  ecx, [ebp-0x14]       ; `this` again - see below
  jmp  0x0089f459
```

Eighty-seven bytes, in a section appended past every existing one with `allocate_section`, which is
what keeps the patch order-independent with everything else in the bundle. Both calls are
`__thiscall` and preserve `esi`, `edi` and `ebx`, which is what lets the two stock tests below them
run unchanged; `ebx` is still the zero the update set at `0x0089F43F`, and the `cmp` uses an
immediate `0` rather than `bl` so the cave does not depend on that instruction staying there. The
two exits are addresses the stock block already reached — `0x0089F459` is the byte it fell through
to, and `0x0089F6BD` is where the next gate's `jne` goes — and nothing in the update branches into
the 24 bytes being replaced, so no address moves.

**`ecx` is the one register the calls take away, and the scan resume point needs it.** Ten
instructions past `0x0089F459` the update reads the `UpgradeMux` off it:

```
0089f469  83 c1 10        add  ecx, 0x10            ; the UpgradeMux subobject at this+0x10
0089f46c  8b 01           mov  eax, [ecx]           ; its vtable
0089f46e  ff 10           call [eax]                ; isAlreadyUpgraded()
```

Stock that is safe, because nothing between the `__thiscall` prologue and there touches `ecx`. The
cave calls out twice before it jumps there, and a `__thiscall` callee leaves *its own* `this` in
`ecx` — so the scan arm reloads `this` from `[ebp-0x14]`, the slot the displaced `mov` at the top of
the cave has just written and the stock code at `0x0089F4A0` reads back. The sleep arm needs no such
reload: `0x0089F6CB` loads `ecx` from the SEH slot itself on the way into the epilogue.

**This is the crash the first build shipped with**, and it is worth recording as a shape rather than
as an incident. Two dumps from 2026-09-11 in the Edain install both fault in these three
instructions: one at `0x0089F46E` with `ecx` holding the `GettingBuiltBehavior` the gate had just
asked (`[that+0x10]` is zero, so `call [0]`), and one at `0x0089F46C` with `ecx = 2`, the
`OBJECT_STATUS_UNDER_CONSTRUCTION` argument left behind by `Object::testStatus` on the other arm.
Neither is a rare path: the gate answers "finished" for every completed structure, so the game died
on the first aura tick of the first match. A displaced block's register contract runs to the
*resume point*, not to the end of the displaced bytes.

`0x0089F474` is deliberately **left stock** and anchored as such. It is still reached by the
`isAlreadyUpgraded` test four instructions above it, and for an aura that has not been triggered yet
sleeping forever is correct: `giveSelfUpgrade` (`0x00855388`) wakes it through this module's
`upgradeImplementation` (`0x008554D6`), which is a bare `setWakeFrame`.

**What the construction gate costs elsewhere.** Nothing on the object says which kind of build is in
progress, so the gate does not distinguish a rebuild from a first build: an
`AttributeModifierAuraUpdate` on a structure now also stays quiet while that structure goes up for
the first time. That is what `PassiveAreaEffectBehavior` already does, so the change makes the two
modules agree rather than inventing a third behaviour, and in the Edain tree it reaches 154 objects
— the 107 that repair out of rubble plus 47 more that are built but do not survive death. Units are
untouched: they have no `GettingBuiltBehavior` and never carry `UNDER_CONSTRUCTION`, so the gate
answers no.

**Cost.** A dead or half-built aura object runs the gates and one module-array walk every
`RefreshDelay + id % 5` frames instead of nothing. Un-triggered auras are untouched — that is the
whole reason for splitting the sentinel.

**Anchors.** The constructor's `mov dword [esi+0x10], 0xC67598` (`0x0089ED9B`), `getModuleName`
(`0x0089EDD2`), slot 0 of the update vtable (`0x00C67598`), the module-name string (`0x00C0B290`),
the next gate the cave hands `RunWhileDead = Yes` back to (`0x0089F459`), the sentinel that must
stay stock (`0x0089F474`), the sleep computation the cave jumps to (`0x0089F6BD`), and the two
routines the transcription calls (`0x0068C3E6`, `0x0044DDEC`). The passive module's own
construction gate (`0x00887E45`) and its fallback arm (`0x00887E6B`) are anchored too, because they
are the source the cave was transcribed from.

## 7. What a mod has to write

Nothing. No keyword, no token, no `.str` key, no map data. The module and its fields are exactly as
they were, and a mod uses this by writing what it already writes.

The two INI-level alternatives both fail on their own terms, which is why this is a binary patch at
all. Gating the aura on an `UpgradeRequired` does not help: an aura whose upgrade is *satisfied*
reaches the dead arm like any other, and one whose upgrade is not satisfied was not running
anyway. And moving the aura to `AttributeModifierAuraUpdate` with `RunWhileDead = Yes` trades a
permanent loss for an aura that stays on while the keep is a pile of rubble — its `RequiredConditions`
name table (`0x00DB094C`) offers only `MOUNTED`, `TAINT` and `ELVEN_WOOD`, so there is no condition
to gate it back off with.

## 8. The two sibling modules

Read statically on 2026-09-09 against the same build, from the same repo `game.dat` (no patch
detected in it, so every byte quoted here is stock). This is the reading behind §6.2, and the
reason the third module a reader might expect is absent from it.

### 8.1 `AttributeModifierUpgrade` — no defect of this shape

It is not an update module. Its interface mask is `0x84` — upgrade, plus the same second bit
`CommandSetUpgrade` carries — against `1` for `PassiveAreaEffectBehavior` and `0x81` for
`AttributeModifierAuraUpdate`. There is no `update`, so there is no sleep to park and no sentinel to
rewrite.

| what | VA |
|---|---|
| module name string | `0x00C0AE38` |
| registration | `0x0065A6B2` (`newModule` `0x00650334`, `newModuleData` `0x006555B0`) |
| instance ctor, `0x1C` bytes | `0x008BA876` |
| `UpgradeMux` sub-object at module `+0x10`, vtable | `0x00C6F400` |
| `upgradeImplementation` (mux `+0x28`) | `0x008BA8C3` |

`upgradeImplementation` is three instructions — `Object::applyModifierList(ModuleData+0x138, -1)` —
and `-1` means the `ModifierList`'s own `Duration`, so a bonus meant to be permanent never lapses
and there is nothing for a revive to restart.

Nor does death drop it. The modifiers live in `AttributeModifierPoolUpdate` (name string
`0x00C0B068`, found by name key from `0x0068C4A6`), and that module's update (`0x0080585F`) has
**no dead gate at all**: it opens `mov ebx, 0x3FFFFFFF`, walks the pool for the soonest expiry, and
returns the sentinel only when the pool is empty. An `AttributeModifierUpgrade` bonus survives an
object's death because nothing in the death path touches either the module or the pool.

**Not patched, because there is nothing to patch.** The defect this document is about cannot
occur in a module with no update.

### 8.2 `AttributeModifierAuraUpdate` — the same defect, and why the fix needs a cave

| what | VA |
|---|---|
| module name string | `0x00C0B290` |
| `getModuleName` | `0x0089EDD2` |
| instance ctor, `0x28` bytes (vptrs `+0x00` `0xC675A4`, `+0x0C` `0xC67838`, `+0x10` `0xC67598`; `UpgradeMux` at `+0x20`, vtable `0xC67550`) | `0x0089ED5C` |
| `update` — slot 0 of `0xC67598` | `0x0089F42D` |
| the effectively-dead test | `0x0089F441` |
| the `RunWhileDead` gate — the eight bytes a patch would rewrite | `0x0089F451` |
| the shared sentinel | `0x0089F474` |
| the ordinary sleep | `0x0089F6BD` |

Two things about this update decide the patch, and both differ from `PassiveAreaEffectBehavior`.

**There is no sleep slot to read back.** The passive module writes `PingDelay` into `[esp+0x10]` at
the top and every ordinary gate returns that dword, which is why its fix is a five-byte `mov`. Here
the sleep is *computed at the exit*:

```
0089f6bd  mov  eax, [esi+0x74]      ; the Object's id
0089f6c0  cdq
0089f6c1  push 5 ; pop ecx
0089f6c4  idiv ecx
0089f6c6  mov  eax, edx             ; id % 5 - a stagger, so every aura does not scan on one frame
0089f6c8  add  eax, [edi+0x18]      ; + RefreshDelay
0089f6cb  <epilogue: pop edi/esi/ebx, restore fs:[0], leave, ret>
```

So the replacement is a jump to that computation rather than a load. It unwinds correctly from the
gate: `esi` (the `Object`) and `edi` (the `ModuleData`) are both live from `0x0089F43C` and
`0x0089F449`, all three pushes the epilogue pops happen before `0x0089F451`, and `[ebp-4]` still
holds the SEH scope index the sentinel arm returns under — the function has not entered a scope yet.
`ModuleData+0x18` is `RefreshDelay` and `+0x16A` is `RunWhileDead`, which the recovered field table
for the block confirms independently of the disassembly.

**The sentinel is shared by two arms, and only one of them is a bug.**

```
0089f441  test byte [esi+0x458], 1   ; effectively dead?
0089f44f  je   0x0089f459            ;   no -> on to the next gate
0089f451  cmp  byte [edi+0x16a], bl  ; RunWhileDead
0089f457  je   0x0089f474            ;   dead and No  -> sleep forever    <- the defect
...
0089f46e  call [eax]                 ; UpgradeMux::isAlreadyUpgraded, mux at module+0x20
0089f470  test al, al
0089f472  jne  0x0089f47e
0089f474  mov  eax, 0x3fffffff       ;   not triggered -> sleep forever   <- by design
```

The second arm is the module's idle state. An aura gated on `TriggeredBy` is *meant* to sleep
forever until `UpgradeMux::giveSelfUpgrade` (`0x00855388`) calls its `upgradeImplementation`, which
for this module (mux `+0x28`, `0x008554D6`) is nothing but a `setWakeFrame` of 1. Rewriting
`0x0089F474` in place would put every un-triggered aura in the game back on a `RefreshDelay` poll —
and `RefreshDelay` defaults to 1 — for no benefit at all. **The patch has to split the arms**, which
the passive module never had to do.

**Nothing re-arms the module once the dead arm fires.** `Object::updateUpgradeModules` calls
`isAlreadyUpgraded` at `0x0069375F` and the `jne` at `0x00693763` skips a latched module before it
reaches `attemptUpgrade` at `0x006937A8`, so a later upgrade on the same object does not re-fire it;
and slot `+0x18`, the per-pass tail `CommandSetUpgrade` uses to reset and re-evaluate itself, is
`0x0063F3BF` (a bare `ret`) for this module. Of Edain's 200 aura-carrying heroes, 192 set
`StartsActive = Yes`, which latches the mux in the constructor at `0x0089EDBB`. So the module is
unreachable for the rest of the game, exactly as the passive one is.

**A hero respawn is not the exposure.** That was §4's open question, and the answer removes the risk
rather than adding to it. `RespawnUpdate`'s die handler does call `setEffectivelyDead(TRUE)` and
does keep the object ([`cooldown-through-death.md`](cooldown-through-death.md) §1.2), so an
in-place respawn would lose the aura — but that is Path A, `RespawnRules AutoSpawn:Yes`, and Edain
does not use it anywhere: `AutoSpawn:Yes` appears zero times in the mod tree. Every recruitable hero
comes back through `ReviveMgr::reviveHero` as a **new** `Object` with fresh modules, which is Path B
and is unaffected.

**Population.** Objects in the Edain tree, by the same count §5 uses for the passive module:

| set | objects |
|---|---|
| carry an `AttributeModifierAuraUpdate` | 952 |
| ... and survive their own death (`KeepObjectDie` / `RubbleRiseUpdate`) | 341 |
| ... and repair themselves out of rubble - the ones that actually come back | 107 |
| ... of those, `RunWhileDead = Yes` and so unaffected | 2 |
| the same count for `PassiveAreaEffectBehavior` | 44 |

The affected set is the castle furniture: walls, gates, bridges, elevators, ramps and the Carn Dum
citadel, across every faction and Helm's Deep. It is two and a half times the population this patch
already fixes, and it is the same failure — the aura stops when the wall falls, correctly, and never
comes back when the wall is rebuilt.

**Why the fix needs a cave.** Two reasons. The arms have to be split somewhere, and there is no
room to split them in place: the gate is a `cmp` (6 bytes) plus a short `je` (2), and the two exits
it needs are both out of `rel8` range. And the module has to be given a construction gate, because
the effectively-dead flag it tests clears on the first frame of a repair — see §6.2, which has the
bytes and the evidence.

**Risk.** Low, and lower than the passive half's, because the exposure turned out to be structures
rather than heroes. The failure mode is an aura that resumes when it should not, not a crash.

**Status: built, in the same patch.** The remaining unknown is the one the passive half has too:
the resumption has not been watched in a running game.
