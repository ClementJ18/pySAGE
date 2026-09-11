# A garrison that heals but never refills — the `contained-horde-respawn` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read out of the installed
`game.dat`.

**Verdict:** five bytes and a 228-byte cave. `AutoHealBehavior::update` is an if/else chain over
four `ModuleData` flags, and `RespawnNearbyHordeMembers` is read at **exactly one site in the whole
image**, inside the last of the four arms. `AffectsContained` is the arm above it and returns
first, so the two keywords are mutually exclusive as shipped and no module in the engine can
replenish a battalion that is inside something. The patch hooks the `AffectsContained` arm's own
closing `jmp` and runs the same respawn block over the container's passengers. **Static-verified**:
it applies, verifies and disassembles as intended, every anchor is confirmed against the real
binary, and the cave is a decoded-instruction-for-decoded-instruction copy of the stock block — but
a replenished garrison has not been watched in a running game.

## 1. The symptom

A garrison tower carries an `AutoHealBehavior` that is meant to keep the battalion inside it topped
up:

```
Behavior = AutoHealBehavior ModuleTag_HearthHeal
    StartsActive              = Yes
    AffectsContained          = Yes
    RespawnNearbyHordeMembers = Yes
    RespawnFXList             = FX_BannerCarrierSpawnUnit
    RespawnMinimumDelay       = 1
    HealingDelay              = 10000
    HealingAmount             = 35
End
```

The healing works. The replenishment never happens, at any value of any field, and adding a second
module with a `Radius` does not help either.

## 2. The update is an if/else chain

`AutoHealBehavior::update` is `0x008558C0`, slot 0 of the `UpdateModule` vtable at `0x00C564F8`
which the constructor stores at module `+0x10` (`0x00855673`). `getModuleName` at `0x00855415`
(`mov eax, 0xC0BED4 ; ret`) ties the whole block to `AutoHealBehavior` by name. `this` is the
sub-object, so the body opens by reaching back past it:

```
008558e4  push ebx
008558e5  mov  ebx, [ecx-0xc]        ; the ModuleData, kept in ebx for the whole function
008558e8  lea  eax, [ecx-0x10]       ; the module base
008558eb  push esi
008558ec  mov  esi, [ecx-0x8]        ; the Object
008558ef  lea  ecx, [eax+0x20]
008558f2  mov  [ebp-0x20], eax       ; the module base, in a frame slot nothing else writes
```

Past the upgrade gate, the effectively-dead test and `HealOnlyIfNotInCombat`, the healing amount is
computed once and the function forks four ways:

| order | field tested | site | what it does |
|---|---|---|---|
| 1 | `AffectsWholePlayer` (`+0x14C`) | `0x00855965` | walks every object of the owning player, heals each, returns `HealingDelay` |
| 2 | `AffectsContained` (`+0x14D`) | `0x00855A25` | heals the passengers, then jumps to the shared tail |
| 3 | `Radius == 0` (`+0x148`) | `0x00855AC6` | heals only its own object |
| 4 | otherwise | `0x00855B04` | a partition range scan — **and the respawn** |

A scan of `.text` for every instruction carrying a `0x175` displacement finds two: the constructor's
default store at `0x00654BB5`, and one read, at `0x00855D1C`. That read is inside arm 4's per-object
loop. `RespawnFXList` (`+0x178`) is likewise read only at `0x00855D85` and `RespawnMinimumDelay`
(`+0x17C`) only at `0x00855B04`. `AffectsContained` has one read too, the `cmp` at `0x00855A25` that
opens arm 2.

So the entire respawn feature lives inside the arm that arm 2 returns before reaching, and the two
keywords cannot both take effect. That is the whole bug, and it is a structural one rather than a
mistake in a condition.

## 3. Arm 4's respawn, which is what gets transcribed

The gate is computed once, above the scan:

```
00855b04  mov  ecx, [ebx+0x17c]      ; RespawnMinimumDelay - an Int of raw frames, not a Duration
00855b0a  mov  edx, [ebp-0x18]       ; the UpdateModule sub-object
00855b0d  mov  eax, [0xde412c]       ; TheGameLogic
00855b12  mov  eax, [eax+0x40]       ; ->frame
00855b15  add  ecx, [edx+0x24]       ; + the frame the last respawn was stamped at
00855b1b  cmp  eax, ecx
00855b1d  sbb  al, al
00855b1f  inc  al
00855b21  mov  [ebp-0xd], al         ; respawnAllowed = now >= last + RespawnMinimumDelay
```

`[edx+0x24]` on the sub-object is `+0x34` on the module base, which the constructor zeroes at
`0x0085568D`. Arm 4 stamps it back at `0x00855DBE`, whenever the gate was open, respawn or no
respawn.

The respawn itself is `0x00855D16` to `0x00855D97`, reached once per object the scan returns and
reached whether or not that object was healed:

