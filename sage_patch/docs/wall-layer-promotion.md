# An object standing inside a wall's footprint is teleported onto the wall

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Shipped as
[`../patches/experimental/wall_layer_promotion.py`](../patches/experimental/wall_layer_promotion.py),
which implements §7.
**Confirmed against a running game on 2026-09-21**
(§6): a trebuchet really is put on a wall-height layer, and its z really does become the wall's
height. The same run refuted §3's separability claim and found a layer the number space below did
not have — both recorded in §6.

**The finding in one sentence.** Every wall stamps its own *layer number* into the pathfind cells
its `WallBoundsMesh` covers, and once per movement re-evaluation the engine reads the cell under an
object's centre and, if that cell names a layer whose surface is more than 10 units above the
object, moves the object to that layer — which resolves its ground height to the wall top. The
promotion reads neither the object's `ThingTemplate` nor its `Locomotor`, so no INI field on the
promoted object can prevent it.

## 1. Two different layer spaces

`isWallLayer` (`0x006E82B3`) is the whole definition:

```
006e82b3  cmp dword [esp+4], 0x11 / jl  -> 0
006e82ba  cmp dword [esp+4], 0x40 / jg  -> 0
006e82c1  -> 1
```

| layer numbers | what they are | where the cells live |
|---|---|---|
| `1` | ground (`Object::getLayer` returns this) | the main grid, `Pathfinder+0x10` |
| `2`..`15` | the 16-slot layer objects at `Pathfinder+0x60`, stride `0x40` — bridges and the raised walkable wall surfaces | each slot's own sparse grid, `slot+0x04` |
| `16` | a layer of its own, **observed live and not in `isWallLayer`'s range**; `getLayerHeight` gives it a dedicated arm (`cmp eax, 0x10` at `0x006F0B58`, then the position predicate `0x006E89EE`). Every object seen standing on a wall alternated between `16` and a wall-height layer | the ground grid, as below |
| `17`..`64` | **wall-height layers** — a wall's *bounds*, not its walkable top | none of their own; see below |

`Pathfinder::getCell(layer, cellX, cellY)` (`0x005E2E9C`) consults a slot grid **only** for
`2 <= layer <= 15` (`0x005E2EC1`/`0x005E2EC6`, `lea ecx,[eax*0x40 + esi + 0x60]`). Every other
layer — a wall-height layer included — falls through to the ground grid at `[Pathfinder+0x10]`
(cell stride `0x10`). **So a wall-height layer's stamp lives on ordinary ground cells**, which is
what makes a ground unit able to read it.

Three arrays are indexed by wall layer, all in the `Pathfinder`:

| | |
|---|---|
| `+0x1BE78 + layer*4` | the layer's surface height (`Real`) |
| `+0x1BF78 + layer*4` | the object that defined it |
| `+0x1BEB8` | **count** of wall layers in use; `+0x1BEBC` is entry 0, i.e. layer `17` |

The `+0x11` is explicit at `0x00936307`. Registration walks the existing heights looking for one
close enough to share (`0x009362DD`..`0x00936315`, the two `.rdata` literals
`' has a wall height of '` / `" but there's already a wall with a height\nof "`) and otherwise
allocates a new layer at `count + 0x11`:

```
009362c0  cmp  dword [esi+0x1beb8], edi        ; count
009362d4  lea  eax, [esi+0x1bebc]              ; &heights[17]
009362e3  fsub dword [eax]                     ; h - heights[i]
009362ea  call 0xa3cf8a                        ; fabs
00936307  lea  ebx, [edi+0x11]                 ; layer := i + 17
```

## 2. The stamp

`PathfindCell` packs its state into the dword at `+0xC`: **bits 0..3 the cell type, bits 4..9 the
layer**. `PathfindCell::setLayer` (`0x007681BB`) is the only writer:

```
007681d4  shl eax, 4 / xor eax, edx / and eax, 0x3f0 / xor eax, edx
007681e0  mov dword [ecx+0xc], eax
```

