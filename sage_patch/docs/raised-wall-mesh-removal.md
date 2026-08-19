# `RaisedWallMesh` geometry survives the wall that owned it

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Static recovery only — **nothing here has been
confirmed against a running game yet**; §7 is the test that would. Re-read end to end on
2026-08-19 against `engine/game.dat.backup`, which corrected four things in §3 and §4 and located
the release routine §7b had recorded as missing; the corrections are marked **(2026-08-19)** where
they land. Shipped as
[`../patches/wall_mesh_release.py`](../patches/wall_mesh_release.py), which implements §7b.

**The finding in one sentence.** A wall registers three separate things with the pathfinder and
gives back **none** of them when it dies: the walkable surface leaks because nothing removes it at
all, and the ramps and the bounds cells leak because their removal re-asks the drawable for a mesh
that the dying wall's model no longer contains.

**Two legs, and only one of them is a hypothesis (2026-08-19).** The original framing above — "the
removal is the addition run again against whatever model the drawable is showing now" — is right
about the ramps and the wall bounds, and those do depend on the unmeasured claim that the model has
already changed by teardown time (§4). It does **not** describe the walkable surface, which is the
leg the `RaisedWallMesh` keyword names: `Pathfinder::claimWallLayer` (`0x00768246`) and the
list push beside it (`0x00768276`) have **exactly one caller each, both on the add path**, so
there is no removal code to fail. That leg leaks whatever the model does, and it needs no
triage in §6 to believe.

## 1. Where the field lives

`RaisedWallMesh` is a plain `AsciiString` on the `W3DScriptedModelDraw` module data. Its field-parse
table is at `0x00BE1320`..`0x00BE16B0` (58 rows of `0x10`, NULL-terminated, one reference at
`0x004C8940`), and five adjacent rows are the wall block:

| keyword | `ModuleData` offset | parser |
|---|---|---|
| `WallBoundsMesh` | `+0x10C` | `0x0042EE5E` (generic `AsciiString`) |
| **`RaisedWallMesh`** | **`+0x110`** | `0x0042EE5E` |
| `RampMesh1` | `+0x114` | `0x0042EE5E` |
| `RampMesh2` | `+0x118` | `0x0042EE5E` |
| `EmbedPortal` | `+0x11C` | `0x004C30BD` (custom) |

The module data is constructed at `0x004C85E9` (the four strings zeroed at
`0x004C86A8`/`AE`/`B4`/`BA`) and released at `0x004C830D`..`0x004C8349`.

> **A scan trap worth recording.** Searching `.text` for memory operands with displacement `0x110`
> finds *none* of the readers. Every reader takes the module data pointer into a register and does
> `add esi, 0x110` — an **immediate**, not a displacement — because it then passes `&theString` to
> `AsciiString::operator=`. A displacement-only sweep concludes the field is write-only, which is
> wrong. Scan for `add reg, imm32` as well.

## 2. The query API: `ObjectDrawInterface`

`W3DScriptedModelDraw`'s constructor (`0x004C04A3`) plants three vtables: the module's own at
`this+0` (`0x00BDFFE8`), and two interface sub-objects at `this+0xC` (`0x00BE3B78`) and `this+0x10`.
`getObjectDrawInterface()` is vtable slot `+0xA8` (`0x004C9323`) and simply returns `this + 0xC`, so
inside an interface method `[esi-0xC]` is the module and **`[esi-8]` is the `ModuleData *`**.

Seven slots on `0x00BE3B78` answer wall questions. Each one does the same three steps: fetch the
module's current render object (`module->vt[0xC4]`), resolve a mesh **name**, then call
`renderObj->vt[0x80](name, 0)` — `Get_Sub_Object_By_Name`. **If the sub-object is not in the model,
the method returns false/NULL.**