```
00855d16  cmp  byte [ebp-0xd], 0            ; the delay gate
00855d1c  cmp  byte [ebx+0x175], 0          ; RespawnNearbyHordeMembers - the only read in the image
00855d25  mov  eax, [esi+4]
00855d28  test byte [eax+0x115], 0x20       ; KindOf HORDE, bit 109
00855d31  push 2                            ; ObjectStatus UNDER_CONSTRUCTION
00855d35  call 0x0044ddec
00855d40  call 0x0068c866                   ; Object::getHordeIface
00855d50  call [edx+0x17c]                  ; the contain's Slots
00855d5e  call [eax+0x188]                  ; the live member count
00855d64  cmp  eax, [ebp-0x24]              ; count >= Slots -> skip
00855d6e  add  esi, 8                       ; &Object::m_transform
00855d72  call [eax+0x18c]                  ; create one member there
00855d80  call 0x0068c7e9
00855d92  call 0x004b1b5a                   ; RespawnFXList, through the null-safe wrapper
```

The three interface slots are the banner carrier's own machinery. `+0x17C` (`0x0086C8DE`) reads
`Slots` off the contain's module data, answering `0` where there is none; `+0x188` (`0x0086C09B`)
is the live count; `+0x18C` (`0x00873AE3`, `ret 4`) creates a member at a `Matrix3D *` and returns
it. `0x0068C7E9` is `__thiscall` with no arguments: it reaches a virtual base through the vbtable at
`Object+0x68`, calls that base's vtable `+0x10`, and hands a non-NULL answer to `0x00B4F410`, which
unlinks a node from a doubly-linked list and frees it. What the node is has not been established;
one of its ten callers is the engine's own change-of-owner path at `0x0068DAAE`.

## 4. Why no INI arrangement works

**Two modules do not work.** Splitting the fields across an `AffectsContained` module and a `Radius`
module puts the respawn in arm 4, where it acts on whatever the partition scan returns rather than
on the passengers. The scan is a `ThePartitionManager` range query (`0x00855B8F`, filters for alive,
same on-map status, and an allied relationship) centred on the tower, so it can only reach the
garrison if a contained object keeps its partition registration. Whether it does was not settled
here.

**No other module covers it.** `ReplenishUnitsBehavior` is the only other module in the engine that
repopulates a horde, and its update issues the same kind of query at `0x008877CE`. There is no
contained-aware replenishment anywhere.

**Nor does moving the module.** Putting the radius module on the battalion itself makes it replenish
in the open field too, which is a different feature.

## 5. The patch

Arm 2 ends at one instruction with nothing else in it:

```
00855ab9  lea  ecx, [ebp-0x18]
00855abc  call 0x005eaea2                   ; the arm's list destructor
00855ac1  jmp  0x00855dcd                   ; e9 07 03 00 00   <- the whole hook site
```

Those five bytes become a jump into a `.cnthrd` cave that ends by jumping to `0x00855DCD` itself, so
the sleep the module asks for is untouched and no other arm sees a changed instruction.

### 5.1 What is live at the hook

`ebx` is the `ModuleData` and stays so all the way to the tail, which reads `SingleBurst` and
`HealingDelay` off it. `edi` is the `ContainModuleInterface` arm 2 selected — the object's own
(`0x00855A32`) or, for a module sitting on a passenger, the one containing it (`0x00855A4A`). Both
registers are callee-saved and the only calls since `edi`'s last write are
`AutoHealBehavior::healObject` (`0x00855761`, which visibly pushes and pops `edi`) and the list
destructor, so both hold what arm 2 put in them.

`esi` is dead, having been the arm's list cursor. The module base is **not** in `[ebp-0x18]` any
more: that slot held the `UpdateModule` sub-object at the top of the function and was reused as arm
2's list head at `0x00855A5C`. `[ebp-0x20]` still holds the module base, written once at
`0x008558F2`, which is why the cave reaches the respawn timestamp as `+0x34` off the base rather
than as arm 4's `+0x24` off the sub-object.

### 5.2 The entry

```
cmp  byte [ebx+0x175], 0        ; RespawnNearbyHordeMembers - off, and we leave
je   leave
mov  edx, [ebp-0x20]            ; the module base
mov  ecx, [ebx+0x17c]           ; RespawnMinimumDelay
add  ecx, [edx+0x34]            ; + the last respawn frame
mov  eax, [0xde412c]
mov  eax, [eax+0x40]            ; TheGameLogic->frame
cmp  eax, ecx
jb   leave
or   dword [ebp-4], 0xffffffff  ; see below
mov  [edx+0x34], eax            ; stamp, as arm 4 does at 0x00855DBE
push 1
push ebx                        ; the ModuleData, as userData
push <callback>
mov  ecx, edi
mov  eax, [edi]
call [eax+0x110]                ; iterateContained
leave:
jmp  0x00855dcd
```

Three things are worth saying out loud.

