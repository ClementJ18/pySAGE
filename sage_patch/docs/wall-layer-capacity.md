# How many walls the pathfinder can hold

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Read statically from a clean `game_backup.dat`
on 2026-09-24; the pointer chain and table layout were confirmed against a running game the same day
(`../scripts/wall_capacity_probe.py`). **The overflow itself has not been reproduced live yet** (§4).
Background: [`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md) §3 (the registration) and
[`wall-layer-promotion.md`](wall-layer-promotion.md) §1 (the layer number space).

**The finding in one sentence.** A wall registers into two fixed-size, match-long tables: a
`RaisedWallMesh` takes one of the 14 raised-surface slots, and a `WallBoundsMesh` takes one of the
wall-height layers. Neither table gives an entry back when the wall dies. Slot 15 is never
classified, so it is dead on arrival, and wall-height layers past the 47th wrap in the 6-bit cell
stamp onto layer numbers that mean something else.

## 1. Raised-surface slots: 13 usable, never returned

`Pathfinder+0x60` holds 16 slots of `0x40`. Walls scan slots 2..15 (`push 2; pop edi` at
`0x00935FFE`, `cmp edi,0xf / jle` at `0x0093605A`), and bridges take slots from the same table.

**Two walls share a slot only if they touch.** The share test at `0x00936012`..`0x00936054` needs
all of these:
- the slot is in use (`0x00768326`)
- `0x00768286` finds a member whose sub-object bounding box lies within 10 units of the new one
- the slot's integer height (`slot+0x3C`) is within `3.5` (`0x00C7FADC`) of the new one

If the walls don't touch, each separate group needs its own slot, even at the same height.

**When no slot is free, the wall silently gets no surface.** The claim loop at `0x0093605F` finds
nothing and jumps to `0x009360EB`, which is the ramp code. The raised surface is not registered, and
there is no error or debug string.

**Slot 15 is claimable but never classified.** Both loops that build and classify slot cells run 15
iterations from slot 0, so they cover slots 0..14:

```
00935c04  push 0xf / lea esi,[edi+0x60] / pop ebx      ; classify all slots (0x768832 / 0x768AE9)
006ea360  push 0xf / lea esi,[ebx+0x60] / pop edi      ; map-load grid build (0x7684F8)
```

A wall that claims slot 15 at runtime gets a blank grid at `0x009360DF`, and no pass ever marks
its cells. In `wall-layer-promotion.md` §3, the slot loop requires `cell.layer == i`, so nothing
can stand on that surface. Every other slot consumer covers 15: `getCell` (`0x005E2EC6`), the
promotion loop (`0x006F085E`), the zone pass (`0x0093A5BB`) and `Pathfinder::reset`.

**Nothing releases a slot during a match** (`raised-wall-mesh-removal.md` §4). This means the budget
counts every wall group that has *ever* stood, not just the ones standing now. Bridges on the map
come out of the same budget.

## 2. Wall-height layers: the table holds 64, the cell stamp holds 47

`Pathfinder+0x1BEB8` is the count, and `+0x1BEBC` holds the heights (the layer is `index + 17`).
Registration (`0x009362B3`..`0x00936484`) shares the nearest existing height within `3.5`.
Otherwise it appends, with a cap at `0x0093644B`:

```
00936445  mov eax,[esi+0x1beb8]
0093644b  cmp eax, 0x40        ; room for 64 -> layers 17..80
0093644e  jge 0x93648c         ; full: one debug warning, then share the nearest layer
```

The cell only has room for 6 bits: `PathfindCell::setLayer` (`0x007681BB`) masks with `0x3F0`, and
every reader does `shr 4; and 0x3f` (for example `0x006EAA31`, `0x0093510A`). So the 48th
distinct height and beyond get stamped as the wrong layer:

| real layer | stamped as | which is |
|---|---|---|
| 64 | 0 | `LAYER_INVALID` |
| 65 | 1 | ground |
| 66..79 | 2..15 | somebody's raised-surface slot or bridge |
| 80 | 16 | the ramp layer |

`isWallLayer` (`0x006E82B3`, `0x11`..`0x40`) and the pick at `0x006EAA3A` (compares against
`i + 0x11` unmasked) never match those cells again.

The count only goes down in `Pathfinder::reset` (`0x006F5B41`). A height is "distinct" when it is
more than 3.5 from every existing one, and wall heights are absolute world z. So on a hilly map,
free-built walls use up layers by terrain elevation.

**When the table is full (count 64)**, the overflow arm uses `ebx`, the nearest layer. At
`0x009364EE` it *raises* that layer's height to the new wall's if the new one is higher. That moves
the walkable surface of every wall already on that layer.

## 3. Scoping the patch

All of this is **simulation state**. As with `wall-mesh-release`, every peer must run the same
binary, and replays will not cross.

| # | change | sites | size | notes |
|---|---|---|---|---|
| a | classify slot 15 | `0x00935C05`, `0x006EA361`: `0x0F` → `0x10` | 2 bytes | a stock bug fix; the table is 16 long, and `reset` already loops 16 |
| b | release slots when a wall dies | – | – | already `wall-mesh-release` leg 1, but it is **not in the installed `C:\RotWK\game.dat`** (`sagepatch` lists 7 patches, not this one) |
| c | share slots by height alone | `0x00936030` `je` → 2×`nop` | 2 bytes | makes the capacity 13 distinct *heights* instead of 13 disconnected *groups*; see below |
| d | cap wall-height layers at 47 | `0x0093644D` imm `0x40` → `0x2F` | 1 byte | over-limit walls share the nearest layer instead of wrapping; together with (e) |
| e | overflow must not move a shared layer | hook `0x009364EE`, skip the height raise when coming from `0x0093648C` | small cave | stops (d) from moving other walls' surfaces |

**(c) is the one that trades something away.** A shared slot's grid is the union bounding box of
its members (`0x007684F8`). The classifier `0x00768832` tests every cell corner against every member
mesh, and all slots are reclassified whenever a ramp is added (`+0x1BEB4` → `0x006E85B0` →
`0x00935BFF`). So cost grows with the number of cells times the number of members, and could cause
a visible hitch on a big map full of walls. The slot's height is also taken from its first member
(`slot+0x3C`), so the 3.5 tolerance still applies. (c) is compatible with `wall-mesh-release`,
which already unlinks one member from a shared list.

**Wall-height layers are not released (the gap after d/e).** A per-layer refcount would let a layer
be reused, but its cells still carry the stamp until the wall's unmark loop clears them. Leave that
out unless (d) turns out to be hit in real games.

## 4. What is still unconfirmed

Every cap here only breaks walls *past* the limit. None of them, as read, makes walls that already
work stop working. The exceptions are the overflow height raise in §2 (one layer) and the ground
stamp from layer 65 (only the new wall's own cells). A report of "they all stop at once" means one of
two things: the report is really "every *new* one stops", or there is a mechanism this read has not
found.

**The test that settles it:**
1. Build raised walls in a running game until they stop working.
2. Run `../scripts/wall_capacity_probe.py`.
   - Slots 2..15 all taken → §1.
   - Layers ≥ 47 → §2.
   - Neither → look elsewhere.

When the chain was confirmed (a match with no raised walls), the probe read 2 wall-height layers,
all 16 slots free, and 8 ramp records.

## 5. Addresses

| address | what |
|---|---|
| `0x00935FFE`..`0x0093605D` | slot share scan (2..15) |
| `0x00936030` | the adjacency `je`: (c) |
| `0x0093605F`..`0x0093607E` | slot claim scan; full → `0x009360EB` with no surface |
| `0x00768286` | "a member is within 10 units" bounding-box test |
| `0x00935BFF` | classify all slots; `push 0xf` at `0x00935C04`: (a) |
| `0x006EA360` | map-load slot grid build; `push 0xf`: (a) |
| `0x006E85B0` | reclassify when `+0x1BEB4`/`+0x1BEB5` are set, then run zones (`0x0093A530`) |
| `0x0093644B` | wall-height layer cap `0x40`: (d) |
| `0x0093648C` | table-full arm (debug warning once, flag `0x00DEA458`) |
| `0x009364EE` | nearest-layer height raise: (e) |
| `0x007681BB` | `PathfindCell::setLayer`, 6-bit field `0x3F0` |