| iface slot | impl | name comes from | `Drawable` wrapper |
|---|---|---|---|
| `+0x94` | `0x004BA4FF` | `ModuleData+0x110` (`0x004BA538`) | `0x006728A1` |
| `+0x98` | `0x004BA5BB` | `module+0x260` if non-empty, else `ModuleData+0x10C` (`0x004BA616`) | `0x006728D7` |
| `+0x9C` | `0x004BA693` | `ModuleData+0x110` (`0x004BA6CC`) | `0x0067290D` |
| `+0xA0` | `0x004B7A59` | `module+0x260` if non-empty, else `ModuleData+0x10C` (`0x004B7AA0`) | `0x00672943` |
| `+0xA4` | `0x004B7B07` | `ModuleData+0x110` (`0x004B7B37`) | `0x00672979` |
| `+0xA8` | `0x004BB76A` | `module+0x264` if non-empty, else `ModuleData+0x114` | `0x006729A3` |
| `+0xAC` | `0x004BB7EB` | `module+0x268` if non-empty, else `ModuleData+0x118` | `0x006729E9` |

The `Drawable` wrappers all walk the draw-module array at **`Drawable+0x14C`** and return the first
module that answers.

Two things fall out of that table:

- **`WallBoundsMesh`, `RampMesh1` and `RampMesh2` have a runtime override** on the module instance
  (`+0x260`, `+0x264`, `+0x268`), written through module vtable slots `+0xD4` (`0x004B5809`,
  `add ecx,0x260; jmp AsciiString::operator=`) and `+0xD8` (`0x004B5814`,
  `lea ecx,[ecx+eax*4+0x264]`). Slot `+0xDC` (`0x004B582B`) is the "is the bounds override set"
  predicate; `Drawable::hasWallBoundsMesh` at `0x00672F44` ORs it across the module list.
- **`RaisedWallMesh` has no override.** All three of its readers go straight to `ModuleData+0x110`.
  Nothing can change it at runtime.

The only writer of the overrides is `GeometryUpgrade::upgradeImplementation` (`0x008BAD8B`), which
reads its own `ModuleData+0x150`/`+0x154`/`+0x158`, pushes them into every draw module through
`+0xD4`/`+0xD8`, then re-runs `WallUpgradeUpdate` (found by name at `0x008AE8F0`, module-name
literal `0x00C0B0C0`) and re-registers the object with the pathfinder (`0x0068B244`).

## 3. The consumer is the pathfinder, not the renderer

`TheAI = 0x00DE4B40` (registered at `0x0063BE74`..`0x0063BE87`), and `TheAI+0x10` is the
`Pathfinder`. Two thin wrappers front the same worker `0x00936B7D(Object*, a, b, c)`:

```
0x006E85E9  push 0; push 0; push 1; push obj; call 0x936B7D   ; add to pathfind map
0x006E85FB  push 0; push 0; push 0; push obj; call 0x936B7D   ; remove from pathfind map
```

`0x00936B7D` decides whether the object is a walkable wall from `ThingTemplate`'s `KindOf` mask
(base `tmpl+0x108`):

```
0x00936BCE  mov ecx,[eax+0x10c]          ; kindof bits 32..63
0x00936BD7  shr ebx,0x1c / and bl,1      ; bit 60  = WALK_ON_TOP_OF_WALL   -> "is a walkable wall"
0x00936BF3  test ecx,0x20000000          ; bit 61  = DEFENSIVE_WALL
0x00936C6F  test byte [eax+0x11a],0x40   ; bit 150 = WALL_UPGRADE
0x00936C81  call 0x672F44                ;   ... and for those, require hasWallBoundsMesh()
```

and then, on **both** the add and the remove path, tail-calls the wall handler:

```
0x009378A3  call 0x935FAA                ; Pathfinder::<wall geometry>(Object*, Bool adding)
```

`0x00935FAA` is where `RaisedWallMesh` becomes pathfinding data. Its shape:

**(2026-08-19)** The table is at **`Pathfinder+0x60`**, sixteen slots of `0x40` — not `+0xE0`,
which is slot **2**, where the *wall* scan starts (`push 2; pop edi` at `0x00935FFE`, running to
index 15 inclusive at `0x0093605A`). `Pathfinder::reset` proves the base and the count by looping
the release routine over exactly `[esi+0x60] .. +16*0x40` (`0x006F5B03`).