It is reached from `0x00935051`, the per-cell step of the wall registration described in
[`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md) §3. That routine converts the cell to
world space (`imul eax, eax, 0xa` — **one cell is 10 world units**), tests the cell's four corners
against the `WallBoundsMesh` polygon (`0x006E4DC7`), and stamps the layer if any corner is inside —
keeping the taller wall where two overlap:

```
0093511e  movss  xmm0, [ebx + eax*4 + 0x1be78]   ; height of the layer being applied
00935127  comiss xmm0, [ebx + esi*4 + 0x1be78]   ; height of the layer already on the cell
0093512f  jbe    -> skip                          ; the taller wall keeps the cell
00935134  call   0x7681bb                         ; PathfindCell::setLayer
```

## 3. The promotion — `0x006F0741`

`__thiscall` on the `Pathfinder` (`TheAI+0x10`, `TheAI = 0x00DE4B40`), `ret 4`, one `Object *`:

```c
void Pathfinder::updateObjectLayer(Object *obj)          // 0x006F0741
{
    layer = obj->getLayer();                             // 0x0068BBE0
    cell  = this->getCellUnderObject(obj);               // 0x006EF30E - getCell(obj->getLayer(), x, y)
    pos   = obj->pos;                                    // Object+0x38 / +0x3C / +0x40
    if (!cell) return;
    cl = (cell->[+0xC] >> 4) & 0x3F;
    if (cl == layer) return;

    if (TheTerrainLogic->getLayerHeight(pos.x, pos.y, cl, 0, 1) > pos.z + 10.0f)
        obj->setLayer(cl);                               // 0x0068BB9D   <-- the teleport

    for (i = 2; i <= 15; i++) {                          // the bridge / raised-surface slots
        if (!slotInUse(&this->slot[i])) continue;        // 0x00768326
        c = this->getCell(i, &pos);                      // 0x005E2EF2 -> 0x005E2E9C
        if (!c || c->layer != i || (c->[+0xC] & 0xF) == 5) continue;
        if (fabs(getLayerHeight(pos.x, pos.y, i) - pos.z) < 10.0f) { obj->setLayer(i); break; }
    }
}
```

The comparison direction, which is the whole bug, is worth spelling out. `10.0f` is `0x00BD83D8`:

```
006f079b  fld   [ebp-8] / fadd [0xbd83d8]      ; z + 10
006f07c3  call  dword [edx+0x1c]               ; TheTerrainLogic::getLayerHeight -> st0
006f07c6  fld   [ebp+8] / fxch st(1)           ; st0 = h, st1 = z+10
006f07cb  fcompi st(1)
006f07cf  jbe   0x6f07e2                       ; h <= z+10  ->  no promotion
006f07dd  call  0x68bb9d                       ; h  > z+10  ->  setLayer(cellLayer)
```

So the promotion fires precisely when the layer's surface is **above** the object: an object whose
centre sits on a cell inside a wall's bounds, at ground level, is put on the wall.

The loop is the *bridge* path (`2..15`), and its rule is the opposite one — the object's z must
already be within 10 units of the surface. Legitimate arrival on a walkable wall top goes through
that loop, not through the branch above. **This split is what makes the two separable**, and it is
the load-bearing claim §6 has to check.

`Object::setLayer` (`0x0068BB9D`) writes `Object+0x428` and unregisters from the old layer through
`TheTerrainLogic` vtable `+0xAC`; `Object::getLayer` (`0x0068BBE0`) returns a forced `1` while
`Object+0x4AC` is set (the saved-position state at `Object+0x4A0`..`+0x4B0`). Once `+0x428` names a
wall layer, `getLayerHeight` (`0x006F0B27`) returns the constant `Pathfinder+0x1BE78[layer]` with
normal `(0,0,1)` (`0x006F0B96`..`0x006F0BCF`) — the object is on top of the wall, level.

## 4. Nothing on the promoted object is consulted

Every call `0x006F0741` makes: `Object::getLayer`, `getCellUnderObject`, `getLayerHeight` (×2),
`Object::setLayer` (×2), the slot-in-use predicate, `getCell`, `fabs`. It never dereferences
`Object+0x04` (the `ThingTemplate`) and never reaches the `Locomotor`. There is no `KindOf` test,
no `Surfaces` test, no status-bit test.

In particular **`ScalesWalls` is not on this path.** `Object::canScaleWalls` (`0x0068B331` —
`obj->[+0x260]->[+0x1F0]` = the current `Locomotor`, `->[+4]` = its template, `->[+0x150]` =
`ScalesWalls`) has nine callers, and all nine are *pathfinding queries*: `0x006EA563`, `0x006EA796`,
`0x006EE162`, `0x006EE4C5`, `0x006EF94D`, `0x006F08D3`, `0x006F55A6`, `0x006F897B`, `0x006FAD9E`.
It decides whether a **path** may be routed over wall cells. It has no say in where an object that
is already standing on one ends up.

## 5. How a siege unit gets there

The promotion is re-evaluated from at least four sites; the one that matters for a unit shoved into
a wall is inside `AIUpdateInterface` (`AIUpdate+0x140` is the path, freed here; `Object+0x260` is
the module):

```
0066cc58  call 0x68bbe0                    ; obj->getLayer()
0066cc65  call 0x6ea4e7                    ; is this position still valid on that layer?
0066cc6c  je   0x66ccea                    ;   no -> ...
0066cc8c  mov  edi, [esi+0x140]            ; the current path
0066cc98  call 0x7666ff / 0x42f6a0         ;   destroyed and freed
0066cca3  and  dword [esi+0x140], 0
0066ccb4  call 0x6f0741                    ; <- re-evaluate the layer
```

That is the shape of the symptom: collision resolution pushes the unit's centre into a cell the
wall's bounds cover, the position stops being valid for the ground layer, the path is dropped, the
layer is recomputed, and the wall is above — so the unit is placed on top of it. The other callers
are `0x0066CD6F` (the same module), `0x00663F04`, and `0x00793792` (the flight-path stepper in the
`PhysicsBehavior` translation unit, which advances a precomputed `Coord3D` array at `[ebx+0x10]`).

Cell size is the tolerance that matters in practice: one cell is 10 world units, and the stamp
covers any cell with a corner inside the `WallBoundsMesh`. A `IsengardBatteringRam` is
`Geometry = CYLINDER` / `GeometryMajorRadius = 20`, `KindOf = ... CAN_ATTACK_WALLS`, on
`BatteringRamLocomotor` (`Surfaces = GROUND`, no `ScalesWalls`) — so it is a wide object driven
deliberately into a wall, and its *centre* only has to reach the first stamped cell.

## 6. Confirmed live, 2026-09-21

Read with a `sage_live` probe against a **playing replay** (read-only; `Object+0x428` sampled every
tick for every object in the table, alongside the wall-layer arrays of §1). 1165 samples, 950
objects.

**The wall-layer table was exactly as §1 describes it.** Three layers in use, `Pathfinder+0x1BEB8`
= 3, entries at `+0x11`:

```
layer  17  height   180.33
layer  18  height   218.99
layer  19  height   228.97
```

**§6.1 — the siege unit lands on a wall-height layer.** `ArnorTrebuchet` took layer `18`, then
`19`, and its position z became the layer's height to the centimetre:

```
f5297 ArnorTrebuchet #3505 -> layer 18   pos=(3195,2766,219.0)
f5319 ArnorTrebuchet #4063 -> layer 19   pos=(3088,2778,229.0)
```

That is this bug, not the bridge loop. §3 is right about the mechanism.

**The promotion really does ignore what the object is.** `IronHillsRockyOutcropping03` — immobile
map scenery — was promoted to layer `17` while its own z stayed at `-8.9`. Nothing about a rock
asked to be on a wall.

**§6.3 came back dirty, and it is the finding that matters.** `LothlorienMirkwoodFighter` and its
horde were repeatedly on layer `17` at z `180.3`, which is layer 17's height:

```
f5245 LothlorienMirkwoodFighterHorde #4065 -> layer 17  pos=(2125,3355,180.3)
f5341 LothlorienMirkwoodFighter      #4067 -> layer 17  pos=(1745,3433,180.3)
```

So infantry are **not** confined to the `2`..`15` loop, and §3's "this split is what makes the two
separable" does not hold: the branch at `0x006F07CF` is not a siege-only path. A patch that removes
or neuters that branch changes where infantry stand too.

**Layer `16` is real and was not in §1's number space.** Objects on a wall alternated between `16`
and the wall-height layer — the trebuchet finished on `16` at z `229.0`, the fighters bounced
`17` ⇄ `16` while moving along the wall. `16` is outside `isWallLayer` (`0x11`..`0x40`) and outside
the slot range, which the binary reconfirms twice: `getCell` tests `cmp eax,1 / jle` and
`cmp eax,0xf / jg` (`0x005E2EC1`, `0x005E2EC6`), and the loop in §3 ends on
`cmp edi,0xf / jle` (`0x006F085E`). Only `getLayerHeight` knows it, at `0x006F0B58`. Both `16` and
the wall-height layers reach an object through the *same* `setLayer` in §3's first branch, because
that branch applies whatever layer the cell names — so `16` is most likely the walkable wall top
stamped into its own cells, and legitimate wall-walking goes through the branch after all.

**Still open.**

1. **Were those fighters legitimately on the wall, or glitched onto it the same way?** The probe
   cannot tell: it reads the layer, not the intent. This decides whether §6.3 means "infantry use
   this branch legitimately" or "infantry suffer the same bug". Watching one garrison a wall via
   the flag in a live skirmish settles it.
2. ~~What `16` is~~ — **answered, statically: `16` is the ramp layer.** `getLayerHeight`'s arm at
   `0x006F0B58` honours a cell stamped `16` only when `0x006E89EE` says so, and that predicate
   walks the **ramp record list at `Pathfinder+0x5C`** — the list built from `RampMesh1` /
   `RampMesh2` in [`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md) §3 — returning true
   if any record contains the position (`0x0067F2D0`). So a unit on a ramp gets a
   *position-dependent* height and rides up; a unit on a wall-height layer gets the **flat**
   constant `Pathfinder+0x1BE78[layer]`. What remains open is whether a unit standing on a wall
   *top* is represented by a slot layer, by `16`, or only by `17`..`64`: §6 never saw anything on
   `2`..`15`.
