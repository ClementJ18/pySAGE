# A structure destroyed while it is rebuilding leaves no rebuild hole

RotWK `game.dat` 2.01.2614.37001, ImageBase `0x400000`. Sections 1–4 are static analysis; §6
records what a running game showed — the patch fires and the hole is created, but it spawns buried
(`CollapseHeight` below ground) on the rebuild path. Read §6 before trusting §4's "nothing
downstream differs."

## 1. The lifecycle, as the engine runs it

A creep lair is a structure carrying `RebuildHoleExposeDie`. Killing it puts a hole in its place;
the hole rebuilds it; killing the hole instead drops treasure. Four engine sites carry that loop.

| what | where |
|---|---|
| `RebuildHoleExposeDie::onDie` | `0x00889AAF` |
| the shared die-module filter it opens with | `0x0085FED5` → `0x008D29A9` |
| `RebuildHoleBehavior::update` | `0x008868C2` |
| the hole's own self-kill once the rebuild starts | `0x00886C3A` |

**Lair dies → hole appears.** `onDie` resolves `HoleName` (moduleData `+0x38`) through
`TheThingFactory` (`0x00889B3B` `findTemplate`, `0x00889B47` `newObject`), places it at the dead
object's position and angle, sets its body to `HoleMaxHealth` (moduleData `+0x3c`), then hands the
hole's `RebuildHoleBehavior` the template to put back:

```
00889be7  ff 76 74        push dword [esi+0x74]    ; the dying object's id
00889bea  8b 4d 08        mov  ecx, [ebp+8]        ; its RebuildHoleBehavior
00889bed  ff 76 04        push dword [esi+4]       ; the dying object's ThingTemplate
00889bf0  8b 01           mov  eax, [ecx]
00889bf2  ff 10           call dword [eax]         ; RebuildHoleBehavior::startRebuild
```

**Hole rebuilds → hole removes itself.** `RebuildHoleBehavior::update` creates the structure, then
in the same pass checks what it just made and stands down:

```
00886bd8  test ebx, ebx                  ; the object being rebuilt
00886bda  je   0x886c45
00886bdc  push 0x56                      ; BUILD_BEING_CANCELED
00886bde  mov  ecx, ebx
00886be0  call 0x0044ddec                ; Object::testStatus
00886be5  test al, al
00886bea  jne  0x886bf9
00886bec  mov  eax, [ebx+0x94]           ; the status bitset
00886bf2  shr  eax, 2
00886bf5  test al, 1                     ; UNDER_CONSTRUCTION
00886bf7  jne  0x886c45                  ; neither -> nothing to babysit, sleep
...
00886c3a  6a 16           push 0x16      ; DeathType FADED
00886c3c  6a 08           push 8         ; DamageType UNRESISTABLE
00886c3e  8b cf           mov  ecx, edi  ; the hole
00886c40  e8 7e 22 e1 ff  call 0x00698ec3 ; Object::kill
```

Two facts fall out of that block. The object a hole rebuilds **is** `UNDER_CONSTRUCTION` while it
rises — the engine's own babysitting loop is keyed on exactly that bit. And the hole leaves with
DeathType `FADED`, which is why every hole in the data writes `DeathTypes = ALL -FADED` on its
treasure module: `-FADED` is what stops the hole paying out when it retires normally.

## 2. The gate

`RebuildHoleExposeDie::onDie` opens with the shared applicability filter, then three of its own
tests. The third is the one that matters:

```
00889aaf  push ebp                       ; RebuildHoleExposeDie::onDie
00889ab0  mov  ebp, esp
00889ab2  sub  esp, 0x14
00889ab5  push esi
00889ab6  push dword [ebp+8]             ; the DamageInfo
00889ab9  mov  esi, ecx
00889abb  lea  ecx, [esi-0x10]
00889abe  call 0x0085fed5                ; DeathTypes / ExemptStatus / RequiredStatus / angles
00889ac3  test al, al
00889ac5  je   0x889c5c                  ; filtered out by the INI -> return

00889acb  mov  eax, [0xde4928]           ; ThePlayerList
00889ad1  mov  ebx, [esi-0xc]            ; moduleData
00889ad4  mov  esi, [esi-8]              ; the dying Object
00889ad8  mov  edi, [eax+0x18]
00889ae0  call 0x0068b678                ; Object::getControllingPlayer
00889ae5  cmp  eax, edi
00889ae7  je   0x889c5a                  ; that one player -> no hole
00889aef  call 0x0068b678
00889af6  call 0x006aac52
00889afb  test al, al
00889afd  je   0x889c5a                  ; player says no -> no hole

00889b03  8b 86 94 00 00 00  mov  eax, [esi+0x94]   ; the status bitset
00889b09  c1 e8 02           shr  eax, 2
00889b0c  a8 01              test al, 1             ; UNDER_CONSTRUCTION
00889b0e  0f 85 46 01 00 00  jne  0x889c5a          ; <-- still going up -> no hole
```

