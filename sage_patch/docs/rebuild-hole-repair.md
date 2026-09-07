# A structure destroyed while it is rebuilding leaves no rebuild hole, and the hole it should leave would be buried

RotWK `game.dat` 2.01.2614.37001, ImageBase `0x400000`. The write-up behind
`rebuild-hole-repair`, in
[`patches/experimental/rebuild_hole_repair.py`](../patches/experimental/rebuild_hole_repair.py).

Two defects, one function. Sections 1–4 cover the first: `RebuildHoleExposeDie::onDie` refuses to
make a hole for a structure that is still going up. §6 records what a running game showed when
that branch was erased — the hole is created, and it spawns buried, because `onDie` also copies the
dying object's height onto it. Sections 7–9 are the second defect and its fix. The patch closes
both, because closing only the first is what exposes the second.

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

`0x00889B0E` is the first defect. A lair killed in the window between "the hole started rebuilding
it" and "the rebuild finished" runs `onDie`, reaches this branch, and returns without creating
anything. The lair is then destroyed for good: no hole, no rebuild, and — because treasure hangs
off the *hole's* `CreateObjectDie`, not the lair's — no treasure, ever again.

The hole that spawned it is already gone, killed by `0x00886C3A` in the frame the rebuild began, so
there is nothing left to carry the loop.

Six bytes. A scan of every branch displacement and imm32 in the image finds no inbound edge into
them, so they are replaceable in place.

## 3. Why the gate is deleted rather than narrowed

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

## 4. What downstream of the gate depends on the object being finished

Everything `onDie` does after the gate reads only the dying object's position (`+0x38`), angle
(`+0x44`), team (`+0x31c`), id (`+0x74`) and template (`+4`), plus moduleData. The angle, team, id
and template do not differ between a finished lair and one at 5% construction, and the template it
hands to `startRebuild` is the lair either way — so the hole created from a half-built lair
rebuilds the same thing the hole created from a finished one does.

**The position does differ, and it is load-bearing.** That is the second defect, and §7 is about
it. It is a flaw in the death path rather than in the gate, and it is invisible in a stock game
only because the gate stops a hole from ever being made there to reveal it.

## 5. What was not established statically — resolved in §6

The static write-up left three things open. §6 closes them against a running game:

- **Does the death reach `onDie` at all?** Yes — a lair killed mid-rebuild creates its hole.
- **The two upstream player gates** (`0x00889AE7`, `0x00889AFD`) — these *are* on the path, ahead
  of the erased branch. Runtime shows they pass for a rebuilding lair, because it carries the same
  owner as an intact one.
- **The retiring first hole.** Watched: it retires with `FADED` (no payout) the moment its lair
  dies, exactly as designed. It does not fight the new hole.

## 6. Runtime verification (2026-08-23): the hole spawns, but buried