| | add (`adding != 0`) | remove (`adding == 0`) |
|---|---|---|
| raised surface | `Drawable::0x67290D` → iface `+0x9C` → **`RaisedWallMesh`**; claims a slot in the 16-entry table at `Pathfinder+0x60` (stride `0x40`, wall slots 2..15), storing the *`RenderObjClass *`* of the mesh (`0x00768276` / `0x00768246`) | **nothing at all** — no query, no release, no code |
| ramp 1 | `Drawable::0x6729A3` → iface `+0xA8`; `new(0xCC)`, built by `0x0067FFA6`, linked into the list at `Pathfinder+0x5C` | same query; `new(0xCC)`, built the same way, then `0x009356DF(record, 0)` **removes by value** and the temporary is deleted |
| ramp 2 | `Drawable::0x6729E9` → iface `+0xAC`; same | same |
| wall bounds | `Drawable::0x6728D7` → iface `+0x98`; **`test eax,eax; je 0x936B6C`** — a NULL answer returns from the function; otherwise the returned height is matched against the wall-layer height array at `Pathfinder+0x1BEBC` (count at `+0x1BEB8`) to pick the layer, and the cell rectangle is marked | same query, same early-out; the same rectangle is **un**marked |

**(2026-08-19) The wall-bounds row runs in both directions, and the two paths rejoin to reach it.**
`adding` is branched on at `0x00935FDD`, which separates the raised surface and the ramps, and the
two arms *rejoin* at `0x0093629C`; the bounds mesh is then queried once, for both. `adding` is read
a **second** time at `0x009365F9`, after the cell rectangle has been computed, and only there does
the mark/unmark choice happen — it is the last argument of `0x00935051`. So the NULL early-out at
`0x009362AD` is not a removal-only weakness: it abandons the function in either direction, and a
wall whose bounds mesh is missing at *add* time registers its ramps and never its cells.

**(2026-08-19) The slot holds a list, and the pathfinder owns what is in it.** `0x00768246` claims
an empty slot and `0x00768276` pushes onto it; the link is the **render object's own `+0x3C`**, and
the slot's `+0x38` is the head. Sharing is by height — the scan at `0x00936012` looks for a slot
already in use whose stored height matches this wall's, and appends to it (`0x00936080`) rather
than taking a new one, so one slot can carry many walls. What it carries is not the drawable's live
mesh: `0x004BA693` calls `Get_Sub_Object_By_Name`, passes the result through the virtual at
`+0x14`, and **releases the queried sub-object** (`dec [esi+4]`, destroy at zero) before returning
that derived object — which the pathfinder then destroys itself in `0x00768AA7`
(`(*vt[0])(0); operator delete`). Two consequences, both load-bearing for §7b: a pointer cached at
add time **stays valid**, because the pathfinder owns the referent; and the release frees **only
the head**, so a slot shared by several walls leaks its tail even when the slot is reset.

## 4. The failure, stated exactly

Nothing about the wall's footprint is *recorded* at add time in a form the remove path consults. The
remove path rebuilds two of the three queries and cancels whatever they return **now** — and does
not rebuild the third at all:

1. Each removal step is guarded by its own query succeeding —
   `0x009361CF` (ramp 1), `0x00936242` (ramp 2), `0x009362AD` (wall bounds, an early **return**).
2. Every one of those queries ends in `Get_Sub_Object_By_Name` against the render object the
   drawable is holding **at the moment of the call**.
3. The layer is not identified by object id or by anything the wall owns. It is found by matching a
   *height* that the removal has to recompute from the mesh.
4. **(2026-08-19)** The walkable surface is not on that list, because it has no removal step. The
   claim and the list push have one caller each and both are on the add path; nothing anywhere in
   the image unlinks a render object from a wall-layer slot. This leg does not depend on the
   model-change hypothesis below — it leaks on every wall removal, for any reason, whatever the
   drawable is showing.

So the moment the model stops containing `P2`/`P3`, the wall's ramp and cell data becomes
unreachable — not stale, *unreachable*. There is no code path left that can name it. `P1`'s slot
was already unreachable, from the moment it was claimed.

