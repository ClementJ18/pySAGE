# Fog of war — how the engine hides things, and how to read it

Recovered against RotWK 2.01 + Edain, `game.dat`, 2026-08-05. Static analysis plus read-only
`ReadProcessMemory` against a live skirmish; no injection, no writes.

**Verdict up front.** Per-player visibility is readable, and the filter it enables is shipped:
`sage_live.api.shroud` holds the model, `sage_live.backends.shroud` reads it, and
`Observation.under_fog` applies it. This closes the item [`live-api.md`](../../docs/live-api.md)
§5 records as "the remaining work", and the last bullet of
[`live-object-model.md`](live-object-model.md) §5.

It does **not** close everything the fog does. See §6.

## 1. Two corrections to the address table first

`ThePartitionManager` was recorded at `0x00DE4358`. That address is **`TheShroudManager`**.

The registration block builds each subsystem, stores it, and *then* pushes its name — so
"the object built immediately after the name string is pushed" reads one slot late. The
decisive instruction is the `setName` call site, which reloads the global it is naming:

```
0x0062CEB3  mov  [0x00DE4354], eax      ; store the object
0x0062CECB  push 0x00BFDC08             ; "ThePartitionManager"
0x0062CED5  mov  ecx, [0x00DE4354]      ; <- names the object stored above
0x0062CEDB  call 0x0046EC7F             ; setName
```

Both are now confirmed **live** rather than statically, which is stronger than the disassembly:
each subsystem carries its own name as an `AsciiString` at `+0x08`, so reading it back is a
direct answer.

| address | subsystem |
|---|---|
| `0x00DE4354` | `ThePartitionManager` |
| `0x00DE4358` | **`TheShroudManager`** |
| `0x00DE435C` | `TheTaintManager` |
| `0x00DE4360` | `TheCollisionManager` |

The "109 code references" that [`live-object-model.md`](live-object-model.md) §5 attributed to
`ThePartitionManager` are `TheShroudManager`'s. The partition manager has 285.

**The second correction is that the 20-byte object is not a mistake, it is a facade.** The old
note flagged `push 0x14` as implausibly small for a manager and suggested confirming it live.
It is exactly right, and it is why: every method is a two-instruction thunk.

```
0x00B4D9A0  mov  ecx, [ecx + 0x10]
0x00B4D9A3  jmp  0x00B4FB20
```

So the real object is the one at `+0x10` — `0x70` bytes, allocated by the constructor at
`0x00B4DA80` — and **every offset below is relative to that**, not to the global.

## 2. The grid

`TheShroudManager`'s implementation owns a flat, row-major grid of cells.

| offset | field | value on the measured map |
|---|---|---|
| `+0x04` | origin X | `0.0` |
| `+0x08` | origin Y | `0.0` |
| `+0x1C` | cell size | `40.0` world units |
| `+0x20` | **1 / cell size** | `0.025` |
| `+0x24` | cells along X | `104` |
| `+0x28` | cells along Y | `104` |
| `+0x2C` | cell array | stride `0xA8` |
| `+0x64` | the seat the grid is currently being evaluated for | |
| `+0x68` | fog of war enabled | one byte |

`104 × 40 = 4160`, against a map extent of `4130` — the grid covers the map and rounds up, which
is the first cheap check that these are the right two fields.

**Multiply by `+0x20`, do not divide by `+0x1C`.** `0x00B4E390` is the world→cell conversion and
it multiplies by the stored reciprocal; the two disagree in the last bit, and a filter that
disagrees with the engine at a cell boundary is a filter that reports the wrong answer for one
unit standing exactly on it.

```
cx = floor((x - origin_x) * inv_cell_size)
cy = floor((y - origin_y) * inv_cell_size)
if cx or cy is out of range: no cell
cell = cells + (cells_x * cy + cx) * 0xA8
```

## 3. The cell

One cell is `0xA8` = 168 bytes: a 4-byte head, then **20 eight-byte per-player records**
(`4 + 20 * 8 = 164`, padded to 168). Twenty is `MAX_PLAYER_COUNT`, and `0x00B4FB20` rejects a
seat outside `0 <= p < 0x14` before touching the grid — the same bound
[`max-player-count.md`](max-player-count.md) records.

A record is four `u16`s. Only the first is visibility:

| record offset | field |
|---|---|
| `+0x00` | **shroud level** — how many of that player's revealers currently cover this cell |
| `+0x02`, `+0x04`, `+0x06` | the cell's value maps, selected by index 0..2 at `0x00B4FE40` |

The other three are `PartitionCell`'s `m_threatValue` / `m_cashValue` neighbours: measured live,
one of them took only multiples of 250 and another ran to five figures. That is corroboration
that this grid *is* `PartitionCell`, which is what
[`max-player-count.md`](max-player-count.md) predicted holds `ShroudLevel m_shroudLevel[N]`.

## 4. The lookup