3. **`Pathfinder+0x1BF78 + layer*4` did not resolve to an object** in the live table for any of the
   three layers, so §1's "the object that defined it" is unconfirmed.

## 6b. The cell stamps, and why the layer gate is dead (2026-09-21)

A second read, of the grid rather than the objects: `Pathfinder+0x10` is an array of **column**
pointers indexed by cellX, a cell is `column[cellX] + cellY*0x10`, bounds at `+0x14`/`+0x18`
(min) and `+0x1C`/`+0x20` (max), one cell to 10 world units (`0x005E2EDD`, `0x006E8DD5`).

**The whole map, 400x400 cells:**

```
layer   1    156151 cells   ground
layer  16      1232 cells   RAMP
layer  17      2265 cells   wall-height bounds
layer  18       352 cells   wall-height bounds
```

**No cell anywhere is stamped `2`..`15`.** The slot layers are not how this map represents a wall
at all, so §1's "the raised walkable wall surfaces" are not what a standing object holds.

**A catapult driven up a ramp and back down, live:**

```
f913 ImladrisCatapult #852: layer  1 -> 16 [RAMP]          z=207.3
f925 ImladrisCatapult #852: layer 16 -> 17 [wall-height]   z=255.4
f962 ImladrisCatapult #852: layer 17 -> 16 [RAMP]          z=245.4
```

