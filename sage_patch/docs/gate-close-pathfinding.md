# Closing a gate changes nothing the pathfinder can see

RotWK 2.01 `game.dat`, ImageBase `0x400000`. **Static recovery only — nothing here has been
confirmed against a running game.** §7 lists the runtime checks that would.

**The finding in one sentence.** Everything that separates an open gate from a closed one in the
pathfind grid is driven by the `GeometryForOpen` / `GeometryForClosed` lists on
`GateOpenAndCloseBehavior`, and no gate in the BFME2 or Edain data sets either list — so the
close transition removes the object from the pathfind map and puts back a byte-identical
footprint, leaving every in-flight path valid and every cell as passable as it was a frame
earlier.

## 1. What the module does on a state change

`GateOpenAndCloseBehavior` (registered at `0x006594CB`, class ctor `0x0089C04B`, instance
`0x4C` bytes, primary vtable `0x00C668E0`) keeps two separate states:

| field | meaning |
|---|---|
| `+0x28` | animation state — `0` opening, `1` open, `2` closing, `3` closed. `isOpen()` (`0x008DC9AB`) is `state == 1`. The ctor picks `1` or `3` from `OpenByDefault` at `0x0089C0A2`..`0x0089C0B3` |
| `+0x2C` | **pathing** state — `1` closed-for-pathing, `2` open-for-pathing |
| `+0x34` | transition percentage, `0`..`100` |
| `+0x40` | manual open/close lock counter, driven by the `TOGGLE_GATE` command button |

The two functions that move `+0x2C` are the whole story:

| | |
|---|---|
| `0x0089C9FA` | **close for pathing** — `+0x2C := 1` |
| `0x0089CA84` | **open for pathing** — `+0x2C := 2` |

They are the same routine mirrored, and each does exactly three things:

```
0089ca12  mov  eax, [0xde4b40] / mov ecx, [eax+0x10]   ; the Pathfinder
0089ca20  call 0x6e861e                                 ; remove object from pathfind map
0089ca2c  call 0x68be6b                                 ; object flag 9, cleared/set
          ; for each name in GeometryForOpen   (moduledata +0x2C .. +0x30)
0089ca44  call 0xad3520(obj+0xa8, name, 0)              ; deactivate that shape
          ; for each name in GeometryForClosed (moduledata +0x38 .. +0x3C)
0089ca59  call 0xad3520(obj+0xa8, name, 1)              ; activate that shape
0089ca6a  call 0x68b244(obj, 1)
0089ca78  call 0x6e85e9                                 ; add object to pathfind map
```

`0x006E85E9` and `0x006E861E` are one-line wrappers over
`Pathfinder::addOrRemoveObjectFromPathfindMap` (`0x00936B7D`), differing only in the add/remove
argument.

Which of the two is "closed" is fixed by `update()`. In the closing branch the transition
percentage climbs to `100`, at which point `setGateState(3)` runs (`0x0089CE46`), and on the way
there:

```
0089ce53  push 0x64 / pop eax
0089ce56  sub  eax, [edi+0x10]        ; 100 - PercentOpenForPathing
0089ce69  fld  [esi+0x20]             ; the transition percentage
0089ce6e  fcompi
0089ce70  jbe  0x89ce7f
0089ce77  call 0x89c9fa               ; past the threshold -> closed for pathing
```

## 2. The rasterizer honours a per-shape flag, and only that

`Pathfinder::addOrRemoveObjectFromPathfindMap` walks the object's `GeometryCollection` at
`obj+0xA8` and skips any shape whose byte at `+0x20` is zero:

```
00936e4c  mov  ecx, [ebp+0x70] / add ecx, 0xa8    ; the collection
00936e58  call 0xad1ae0                            ; shape i
00936e5f  cmp  byte [edi+0x20], 0
00936e63  je   0x937448                            ; shape inactive -> contributes nothing
```

`0x00AD3520` is the only writer reachable from the gate: it matches a shape by its
`GeometryName` (`repe cmpsb` at `0x00AD3576` against `[shape+0x1C]`), writes the caller's bool
into `[shape+0x20]`, and recomputes the collection bounds. Both shape constructors initialise
`[shape+0x20]` to `1` (`0x00AD3FEC`, `0x00AD408A`), so **every shape is active until something
deactivates it.**

## 3. Why that machinery never runs

`GeometryForOpen` and `GeometryForClosed` are `AsciiStringList` fields at moduledata `+0x2C` and
`+0x38`. Across the Edain and BFME2 INI trees, **not one `GateOpenAndCloseBehavior` sets either
field** — while 54 objects define a `GeometryName = Closed` shape and about 52 define
`OpenLeft` / `OpenRight`. The named shapes the design expects are all present; only the wiring
that tells the module about them is missing.

With both lists empty the two loops in §1 iterate zero times. A close therefore reduces to
*remove the object from the map, then add the same object back with the same active shapes* —
the grid ends up in the state it started in.

The stock Men castle gate is representative:

```
Behavior = GateOpenAndCloseBehavior ModuleTag_GATE
    ResetTimeInMilliseconds = 12200
    OpenByDefault           = Yes
    PercentOpenForPathing   = 50
    ...                                  ; no GeometryForOpen, no GeometryForClosed
End
Geometry            = BOX    ; GeometryName = Closed      (16 x 72 x 56, spans the doorway)
AdditionalGeometry  = BOX    ; GeometryName = OpenLeft    (21 x 2, one door leaf)
AdditionalGeometry  = BOX    ; GeometryName = OpenRight
```

## 4. The cell "gate" bit is inert

`PathfindCell` packs its state into the dword at `+0xC`; **bit 17 is the gate bit**, written only
by `PathfindCell::setGate` (`0x0093496C`). The write sites in the map update
(`0x0093715F`, `0x009373E6`) set the bit to the add/remove argument, and the "is this a gate"
local is decided from the KindOf alone:

```
00936ce2  test byte [eax+0x119], 2     ; BLOCKING_GATE
00936ce9  jne  0x936cf3
00936cf3  mov  byte [ebp+0x7f], 1
```

So the bit tracks *a gate object is registered here*, never *the gate is shut*.

`PathfindCell::isPassable` (`0x006E8200`) consults it once:

```
006e826a  cmp  byte [edi+4], 0        ; constraint: mover cannot path through gates
006e826e  je   0x6e827a
006e8272  shr  ecx, 0x11              ; cell gate bit
006e8278  jne  0x6e822b               ; impassable
```

`constraint+4` is built as `CanPathThroughGates == 0` (`0x006EB180`..`0x006EB19B`, one of ~30
identical inline sites), and the `ThingTemplate` constructor defaults that field to **Yes**:

```
0074004a  inc  edx
0074004b  mov  byte [ebx+0x644], dl   ; CanPathThroughGates = 1
```

Across the whole Edain tree only two objects opt into `Yes` explicitly and 22 opt out with `No`.
Everything else inherits `Yes`, so the gate bit blocks essentially nobody, in either state.

## 5. The only thing a close actually changes

`GateOpenAndCloseBehavior::onCollide` (`0x0089C6F5`) is the sole consumer of the pathing state:

```
0089c6f8  mov  eax, [esi+8] / cmp byte [eax+0x18], 0   ; RepelCollidingUnits
0089c701  cmp  dword [esi+0x2c], 1                      ; closed for pathing
0089c70d  call 0x89c33a                                 ; collider is non-IMMOBILE and on layer 1
0089c719  mov  edi, [ebp+0x260]                         ; the collider's AIUpdate
0089c729  call 0x8dbace / cmp eax, gate -> skip
0089c737  call 0x668303 / cmp eax, gate -> skip         ; AI current victim
0089c74d  call 0x89c5a2                                 ; repel
```

A shut gate pushes colliders away — **except** any unit whose AI is currently targeting the gate,
which is exactly an attack-moving army. Nothing here invalidates a path; nothing here consults
the relationship between the collider and the gate's owner.

## 6. The pass EA wrote and never called

Two sibling methods on the gate manager exist and are reachable from nothing in the image —
`explore.py xref` reports zero dword references and zero direct branches for both:

| | |
|---|---|
| `0x008ED65C` | for each registered gate that is `!isOpen()` and whose owner is `ALLIES` with the passed player, call `0x0089CA84` — *open the closed gate for pathing* |
| `0x008ED69D` | the same walk, calling `0x0089C9FA` — *put it back* |

That pair is the shape of a correct implementation: flip allied closed gates open for the
duration of one player's path request, then restore them, so a closed gate is a wall to
everybody else. It is dead code.

`FakePathfindPortalBehaviour` is a separate, live mechanism and is not the leak.
`FakePathfindPortal::isAllowedThrough` (`0x0068229C`) requires `ALLIES` with the gate's owner
when `AllowEnemies = No`, and a skirmish-AI controller when `AllowNonSkirmishAIUnits = No`. It
never asks the gate whether it is open, but it also never grants an enemy passage.

## 7. What is not established

The one link this write-up does not close: whether a gate's doorway cells are currently stamped
as obstacle cells (`PathfindCell` type `4`, impassable to a ground locomotor per the cell-type
surface table at `0x00DA2444`) or left clear. `0x00937116` calls the obstacle stamp
(`0x0093485A`) on the gate branch without an exception, which would make the doorway permanently
impassable — inconsistent with units walking through their own open gates. Either an earlier
branch of `0x00936B7D` diverts gates, or the gate's shapes never reach the rasterizer at all.
Reading the remaining ~3 KB of `0x00936B7D` settles it; so does one live check.

The runtime checks, in order of cost:

1. Add `GeometryForOpen = OpenLeft OpenRight` and `GeometryForClosed = Closed` to one gate's
   `GateOpenAndCloseBehavior`, then watch whether enemy AI pathing around that gate changes when
   it shuts. This exercises the machinery in §1 and §2 end to end and needs no binary change.
2. With `sage_live`, read `[module+0x2C]` across a manual `TOGGLE_GATE` to confirm the pathing
   state actually flips, and confirm `[shape+0x20]` for `Closed` stays `1` in both states.
3. Watch the cell dword at `+0xC` for a doorway cell across a close to see whether the type
   nibble or bit 17 moves at all.