And a dying structure does exactly that. In Edain's own wall data
(`data/ini/object/goodfaction/structures/lothlorien/mirkwood_walls.ini`, `Mirkwood_Wall_02`):

```
RaisedWallMesh = P1                     ; RampMesh1 = P2, RampMesh2 = P3
DefaultModelConditionState  Model = ib_mrk_wll02
ModelConditionState = RUBBLE            Model = gbgenrubble
ModelConditionState = POST_RUBBLE       Model = None
```

`RUBBLE` swaps in a generic rubble model that has no `P1`; `POST_RUBBLE` has no model at all. The
destroy-time teardown that calls the pathfinder removal is `0x00692313` — it hides the drawable
(`0x006718FB(1)`), drops the object from `TheRadar` (`0x006D876A`), and only then calls
`0x006E85FB`. By then the death sequence has long since moved the drawable off the built model.

**(2026-08-19) The leak is bounded by the match, not by the process.** `Pathfinder::reset`
(`0x006F5B03`) frees the whole `+0x5C` ramp list and calls the slot release over all sixteen slots,
so nothing survives into the next game. Within one match nothing is given back, and the sixteen
slots — fourteen of them reachable by walls — are a hard resource.

**This is the hypothesis the whole document points at, and it is the one thing still unverified.**
The static facts (§1–§3, the guards in §4.1–4.3, the INI in §4) are all confirmed. The claim that
the model has *already* changed by `0x00692313` is inferred from the ordering of a normal
structure death, not measured.

## 5. Why a porter-built wall hits this and a castle wall may not

Three gates in `0x00936B7D` decide whether the wall handler runs at all, and a freely placed
object is likely to sit on the wrong side of them:

- **`WALK_ON_TOP_OF_WALL` (bit 60)** is the master switch. Without it `0x00935FAA` is never called
  in either direction, and whatever is left behind is *not* this bug — see §6.
- For a template that is also **`WALL_UPGRADE` (bit 150)**, the engine additionally demands
  `Drawable::hasWallBoundsMesh()` — the *runtime override* at `module+0x260`, which only
  `GeometryUpgrade` ever writes. An object carrying `WallBoundsMesh` in its `Draw` block but no
  `GeometryUpgrade` answers **no** here, and is treated as not-a-wall on both paths.
- The engine's one existing mitigation — the remove/add pair at `0x0067B428`/`0x0067B43B`, run when
  a drawable's state changes — is gated on that same `WALL_UPGRADE` + `hasWallBoundsMesh()` pair
  (`0x0067B405`, `0x0067B411`). A wall outside the castle system never gets it.

Castle walls reach destruction through `WallHubBehavior` / `CastleBehavior` / `WallUpgradeUpdate`
and through `ReplaceSelfUpgrade`'s explicit removal at `0x008BB6BE`, which fire while the object is
still whole. That is the difference in practice, not anything about how the wall was paid for.

## 6. Before fixing: confirm it is actually this

Cheap triage, in order — the symptom "geometry stays behind" covers at least three different
mechanisms and only one of them is the above:

1. **Does the template have `KindOf = WALK_ON_TOP_OF_WALL`?** If not, `RaisedWallMesh` is inert for
   that object and what is left behind is the ordinary object footprint or a `GeometryUpgrade`
   override — a different investigation.
2. **What exactly persists?** Units walking on thin air over the dead wall ⇒ the wall layer
   (`Pathfinder+0xE0` / `+0x1BEBC`) was not released, which is this bug. A blocked patch of ground
   with nothing visible ⇒ the plain pathfind footprint, i.e. `0x00936B7D`'s generic path, not
   `0x00935FAA`. A *visible* mesh still drawn ⇒ neither; that is a drawable/render-object leak.
3. **Delete the `RUBBLE`/`POST_RUBBLE` model condition states** (or point them at the intact model)
   on one test object. If the leak stops, the diagnosis in §4 is confirmed and the rest of this
   document applies.

## 7. Scoping the fix