Watched live against `C:\RotWK\game.dat` carrying the gate erase alone (present and confirmed in
the running process — the six bytes at `0x00889B0E` read back `66 0f 1f 44 00 00`, the `nop`, via
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

**The hole is created — erasing the gate works.** On killing lair 361:

```
frame 2794   361 DunlandGoblinLair   3.6%  UNDER_CONSTRUCTION
frame 2795   359 DunlandLairHole      0%   -     ; original hole retires (FADED)
             361 DunlandGoblinLair     0%   -     ; the rebuilding lair, dead
             362 DunlandLairHole    100%   -     ; *** a new hole, created by 361's onDie ***
frame 2805   362 DunlandLairHole    100%   -     ; persists, alone
```

So a lair destroyed mid-rebuild *does* leave a hole once the gate is gone. The erased branch was
the only logic suppressing it, and the two upstream gates pass. That half is confirmed on hardware.

**But the hole spawns underground.** The new hole 362 is stable — 100% health, not sinking, not
retiring, across every sampled frame (2945–2994) — yet it sits at **Z = 280.4** while the lair it
replaced, the hole before it, and every intact lair on the map all sit at **Z ≈ 396**. It is ~116
units below the surface, so it cannot be seen or clicked, and holes are `NOT_AUTOACQUIRABLE`, so it
cannot be loot-targeted either. It still rebuilds the lair underneath. From the player's chair this
reads as "I killed it, no hole appeared, the lair just grew back" — the reported bug again.

**Control — a built lair drops its hole correctly.** Killing an intact, fully-built lair in the
same session:

```
397 DunlandLairHole  (2488, 2956)  Z=396.0  100%   ; from a BUILT lair — ground level
—   DunlandLairHole  ( 905,  865)  Z=280.6  100%   ; from the rebuilt lair — buried
```

So the burial is specific to the `UNDER_CONSTRUCTION` death path, not to `onDie` in general.

## 7. Where the height comes from

`onDie` makes the hole and then copies the dying object's position onto it verbatim:

```
00889b40  mov  ecx, [0xde4a40]           ; TheThingFactory
00889b46  push eax                       ; the hole's ThingTemplate
00889b47  call 0x6d165e                  ; newObject
00889b4c  mov  edi, eax                  ; edi = the new hole
00889b4e  lea  eax, [esi + 0x38]         ; the *dying object's* Coord3D
00889b51  push eax
00889b52  mov  ecx, edi
00889b54  call 0x70c201                  ; Object::setPosition(hole, &pos)
00889b59  fld  dword ptr [esi + 0x44]    ; ... then its angle, team, id, template
```

`esi` is the dying `Object`, `edi` the fresh hole. `Object::setPosition` (`0x0070C201`) is
`__thiscall`, one `Coord3D *`, `ret 4` (`0x0070C31B`) — so the eleven bytes at `0x00889B4E` are
one self-contained "place the hole where the corpse is" step, and replacing them replaces the
whole decision.

Nothing branches into them. Every byte from `0x00889B4E` to `0x00889B58` inclusive has zero
inbound `call`/`jmp`/`jcc` edges and zero dword references anywhere in the image, so all eleven
are free to rewrite in place.

## 8. What the height should be

`TheTerrainLogic` is `0x00DE4690`, registered at `0x0062D0C9`:

```
0062d0c3  call dword ptr [eax + 0x38]    ; GameEngine::createTerrainLogic
0062d0c9  mov  dword ptr [0xde4690], eax
0062d0d9  push 0xbfdbd0                  ; "TheTerrainLogic"
```

Its ground-height query is vtable slot `+0x18`, and the engine's own call shape is unambiguous —
`Object::getHeightAboveTerrain` (`0x0070BC6E`) is nothing but that call and a subtraction:

```
0070bc6e  mov  ecx, [0xde4690]
0070bc74  fld  dword ptr [esi + 0x3c]    ; y
0070bc77  mov  eax, dword ptr [ecx]
0070bc79  push 0                         ; Coord3D *normal = NULL
0070bc7b  push ecx                       ; two dwords of scratch for x and y
0070bc7c  push ecx
0070bc7d  fstp dword ptr [esp + 4]       ; [esp+4] = y
0070bc81  fld  dword ptr [esi + 0x38]
0070bc84  fstp dword ptr [esp]           ; [esp]   = x
0070bc87  call dword ptr [eax + 0x18]    ; -> st0
0070bc8a  fsubr dword ptr [esi + 0x40]   ; z - groundHeight
0070bc8d  pop  esi
0070bc8e  ret
```

So the signature is `Real __thiscall TerrainLogic::getGroundHeight(Real x, Real y, Coord3D
*normal)`, returning in `st0` and cleaning its own twelve bytes of arguments — the `ret` above
follows the call with no `add esp`. The wrapper at `0x005E3999` (`leave; ret 8`) has the identical
shape, and the AI's structure placer uses the same call to seed a candidate site's `z`
(`0x009B5AE3`, [`ai-plot-builder.md`](ai-plot-builder.md) §1b). Three independent sites, one
convention.

## 9. The patch

Two edits. The six bytes at `0x00889B0E` become a single six-byte `nop word ptr [eax+eax]` — one
instruction rather than six `0x90`s, so a disassembler and `verify` read one erased branch instead
of pad bytes that could equally be leftovers. And the eleven bytes at `0x00889B4E` become a jump
into a cave that builds a corrected `Coord3D` and issues the one `setPosition` itself.

Hooking *before* the engine's call rather than after it means the hole is positioned exactly once,
so the partition, layer and drawable bookkeeping inside `setPosition` sees the final value rather
than a buried one it has to be corrected out of.

`esi` (dying object), `edi` (the hole) and `ebx` (moduleData) are all live and all callee-saved
across both calls; `eax`, `ecx` and `edx` are already dead at the hook, which is what makes the
sequence free. The x87 stack is empty here — the next stock instruction, `fld [esi+0x44]`, starts
its own — and the cave's one `fstp` balances its one implicit push.

```asm
    sub  esp, 0x0c                  ; a Coord3D on the stack
    mov  eax, [esi+0x38]            ; x  = the corpse's x
    mov  [esp], eax
    mov  eax, [esi+0x3c]            ; y  = the corpse's y
    mov  [esp+4], eax
    mov  eax, [esi+0x40]            ; z  = the corpse's z, the stock answer
    mov  [esp+8], eax
    mov  ecx, [0x00de4690]          ; TheTerrainLogic
    test ecx, ecx
    je   place                      ; no terrain: keep the stock answer
    mov  eax, [ecx]
    push 0                          ; normal = NULL
    push dword [esi+0x3c]           ; y
    push dword [esi+0x38]           ; x
    call dword [eax+0x18]           ; getGroundHeight -> st0, ret 0xC
    fstp dword [esp+8]              ; z = the ground under (x, y)
place:
    mov  eax, esp
    push eax
    mov  ecx, edi                   ; the hole
    call 0x0070c201                 ; Object::setPosition, ret 4
    add  esp, 0x0c
    jmp  0x00889b59                 ; back into onDie, at the angle copy
```

72 bytes, in a `.rhrep` section allocated past every existing one. The placement hook is
`jmp rel32` followed by two `nop`s filling out the eleven stolen bytes.

The addresses are `REBUILD_HOLE_CONSTRUCTION_GATE` (`0x00889B0E`) and its six stock bytes,
`REBUILD_HOLE_SET_POSITION` (`0x00889B4E`) with its eleven, `REBUILD_HOLE_SET_POSITION_RESUME`
(`0x00889B59`), `OBJECT_SET_POSITION` (`0x0070C201`), `THE_TERRAIN_LOGIC` (`0x00DE4690`),
`TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT` (`0x18`) and `OBJECT_GET_HEIGHT_ABOVE_TERRAIN`
(`0x0070BC6E`).

That last one is what the patch anchors the terrain call on. A `.data` global holds nothing in a
file on disk, so `THE_TERRAIN_LOGIC` cannot be asserted directly; `Object::getHeightAboveTerrain`
is 28 bytes that load exactly that global, call exactly that slot, and clean nothing off `esp`
afterwards — so asserting them pins the address, the slot and the calling convention at once.

## 10. Why the snap is unconditional

A built lair's hole already appears at ground level (§6, the control case: `z = 396.0`, matching
every intact lair on the map). For that case the terrain lookup returns the value the object
already carries, so the write is a no-op and the healthy path is unchanged. Only the corpse whose
`z` has drifted from the terrain moves — which is precisely the set the fix is for. Testing
`UNDER_CONSTRUCTION` to decide whether to snap would add a branch that never changes an outcome.