`0x00889B0E` is the whole defect. A lair killed in the window between "the hole started rebuilding
it" and "the rebuild finished" runs `onDie`, reaches this branch, and returns without creating
anything. The lair is then destroyed for good: no hole, no rebuild, and — because treasure hangs
off the *hole's* `CreateObjectDie`, not the lair's — no treasure, ever again.

The hole that spawned it is already gone, killed by `0x00886C3A` in the frame the rebuild began, so
there is nothing left to carry the loop.

## 3. Why the fix is to delete the branch rather than narrow it

The filter at `0x0085FED5` is a two-instruction thunk onto `DieMuxData::isDieApplicable`
(`0x008D29A9`), which reads the module's INI filters against the dying object:

```
008d29b6  mov  ecx, [edi+0x1c]           ; the DeathType
008d29bf  test [esi], eax                ; moduleData +0x0  = DeathTypes
008d29ce  lea  eax, [esi+4]              ; moduleData +0x4  = ExemptStatus
008d29d2  lea  eax, [esi+0x14]           ; moduleData +0x14 = RequiredStatus
008d29d6  lea  ecx, [ebx+0x94]           ; the dying object's status bitset
008d29dc  call 0x00661317
008d29ec  ...                            ; DamageAmountRequired, Min/MaxKillerAngle
```

So `ExemptStatus` is already evaluated against live `ObjectStatus` bits, `UNDER_CONSTRUCTION`
among them. Deleting the hardcoded branch therefore does not remove the rule — it moves it into
the INI, where `ExemptStatus = SOLD UNDER_CONSTRUCTION` on a `RebuildHoleExposeDie` reproduces the
stock behaviour for any object that wants it.

Narrowing the branch in the binary instead was considered and rejected for lack of a discriminator:

- **`RECONSTRUCTING` (status 21)** is the flag that would name this exactly — the engine already
  reads it as "this one was never paid for" to suppress sell refunds at `0x0077B23A` and
  `0x0085465F`, and `GettingBuiltBehavior` clears it beside `UNDER_CONSTRUCTION` at `0x0088DEE3` /
  `0x0088DEED`. But scanning every call to `Object::setStatus` (`0x0062684D`) in `.text` finds
  **no site that ever sets it**. It is cleared in three places and set in none, so it reads as
  vestigial in this build and nothing can be keyed on it.
- **The producer** would work in principle — `RebuildHoleBehavior::update` stamps the hole as the
  rebuilt structure's producer (`0x00886B27`, `Object::setProducer`) — but it stores an `ObjectID`,
  and the hole is dead by the time the structure dies, so the id no longer resolves to anything
  whose `KindOf` could be tested.

## 4. Nothing downstream of the branch depends on the object being finished

Everything `onDie` does after the gate reads only the dying object's position (`+0x38`), angle
(`+0x44`), team (`+0x31c`), id (`+0x74`) and template (`+4`), plus moduleData. None of those
differ between a finished lair and one at 5% construction, and the template it hands to
`startRebuild` is the lair either way — so the hole created from a half-built lair rebuilds the
same thing the hole created from a finished one does.

> **Correction (runtime, §6).** The position at `+0x38` *does* differ, and it is load-bearing.
> `onDie` copies the dying object's live position onto the new hole (`0x00889B4E`,
> `lea eax, [esi+0x38]` → `setPosition`), and for a lair that dies mid-rebuild that position has
> already been dropped by the collapse — so the hole is stamped ~`CollapseHeight` below ground and
> buried. The rest of this section holds; the "none of those differ" clause does not.

## 5. What was not established statically — now resolved in §6

The static write-up left three things open. §6 closes them against a running game:

- **Does the death reach `onDie` at all?** Yes — a lair killed mid-rebuild creates its hole.
- **The two upstream player gates** (`0x00889AE7`, `0x00889AFD`) — these *are* on the path, ahead
  of the erased branch, and the static doc wrongly waved them off as "not on the patched path."
  Runtime shows they pass for a rebuilding lair, because it carries the same owner as an intact
  one. Resolved below.