### 7a. Data-only, no patch — try this first

Keep the named sub-objects reachable for as long as the object can be removed: give the `RUBBLE`
and `POST_RUBBLE` states the same model as the default state (or a rubble model that still carries
`P1`/`P2`/`P3` as hidden sub-objects), and let `FXList`/particles do the visual work. Costs an art
convention and nothing else; verifies the diagnosis at the same time. It does **not** cover an
object removed by `ReplaceSelfUpgrade` or by a script that deletes it outright, and it is a
constraint every future wall model has to remember — which is why the patch below is worth scoping.

### 7b. Patch — remember what was registered, instead of re-deriving it

**This is what `wall-mesh-release` does**; the shape below is the one it was built to.

**(2026-08-19) This supersedes the plan that stood here**, which was to stamp an `ObjectID` into the
layer slot and each ramp record and then sweep for it. Two things found on the re-read make a
cave-owned ledger strictly better: the layer slot is **shared between walls of equal height** (§3),
so an id stamped on the slot cannot say *which* of its members is dying; and the structures the plan
wanted to grow are pathfinder-owned allocations whose pointers **stay valid** for as long as the
registration does (§3), so there is nothing to key on that a side table cannot hold more cheaply.
Nothing in the engine is grown, which also disposes of the savegame question below.

**The ledger.** One entry per registered wall, keyed by `ObjectID`, written on the add path and
consumed on the remove path:

| field | taken from | needed by |
|---|---|---|
| `ObjectID` | `Object+0x74` | the key |
| slot index | `edi` at `0x009360BB`/`0x0093609B` | leg 1 |
| raised `RenderObjClass *` | `[ebp-0x14]` at the same point | leg 1 |
| ramp record ×2 | `[ebp-0x24]` after each `0x0067FFA6` | leg 2 |
| cell rectangle (4 dwords) | `[ebp-0x38]`, `[ebp-0x30]`, `[ebp-0x3C]`, `[ebp-0x34]` at `0x009365F9` | leg 3 |

**Leg 1 — the walkable surface, which today has no removal at all.** Unlink the recorded render
object from the recorded slot's list (the link is `renderObj+0x3C`, the head is `slot+0x38`),
destroy it the way the engine does (`(*vt[0])(0)` then `operator delete`, as `0x00768AA7` does to
the head), and when the list comes out empty call **`0x00768AA7`** on the slot to give it back.
That routine is the inverse the old plan recorded as unlocated: it clears `+0x34`, calls
`0x0076848F` to drop the cell data, destroys the head render object, and resets `+0x18`..`+0x2C`,
`+0x38` and `+0x3C`. `Pathfinder::reset` is what identifies it, looping it over all sixteen slots
at `0x006F5B03`.

**Leg 2 — the ramps.** The two `0xCC` records are already reachable by pointer, so the recorded
pointer is unlinked from the `Pathfinder+0x5C` list directly and freed. This *skips* `0x009356DF`
rather than feeding it: that routine exists to find a record by matching its four-float geometry
block at `record+0xB4`, and a pointer answers the same question exactly.

**Leg 3 — the bounds cells.** This one needs no new loop. Restore the four rectangle dwords into
their own frame slots and jump to **`0x0093682F`**, the head of the stock unmark loop, with `eax`
holding the object's id — which is the whole of that loop's input. It reads `[ebp-0x30]`,
`[ebp-0x34]`, `[ebp-0x38]` and `[ebp-0x3C]` and writes everything else it touches before reading
it, and unlike the *mark* branch it never dereferences the bounds render object, so there is no
pointer to reconstruct.

**Where the hooks go.** Three on the add path, to fill the ledger, and one on the remove path — at
`0x009362A3`'s `test eax,eax`, the bounds query's early-out, which is the point where a removal
currently gives up. A removal with no ledger entry falls through to the stock behaviour untouched,
which is what keeps a wall registered by some path this patch did not see behaving exactly as it
does today.