**It iterates through the slot arm 2 just used.** `0x00855A64` is the arm's own call:

```
00855a64  mov  edx, [edi]
00855a69  push eax                    ; 1
00855a6a  mov  [ebp-4], eax           ; the SEH scope index
00855a70  push eax                    ; &list
00855a71  push 0x0085584b             ; the callback
00855a78  call [edx+0x110]
```

so the slot, the argument order and the callback ABI are all read off the engine rather than
assumed. `0x0085584B` ends in a plain `ret`, which says the iterator cleans the two arguments; the
cave's callback does the same. Walking `CONTAIN_ITEM_LIST` by hand would have been shorter and would
have assumed a layout for whichever contain the object happens to carry.

**It clears the scope index.** `__EH_prolog` (`0x008558C5`) makes `[ebp-4]` the scope index, and arm
2 sets it to `1` at `0x00855A6A` when it constructs its list. Unlike arm 4 at `0x00855DC1`, it never
resets it after destroying that list at `0x00855ABC` — harmless in stock, where three instructions
separate that from the return, but the cave adds calls there, and an unwind through them would run
the destructor on an already-destroyed list. Setting `-1` is what arm 4 does before its own last
destructor.

**It stamps before iterating, not after.** `edx` does not survive the calls, and arm 4's own stamp
is unconditional on the gate rather than on a respawn actually happening, so the two orders mean the
same thing.

### 5.3 The callback

`__cdecl(Object *passenger, AutoHealBehaviorModuleData *data)`, saving `ebx`, `esi` and `edi`. The
body is §3's block with the object coming from the argument instead of from a partition iterator,
and with the delay gate hoisted into the entry because it does not vary per passenger. Every gate,
slot, offset and call target is identical, which is what
`tests/sage_patch/test_contained_horde_respawn.py` asserts — decoding both and comparing, rather
than restating the numbers.

The one thing a reader cannot check by eye is the stack: a conditional taken with the spawn
argument still pushed would corrupt the iterator's frame and look fine. `+0x18C` is `ret 4` and
`0x0044DDEC` is `ret 4`, so both clean their own argument, and the `FXList` wrapper is `__cdecl` and
is balanced explicitly. `TestTheCallbackBalancesItsStack` walks all six exits and asserts the depth.

**It does not mutate the list it is walking.** The callback creates an object, which is a thing to
be careful about inside an iteration. The new member joins the *battalion's* contain, not the
container's: the tower holds the battalion as one passenger — which is why `ContainMax = 1` is what a
garrison tower writes — and the engine's own callback at `0x0085584B` **recurses** into a passenger's
contain when it finds a `KindOf HORDE` one, which it would not need to do if the members were in the
outer list already. So the list under iteration is one level above the one that grows. §8 records
the residual doubt.

## 6. What a mod has to write

Nothing new. `RespawnNearbyHordeMembers` is the switch it already was, and the INI in §1 starts
working. A module without `AffectsContained` never reaches the new code at all, so every existing
object in a mod behaves exactly as it did.

Two things stay true and are worth knowing:

- **`HealingDelay` is the real cadence.** The update reschedules itself that far out, so it is the
  ceiling on how often the respawn can run whatever `RespawnMinimumDelay` says. A mod wanting a
  faster replenish lowers `HealingDelay`.
- **The passenger has to be a battalion with room.** `KindOf HORDE`, not `UNDER_CONSTRUCTION`, a
  contain of its own, and live members below that contain's `Slots`. A transport full of individual
  units costs one `test` per passenger and does nothing.

## 7. Cost, and what is not touched

Per tick of a module that sets both keywords: one compare for the flag, four for the delay gate,
then one virtual call and, per passenger, one `test` before the great majority leave. A module that
sets `AffectsContained` without the respawn flag pays a single compare. Every other module in the
game pays nothing, because the five bytes are inside arm 2.

Arms 1, 3 and 4 are unmodified, and so is the healing arm 2 does before the hook — the cave runs
after it, on the same passengers, and adds to it rather than replacing anything.

## 8. What is still open

- **A running game has not been watched.** The claim that a member appears in the garrison is a
  reading of the machine code, checked by tests written from the same reading.
- **The partition question from §4 is unresolved.** It does not affect this patch, which never
  touches the partition manager, but it is what would decide whether the two-module INI workaround
  could ever have worked.
- **`0x0068C7E9` is a black box.** The cave calls it because the stock respawn calls it. What its
  list node is has not been established, and nothing here depends on knowing.
- **The iteration-safety argument in §5.3 is an inference, not a proof.** It rests on the stock
  callback's recursion, which is strong evidence that a container holds a battalion rather than its
  members, but `HordeGarrisonContain`'s own `addToContain` has not been read, and neither has
  `iterateContained`'s implementation — so whether that walk would tolerate a list growing under it
  is untested. A garrison with `ContainMax` above 1 holding several battalions is the case to watch
  first if this ever misbehaves.