Two things this trades away, both worth stating rather than discovering later:

- **Layers are ignored.** `getGroundHeight` answers for the terrain, not for a bridge or a
  walkable wall top. A rebuild hole on a raised surface would be pulled down to the ground under
  it. `TerrainLogic::getLayerHeight` (vtable `+0x1C`, used at `0x006F07C3` —
  [`wall-layer-promotion.md`](wall-layer-promotion.md) §3) with the dying object's layer
  (`Object::getLayer`, `0x0068BBE0`) is the faithful variant. No stock RotWK or Edain data places
  a `RebuildHoleExposeDie` structure on a layer, so the simpler call is the one shipped; the note
  is here so the upgrade path is known.
- **It reaches every `RebuildHoleExposeDie`, not only the mid-rebuild case**, exactly as the gate
  erase does. That is the point — a hole belongs on the ground whatever killed the thing above it.

## 11. Determinism and composition

Creating an object and deciding where it lands are both logic state, so every peer must run the
same patched binary, and replays do not cross between patched and unpatched. `getGroundHeight`
reads the loaded terrain, which is identical on every peer, so the added call introduces no new
divergence of its own.

Composition is clean. The cave goes in its own appended section, so it is order-independent with
every other section-adding patch. The only engine bytes edited are the six at `0x00889B0E` and the
eleven at `0x00889B4E`, which no other bundled patch touches — they all sit at `0x0079`, `0x008A`,
`0x0094` and `0x00DA`.

## 12. Open question: where the bad `z` comes from

Not needed for the fix — snapping to terrain is correct whatever sank the corpse — but unresolved,
and someone will ask.

`StructureCollapseUpdate` carries `CollapseHeight` (moduleData `+0xF8`) and
`DestroyObjectWhenDone` (`+0xF4`), and `396 − 280.4 = 115.6` against the Dunland lair's
`CollapseHeight = 120` is a close enough match to be the obvious culprit. But §6's own observation
does not fit cleanly: lair 361 was watched at 19% built sitting at `z = 396`, ground level, so an
under-construction structure is not simply parked at the bottom of its rise. Something moves it
between there and the frame `onDie` reads its position.

The experiment that settles it is cheap: `sage_live watch` the object's `z` (`Object+0x40`) across
the frames from lethal damage to `onDie`, on a lair killed mid-rebuild. If it steps downward over
several frames, the collapse is doing it and `onDie` runs at the end of the collapse rather than at
the moment of death — which would be a fact worth writing down on its own.

## 13. What is not yet done

The patch as it stands is **static only**, which is why it is experimental. The gate erase has been
played (§6) and the ground snap has not: it applies to a clean `game.dat`, `sage-patch verify`
confirms the result carries it, and the cave is unit-tested by disassembling it back — but a wrong
reading of the machine code passes both, because the tests are written from the same reading. What
is missing:

- A runtime confirmation on the footing of §6: kill a lair mid-rebuild with this patch applied, and
  check the new hole reads `z ≈ 396`, is clickable, and pays its `CreateObjectDie` treasure when
  broken.
- A check on the healthy path, which is the one the snap could regress: kill an intact lair and a
  regular rebuildable structure and confirm their holes land where they always did.
- §12's open question.