Cost estimate: four `rel32`, a cave of a few hundred bytes plus the ledger (11 dwords an entry;
512 entries is 22 KB and covers any map's walls). **Simulation state** — this decides where units
can walk — so every peer must run the same binary and replays will not cross, the same rule as
`spawn-union` and `multi-execute-gate`.

**Ledger lifetime.** Entries are dropped when consumed, and the whole table is cleared when the
logic clock goes backwards, the trick `cooldown-through-death` uses to stop one match inheriting
the last one's bank. That matches `Pathfinder::reset`, which frees everything this ledger describes
between matches (§4).

### 7c. Rejected

- **Hooking the destroy teardown (`0x00692313`) to remove earlier.** The model has already changed
  by then; moving the call earlier means finding a point before the death model swap, which is
  per-death-module (`SlowDeathBehavior`, `StructureCollapseUpdate`, `FireWeaponWhenDeadBehavior`)
  and therefore not one hook but several.
- **Making `Get_Sub_Object_By_Name` fall back to the built model.** The render object is gone, not
  merely swapped; there is nothing to fall back to.

## 8. Address table

| address | what |
|---|---|
| `0x00BE1320` | `W3DScriptedModelDraw` module-data field table (58 rows, one ref at `0x004C8940`) |
| `0x004C85E9` / `0x004C830D` | its constructor / destructor (the four wall strings) |
| `0x00BDFFE8` / `0x00BE3B78` | `W3DScriptedModelDraw` vtable / its `ObjectDrawInterface` vtable |
| `0x004C9323` | `getObjectDrawInterface` — returns `this + 0xC` |
| `0x004B5809` / `0x004B5814` / `0x004B582B` | set wall-bounds override / set ramp override / "is bounds override set" |
| `0x004BA4FF` `0x004BA5BB` `0x004BA693` `0x004B7A59` `0x004B7B07` `0x004BB76A` `0x004BB7EB` | the seven mesh queries (§2) |
| `0x006728A1` … `0x006729E9` | their `Drawable` wrappers; module array at `Drawable+0x14C` |
| `0x00672F44` | `Drawable::hasWallBoundsMesh` |
| `0x00DE4B40` | `TheAI`; `TheAI+0x10` is the `Pathfinder` |
| `0x006E85E9` / `0x006E85FB` | add to / remove from the pathfind map |
| `0x00936B7D` | the worker both wrap; `KindOf` gates at `0x00936BCE`–`0x00936C81` |
| **`0x00935FAA`** | **the wall handler — add vs remove, §3** |
| `0x009361B4` | its remove path (the hook point in §7b) |
| `0x009356DF` | remove a ramp record from `Pathfinder+0x5C` |
| `0x00768246` / `0x00768276` / `0x00768326` | wall-layer slot claim / list push / "is in use" |
| **`0x00768AA7`** | **the slot release — §7b's missing inverse (2026-08-19)** |
| `0x0076848F` | drops a slot's cell data; called by the release and by the share path |
| `0x00768286` | the height match that decides whether a slot is shared |
| `0x006F5B03` | `Pathfinder::reset` — the ramp list, then the release over all 16 slots |
| `0x0093629C` | where the add and remove arms rejoin for the bounds query |
| `0x009365F9` | the second read of `adding`: mark (`0x00936606`) vs unmark (`0x0093682F`) |
| `0x0093682F` | the stock cell-unmark loop — leg 3's entry point |
| `0x00935051` | marks or unmarks one cell; last argument is `adding` |
| `0x00692313` | destroy teardown: hide drawable, drop from radar, pathfinder remove |
| `0x008BAD8B` | `GeometryUpgrade::upgradeImplementation` — the only writer of the overrides |
| `0x0067B405` / `0x0067B411` | the `WALL_UPGRADE` + `hasWallBoundsMesh` mitigation gate |

KindOf bits used above, read from the name table at `0x00DA0E68`: `STRUCTURE` 7,
`WALK_ON_TOP_OF_WALL` 60, `DEFENSIVE_WALL` 61, `DO_NOT_CLASSIFY` 149, `WALL_UPGRADE` 150,
`WALL_HUB` 156, `WALL_SEGMENT` 189.
