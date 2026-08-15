# `RaisedWallMesh` geometry survives the wall that owned it

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Static recovery only — **nothing here has been
confirmed against a running game yet**; §7 is the test that would.

**The finding in one sentence.** The pathfinder registers a wall's walkable surface by *asking the
drawable for a named sub-object of its current model*, and it **un**registers it the same way — so
the removal is not the inverse of the addition, it is the addition run again against whatever model
the drawable is showing now. A dying wall changes model before it is destroyed, the named mesh is
no longer in it, every lookup on the removal path answers "not found", and the walkable geometry is
never taken back out.

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

| | add (`adding != 0`) | remove (`adding == 0`) |
|---|---|---|
| raised surface | `Drawable::0x67290D` → iface `+0x9C` → **`RaisedWallMesh`**; claims a slot in the 16-entry table at `Pathfinder+0xE0` (stride `0x40`), storing the *`RenderObjClass *`* of the mesh (`0x00768276` / `0x00768246`) | — |
| ramp 1 | `Drawable::0x6729A3` → iface `+0xA8`; `new(0xCC)`, built by `0x0067FFA6`, linked into the list at `Pathfinder+0x5C` | same query; `new(0xCC)`, built the same way, then `0x009356DF(record, 0)` **removes by value** and the temporary is deleted |
| ramp 2 | `Drawable::0x6729E9` → iface `+0xAC`; same | same |
| wall bounds | — | `Drawable::0x6728D7` → iface `+0x98`; **`test eax,eax; je 0x936B6C`** — a NULL answer returns from the function; otherwise the returned height is matched against the wall-layer height array at `Pathfinder+0x1BEBC` (count at `+0x1BEB8`) to pick the layer to release |

## 4. The failure, stated exactly

Nothing about the wall's footprint is *recorded* at add time in a form the remove path consults. The
remove path rebuilds the same three queries and cancels whatever they return **now**:

1. Each removal step is guarded by its own query succeeding —
   `0x009361CF` (ramp 1), `0x00936242` (ramp 2), `0x009362AD` (wall bounds, an early **return**).
2. Every one of those queries ends in `Get_Sub_Object_By_Name` against the render object the
   drawable is holding **at the moment of the call**.
3. The layer is not identified by object id or by anything the wall owns. It is found by matching a
   *height* that the removal has to recompute from the mesh.

So the moment the model stops containing `P1`/`P2`/`P3`, the wall's pathfinding data becomes
unreachable — not stale, *unreachable*. There is no code path left that can name it.

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

### 7b. Patch — remove by identity instead of by re-query

The right shape, matching how the rest of this repo's patches work:

- **Record the owner.** At add time in `0x00935FAA`, stamp the `ObjectID` (`Object+0x74`) into the
  wall-layer slot (`Pathfinder+0xE0 + i*0x40`) and into each `0xCC` ramp record. Both structures
  need to be checked for slack first — `0x40` and `0xCC` are generous, but the constructors
  (`0x00768276`, `0x0067FFA6`) have to be read for what they already write.
- **Add an id-keyed removal.** A new cave routine that walks the 16 layer slots and the
  `Pathfinder+0x5C` list, releasing everything stamped with the dying object's id, using the
  engine's own release calls (`0x009356DF` for a ramp record; whatever `0x00768246`/`0x00768276`'s
  inverse turns out to be for a layer — **this is the one piece not yet located**).
- **Two hooks.** In `0x00935FAA`, take the remove path (`adding == 0`) to the id-keyed routine
  instead of the three re-queries. That is one `jmp` at `0x009361B4` plus the cave. The add path is
  untouched, so an object that never registered costs nothing.
- **Do not touch `0x0067B405`'s gate.** Widening the `WALL_UPGRADE` mitigation is tempting and does
  not help: it would still remove by re-query, against a model that has already changed.

Cost estimate: one `rel32`, a cave of a few hundred bytes, and two struct fields in space that has
to be proven free. **Simulation state** — this decides where units can walk — so every peer must
run the same binary and replays will not cross, the same rule as `spawn-union` and
`multi-execute-gate`.

**Savegame note:** the layer table and the ramp list are pathfinder state; if they are `Xfer`'d, an
added id field changes the blob and needs a version bump. Not yet checked.

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
| `0x00768276` / `0x00768246` / `0x00768326` | wall-layer slot init / claim / "is in use" |
| `0x00692313` | destroy teardown: hide drawable, drop from radar, pathfinder remove |
| `0x008BAD8B` | `GeometryUpgrade::upgradeImplementation` — the only writer of the overrides |
| `0x0067B405` / `0x0067B411` | the `WALL_UPGRADE` + `hasWallBoundsMesh` mitigation gate |

KindOf bits used above, read from the name table at `0x00DA0E68`: `STRUCTURE` 7,
`WALK_ON_TOP_OF_WALL` 60, `DEFENSIVE_WALL` 61, `DO_NOT_CLASSIFY` 149, `WALL_UPGRADE` 150,
`WALL_HUB` 156, `WALL_SEGMENT` 189.