and the cells around it, the ramp reading as a tongue of `R` running into a field of `A` (=17):

```
   at (794,1004), the moment it steps off the ramp onto the wall top
     ....AAAAAAAAAAA
     ..AAAAAAAAAAA..
     AAAAAAAAAAAA...
     AAAAAAAAAARR... <-- the object is here
     AAAAAAAARRRRRR.
     AAAAARRRRRRRRRR
```

**So layer `17` is where a unit legitimately stands after climbing a ramp, and it is also where
the bug puts one.** A gate on `isWallLayer` would stop siege standing on a wall it climbed
properly — worse than the bug. The layer is not the discriminator.

**What is left is the size of the move.** The promotion fires on `h > z + 10`, and the two cases
differ in how far above the object that surface is: a unit stepping off a ramp onto the walkway is
already level with it, while a unit shoved into a wall's bounds at ground level is a whole wall
below. The quantity a patch can test is `wallHeight[layer] - obj->z` at the moment of the call,
and it is cheap at the hook site: the object is in `esi`, its z at `Object+0x40`, and a wall
layer's surface is the flat constant `Pathfinder+0x1BE78[layer]` — no call, no FPU state to
recover. **Measuring it on both cases is the open task**; §7's gate is written against it.

## 7. Scoping the fix

**There is no INI fix on the promoted unit.** §4 is the reason and §6 confirms it: the promotion
reads nothing the unit's data can set, and it promoted a piece of immobile scenery. `ScalesWalls =
No` is already the ram's state and changes nothing. What INI can do is indirect — keep the unit's
centre out of the stamped cells (a larger `GeometryMajorRadius`, a stand-off range on the wall/gate
attack) or shrink the stamp (a tighter `WallBoundsMesh` on the wall's `Draw`, an art change) — and
none of it is a guarantee, because it only makes the clipping rarer.

**The hook site is unchanged; the gate is not.** One hook at `0x006F07DD` — the 5-byte
`call 0x0068BB9D` in the `h > z + 10` branch — gating that one `setLayer`. §6.3 rules out gating it
on the *branch* (infantry come through it too).

**A `KindOf` gate is the wrong shape, because machines belong on walls.** A castle with a ramp
lets siege climb it legitimately, so blocking the promotion for `MACHINE` or `SIEGEENGINE` would
trade this bug for a worse one. (`WALK_ON_TOP_OF_WALL` was never a candidate anyway: in the shipped
data it is a flag on the *wall* — "you may be walked on" — carried by `STRUCTURE IMMOBILE` blocks
and used in object filters, not a unit-side permission.)

**Gating on the target layer is also wrong**, and §6b is why: a catapult that climbs a ramp ends
up on layer `17`, the same layer the bug promotes to. Blocking `17`..`64` would stop siege standing
on a wall it climbed properly.

**Gate on the distance instead.** The discriminator is not where the object is being put but how
far it is being moved to get there:

| | `wallHeight[layer] - obj->z` at the call | what it is |
|---|---|---|
| steps off a ramp onto the walkway | small — it is already level | the legitimate climb |
| shoved into a wall's bounds at ground level | the full height of the wall | the teleport |

So the gate narrows the existing `h > z + 10` into a band: promote when the surface is a step above
the object, skip when it is a storey above. Both operands are to hand at `0x006F07DD` — `esi` is
the object, z is `Object+0x40`, and a wall layer's surface is the flat constant
`Pathfinder+0x1BE78[layer]`, so the test is a load and a compare with no call and no FPU state to
reconstruct. **The threshold is a measurement, not a guess**, and §6b names the run that takes it.

**The measurement, taken 2026-09-21.** Two runs, sampling every layer change:

| transition | `surface - z` beforehand |
|---|---|
| catapult, ramp onto the wall top (3 of 3) | `+0.0` |
| infantry, ramp onto the wall top | `+0.0` .. `+3.4` |
| **trebuchet, ground onto a wall (the bug)** | **`+53.4`** |
| infantry, ground onto a wall (the bug) | `+14.7` |

Every legitimate arrival is already level with the surface it moves to, so it **fails the
routine's own `h > z + 10` test and never reaches this call**. The promotion in this arm is, in
every sample taken, the bug — which is what makes gating it safe for the ramp route: a climbing
catapult is not in this code path to begin with.

**So the gate is `MACHINE`, and the band is not needed.** A threshold cannot discriminate here
anyway: the engine's own `+10` floor means everything reaching the call is already a jump, and the
measured glitches run from `+10.0` to `+53.4` with no legitimate arrival among them to separate
from. `MACHINE` (`KindOf` index 11, bit `0x08` of byte `+0x1` — carried by every siege engine in
the shipped data and by no infantry) covers the reported symptom while leaving alone the arrivals
this session never observed: a wall-scaling unit (`ScaleWallSpecialAbilityUpdate`), a siege ladder,
a siege tower. Each of those moves a unit from the ground to a wall top by design and would show
the same large jump, and none of them is a `MACHINE`.

**What the patch does not fix, and what would settle it.** Infantry promoted from the ground
(`+14.7` above) are still promoted. Widening the gate means knowing whether the ladder/tower/
scaling-unit mechanisms actually use this arm; the run that answers it is watching `Object+0x428`
on a unit riding a siege ladder and on a wall-scaling hero. If none of them passes through
`0x006F07DD`, the gate can drop the `KindOf` test entirely and refuse every wall-height promotion
in this arm.

**Still to confirm in game.** The patch is statically verified only. The test is the one that
motivated the gate: drive a siege engine up a castle ramp with the patch applied and check it still
reaches the walkway, then walk one along the outside of a wall and check it no longer pops up.