- **The retiring first hole.** Watched: it retires with `FADED` (no payout) the moment its lair
  dies, exactly as designed. It does not fight the new hole.

## 6. Runtime verification (2026-08-23): the hole spawns, but buried

Watched live against `C:\RotWK\game.dat` (the patch present and confirmed in the running
process — the six bytes at `0x00889B0E` read back `66 0f 1f 44 00 00`, the `nop`, via
`ReadProcessMemory`), through `sage_live`, on a paused skirmish with a Dunland lair caught
mid-rebuild.

**Setup.** The hole (`DunlandLairHole`, id 359) and the lair it was rebuilding
(`DunlandGoblinLair`, id 361, `UNDER_CONSTRUCTION`, 19% built) both stood at `(905, 865, 396)`.
Both were owned by player index 2, `PlyrCreeps` — the same owner as every intact lair on the map
(`RECONSTRUCTING` was **not** set on 361, matching §3's finding that this build never sets it).

**The two player gates are not the blocker.** `0x00889AE7` filters out a dying object whose
`getControllingPlayer` (`0x0068B678`, reads team at `+0x31c`) equals `ThePlayerList+0x18`, which is
`players[0]` — the neutral/civilian player (`engine-globals.md`, `getNthPlayer` array base `+0x18`).
`0x00889AFD` filters on `0x006AAC52(player)`, true only when `[player+0x35a] == 0 && [player+0x754]
== 0`. A creep lair is owned by `PlyrCreeps` (index 2), not `players[0]`, so gate one passes; and it
shares its owner with the intact lairs that visibly drop holes, so gate two passes too. Both are
irrelevant to the rebuild case.

**The hole is created — the patch works.** On killing lair 361:

```
frame 2794   361 DunlandGoblinLair   3.6%  UNDER_CONSTRUCTION
frame 2795   359 DunlandLairHole      0%   -     ; original hole retires (FADED)
             361 DunlandGoblinLair     0%   -     ; the rebuilding lair, dead
             362 DunlandLairHole    100%   -     ; *** a new hole, created by 361's onDie ***
frame 2805   362 DunlandLairHole    100%   -     ; persists, alone
```

So a lair destroyed mid-rebuild *does* now leave a hole. The erased gate was the only logic
suppressing it, and the two upstream gates pass. The patch's core claim is confirmed on hardware.

**But the hole spawns underground.** The new hole 362 is stable — 100% health, not sinking, not
retiring, across every sampled frame (2945–2994) — yet it sits at **Z = 280.4** while the lair it
replaced, the hole before it, and every intact lair on the map all sit at **Z ≈ 396**. It is ~116
units below the surface, so it cannot be seen or clicked, and holes are `NOT_AUTOACQUIRABLE`, so it
cannot be loot-targeted either. It still rebuilds the lair underneath. From the player's chair this
reads as "I killed it, no hole appeared, the lair just grew back" — which is the reported bug.

**Control — a built lair drops its hole correctly.** Killing an intact, fully-built lair in the
same session:

```
397 DunlandLairHole  (2488, 2956)  Z=396.0  100%   ; from a BUILT lair — ground level
—   DunlandLairHole  ( 905,  865)  Z=280.6  100%   ; from the rebuilt lair — buried
```

So the burial is specific to the `UNDER_CONSTRUCTION` death path, not to `onDie` in general.

**Cause.** `onDie` stamps the hole with the dying object's *live* position (`0x00889B4E`,
`lea eax, [esi+0x38]` → `setPosition`). A built lair still sits at ground height at the instant its
hole is placed. The rebuilding lair does not: its `StructureCollapseUpdate` carries
`CollapseHeight = 120`, and `396 − 116 ≈ 280` — the collapse has already sunk the object by the
time the hole is stamped. This is a latent flaw in the death path that the patch merely *exposed*,
because stock never created a hole here to reveal it. It is **not** caused by the patched bytes,
which touch only the branch and never the position.

## 7. What a fix looks like

The hole needs its Z snapped to terrain rather than inherited from a collapsing corpse: after
`onDie` places the hole, overwrite its height with `TheTerrainLogic`'s ground height at the hole's
`(x, y)`. That is a second, small patch (a code cave adding the terrain lookup and a `setPosition`
Z write; the hole pointer is live at `0x00889BB8` where `onDie` hands it to `startRebuild`),
composable with this one and touching bytes it does not. A data-only stopgap — lowering the lair's
`CollapseHeight` — only shrinks the burial and distorts the collapse visual, so it is a mask, not a
fix.
