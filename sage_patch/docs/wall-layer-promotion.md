# An object standing inside a wall's footprint is teleported onto the wall

RotWK 2.01 `game.dat`, ImageBase `0x400000`. **Static recovery only — nothing here has been
confirmed against a running game.** §6 is the test that would.

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

## 6. Before fixing: confirm it is actually this

1. **Read `Object+0x428` on the ram** as it pops up (`sage_live`, or Cheat Engine). A value in
   `17..64` is this bug. A value in `2..15` is the bridge/raised-surface loop instead, and §3's
   split is wrong.
2. **Check `Pathfinder+0x1BEB8`** against the number of distinct wall heights on the map, and
   `+0x1BF78 + layer*4` against the wall the ram landed on.
3. **Watch a garrisoning infantry unit** reach a wall top and read its `+0x428` too. If infantry
   also land on `17..64`, then the branch at `0x006F07CF` is the *only* way onto a wall and §7
   cannot simply remove it.

## 7. Scoping the fix

**There is no INI fix on the ram.** §4 is the reason: the promotion reads nothing the ram's data
can set. `ScalesWalls = No` is already the ram's state and changes nothing. What INI can do is
indirect — keep the ram's centre out of the stamped cells (a larger `GeometryMajorRadius` on the
ram, a stand-off range on the wall/gate attack) or shrink the stamp (a tighter `WallBoundsMesh` on
the wall's `Draw`, an art change) — and none of it is a guarantee, because it only makes the
clipping rarer.

**The patch is small if §6.3 comes back clean.** One hook at `0x006F07DD` — the 5-byte
`call 0x0068BB9D` in the `h > z + 10` branch — gating that one `setLayer` on the object being
allowed on a wall. The gate to test is the open question, and it is a data question, not a code
one: `Object::canScaleWalls` (`0x0068B331`) already exists and would make `ScalesWalls` mean what
modders expect, but in the shipped locomotors `ScalesWalls = Yes` appears only on
`HeroHumanScalingLocomotor`, `ShelobWallScalingLocomotor`, `ShelobHillScalingLocomotor`,
`GollumWallScalingLocomotor`, `TestWallScalingHordeLocomotor` and `WallScalingMeleeHordeLocomotor`
— units that climb wall *faces*, not the infantry that garrison a wall top. A `KindOf` test
(`CAN_CLIMB_WALLS` bit 184, or excluding `MACHINE`) may fit the existing data better. Decide it
after §6.3, not before.