`0x00B4FB20`, reached through the thunk at `0x00B4D9A0`, taking `(playerIndex, Coord3D *)`:

```
if playerIndex < 0 or >= 20:       return 2
cell = worldToCell(pos.x, pos.y)
if not cell:                       return 2
level = u16[cell + 4 + playerIndex * 8]
if level == 0xFFFF:                return 2
return 1 if level == 0 else 0
```

`0x00B4FAB0` is the same thing taking cell coordinates directly, plus one extra step: when the
result is `1` and the byte at `impl+0x68` is zero, it becomes `0`. That is the fog-of-war switch
— with fog off, "not visible" collapses to "visible".

So the three returns are **0 = visible now, 1 = not visible, 2 = no shroud state**.

**The level is a reference count, not a flag.** Any positive value is visible; live cells read 1
through 9 as units bunched up.

## 5. The measurement

One two-player skirmish (Men vs an Isengard AI), read at several points in a live match.

| seen by | own objects visible | opponent's objects visible |
|---|---|---|
| me (seat 3) | 69 of 70 | **0 of 50** |
| the AI (seat 4) | 49 of 50 | **0 of 70** |

The mirror is what makes this more than a plausible field: a wrong offset does not produce two
sides that each see all of their own army and none of the other's. Drawn as ASCII the grid is a
single filled blob around each base with every enemy unit outside it. Later in the same match,
with the AI attacking, 28 of their 170 objects were visible — the ones standing in my army's
vision — which is the behaviour a flag could not produce either.

The one own object that is not visible to its owner is expected: a garrisoned unit reports its
holder's position, and a unit on the grid edge rounds outward. `under_fog(keep_own=True)` covers
it, and that costs nothing in honesty — you can always see your own army.

## 6. What this does *not* give: explored versus never explored

`0xFFFF` is `-1` read signed, which is the obvious "never explored" sentinel and would make the
triple the classic SAGE `CLEAR / FOGGED / SHROUDED`. **It is not that**, and the measurement is
unambiguous. Across all twenty slots of a live match:

| seats | `0xFFFF` cells | positive cells | zero cells |
|---|---|---|---|
| the two playing seats (3, 4) | **0** | ~1000 each | the rest |
| the fourteen unused slots | 10806 of 10816 | 0 | 10 |
| the replay observer (5) | 0 | **all 10816** | 0 |

So `0xFFFF` means "this seat has no shroud state", not "this cell was never seen" — which is why
the shipped enum names it `UNTRACKED` rather than `SHROUDED`. For a playing seat the level is
only ever zero or a positive count.

**The consequence is real and worth stating plainly: a cell you explored and walked away from is
byte-for-byte identical to one you have never reached.** A human player still sees a scouted
enemy building drawn in the greyed-out fog; a consumer of this grid does not.

The engine keeps that distinction **per object**, not per cell — `PartitionData` carries
`Bool m_everSeenByPlayer[N]` alongside `ObjectShroudStatus m_shroudedness[N]`
([`max-player-count.md`](max-player-count.md)). That structure is still not located, and the
hunt for it recorded in [`live-object-model.md`](live-object-model.md) §5 remains open. What is
new is that it is no longer on the critical path: the per-cell grid answers "can this seat see
that *right now*", which is the whole of hiding units, and remembering what was seen is
something a consumer can do honestly for itself.

`Observation.under_fog` therefore hides what cannot be seen now and invents no memory. A policy
that wants one should accumulate it across frames — it is the policy's memory, and making that
explicit is better than pretending the engine supplied it.

## 7. Method notes

**A back-pointer beats a shape.** The earlier hunt for `PartitionData` looked for the shroud
array's *shape* — a 20-wide per-player array mirroring between two sides — and found only
`Team+0x1A8`. Looking for the structure's *identity* instead (which block points back at the
`Object` it belongs to) is one unambiguous test that does not care where the field sits inside,
and it ran over 60 objects in a single pass. It found the `Drawable` at `Object+0x84` and the
module pointers at `+0x234`..`+0x24C`, and it ruled out `PartitionData` being one pointer from
the object at all — which is a real result, and is what sent this at the manager instead.

**Read the facade before believing an offset is absent.** Every field in this document is behind
`[global] + 0x10`. A scan of the 20-byte object itself finds nothing but a vtable and a name, and
"the manager holds no grid" is exactly the wrong conclusion to draw from that.

**A thunk table is a free API listing.** `0x00B4D900`..`0x00B4D9E0` is fifteen consecutive
`mov ecx,[ecx+0x10]; jmp X` stubs — the class's whole public surface, in declaration order, with
no need to find call sites. Two of them turned out to be the two lookups above.

**The oracle was a live match, and it had to be.** The static reading gives 0/1/2 with no names
attached; only the mirror measurement in §5 says which is which, and only the twenty-slot census
in §6 rules out the reading that the enum names would have suggested.
