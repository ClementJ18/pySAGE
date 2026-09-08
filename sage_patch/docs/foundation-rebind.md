# `foundation-rebind` — let a replaced structure keep the plot it stands on

**Status: implemented as `foundation-rebind`**
([`../patches/foundation_rebind.py`](../patches/foundation_rebind.py)), applying and verifying
against the real `game.dat` and composing in either order with `commandset-limit`,
`unique-production-id`, `spawn-union` and `multi-execute-gate`. Every address below was recovered
**statically** from a ROTWK `game.dat` build `2.01.2614.37001` (ImageBase `0x400000`) on
2026-08-11 with `pefile` + `capstone`, and confirmed in a running process; §8 lists the claims the
live match settled. The image the addresses came from already carries `cah-factions` (it has a
`.cahfac` section); every site cited is stock `.text` and unmoved by that patch.

## 0. The question

Edain's Iron Hills outpost can turn a settlement building into a vineyard. The data-side
implementation is a chain of workarounds: destroy the existing building, spawn the vineyard,
hide the settlement flag when it resurfaces, build a dud on the flag when the cooldown expires,
and destroy the dud when the vineyard dies. All of it exists because `ReplaceSelfUpgrade`
destroys the original, and the settlement flag treats that destruction as "my building is gone".

**Can `ReplaceSelfUpgrade` replace a building without the flag noticing?** Yes. The fix is to hand
the plot straight from the old object to the new one: two hooks, one cave, no INI required (though
§6.4 prices an opt-in keyword). On a plain `FoundationAIUpdate` plot that is one `ObjectID` and no
drawable work at all; on a `CastleBehavior` plot — which is what Edain's settlement flag is — the
occupancy that the rest of the engine reads is three fields, and §5.1 is how they are set.

## TL;DR

- A settlement flag **is** the plot. `FoundationAIUpdate` (and `CastleBehavior`, which derives from
  it) keeps **`module+0x28` = the `ObjectID` of the thing standing on me**. Non-zero means occupied,
  and the setter at `0x008582DE` is what hides the flag (`UNSELECTABLE` + a 10-frame fade-out) and
  what brings it back (fade-in over 30 frames) when it is set to `0`.
- The flag does **not** come back because of an event about death. It comes back because
  **`GettingBuiltBehavior::onDelete` (`0x0085757F`) actively frees the plot**: it reads its own
  object's producer id (`Object+0x78`), finds that object, and calls `setBuiltOnObject(0)` on its
  foundation interface. `GameLogic::destroyObject` broadcasts `onDelete` to every module **in the
  same call** (`0x0062BBAB` → `0x006902FA` → the walk at `0x00690343`), so the flag is already
  freed before `ReplaceSelfUpgrade` has created anything.
- A second, slower mechanism agrees with it: `FoundationAIUpdate::update` polls
  `findObjectByID(m_builtOnID)` every frame and clears the link when the id stops resolving
  (`0x008585EC`–`0x00858610`). `CastleBehavior` polls its keep the same way (`0x00799B13`). **The
  engine's notion of "my building" is an id, and a replacement gets a new id.**
- Nothing re-adopts. `FoundationAIUpdate`'s "scan for whatever is standing on me" pass
  (`0x008583E3`) runs **once**, on the module's first update, gated by the one-shot byte at
  `module+0x2C` — it is there for map-placed structures. After that the link is only ever
  established by the build path (`0x006AAF3B`) or a castle unpack (`0x0079ACFC`).
- `ReplaceSelfUpgrade::upgradeImplementation` (`0x008BB5FA`) destroys at `0x008BB6C6` and creates
  at `0x008BB8D9`. It already walks the whole object list afterwards to re-point references from
  the old object to the new one (`0x008BB955`–`0x008BB9E7`) — but **only for `WALL_HUB`,
  `WALL_UPGRADE` and `WALL_SEGMENT`**. The walls got a rebind; plots did not.
- The patch is a stash and a rebind: before the destroy, stash the plot id and clear
  `old->Object+0x78` so `onDelete` finds nothing; after the create, give the plot back its
  occupant. On a plain foundation plot that is two stores and **the flag never transitions** — no
  fade, no flicker, no cooldown to work around and no dud to clean up.
- **`m_builtOnID` alone leaves a castle plot capturable.** A settlement flag is a `CastleBehavior`,
  and what gates its capture is `module+0x34`, not the occupant id; the keep at `module+0x38`
  clears itself a frame later. Hook 2 therefore calls the engine's own
  `CastleBehavior::onStructureBuilt` (`0x0079AC19`) on a castle plot, which sets all of it. §5.1
  has the live comparison that forced this.
- **This is simulation state.** Every peer needs the patched binary and replays will not play back
  on a stock one.

## 1. What a settlement flag actually is

Two modules share one base. `CastleBehavior`'s instance constructor (`0x0079A901`) calls
`FoundationAIUpdate`'s (`0x00858217`) as its base, and both write **the same vtable
`0x00C30DE8`** into `module+0x20` — `CastleBehavior` overrides none of it. So there is a single
foundation interface, eight slots wide, reached from any object by:

```
0068c3c3  56                 push esi
0068c3c4  8b b1 4c 02 00 00  mov  esi, [ecx+0x24c]     ; the module list
0068c3ca  eb 12              jmp  .next
0068c3cc  8d 48 0c    .ask:  lea  ecx, [eax+0xc]
0068c3cf  8b 01              mov  eax, [ecx]
0068c3d1  ff 90 98 00 00 00  call [eax+0x98]           ; getFoundationInterface()
0068c3d7  85 c0              test eax, eax
0068c3d9  75 09              jnz  .done
0068c3db  83 c6 04           add  esi, 4
0068c3de  8b 06       .next: mov  eax, [esi]
0068c3e0  85 c0              test eax, eax
0068c3e2  75 e8              jnz  .ask
0068c3e4  5e          .done: pop  esi
0068c3e5  c3                 ret
```

the same `Object+0x24C` walk `getSpawnBehaviorInterface` (`0x0068C3A3`) and
`getProductionUpdateInterface` (`0x0068C327`) use — see
[`spawn-behavior-union.md`](spawn-behavior-union.md) §1 and
[`live-object-model.md`](live-object-model.md) §5. The answering thunk is `0x008A18E0`
(`return this-0xc ? this+0x14 : 0`, i.e. `module+0x20`).

| interface slot | what | address |
|---|---|---|
| `+0x08` | `setBuiltOnObject(ObjectID)` | thunk `0x0079AA54` → **`0x008582DE`** |
| `+0x0C` | `isOccupied()` — `return m_builtOnID != 0` | `0x0097031D` |
| `+0x14` | `clearBuiltOn()` — `setBuiltOnObject(0)` | `0x008583D8` |

and the state it guards, on the module itself:

| offset | field | set by |
|---|---|---|
| `module+0x08` | `Object *` (the flag/plot) | base ctor |
| `module+0x20` | foundation-interface subobject (vtable `0x00C30DE8`) | `0x0085825F` |
| `module+0x24` | `1` | ctor |
| **`module+0x28`** | **`m_builtOnID` — the occupant** | `0x008582F5` |
| `module+0x2C` | first-update flag, initialised to `1` | ctor `0x00858269`, cleared `0x00858505` |

The plot is identified in data by **`KindOf = BASE_FOUNDATION`** (index **104**, the name table at
`0x00DA0E68`, mask at `ThingTemplate+0x108`, so `test dword [tmpl+0x114], 0x100`). The build path
and the script/AI "can I build here" predicate (`0x007E66EE`) both gate on it.

## 2. Why the flag hides, and why it comes back

`FoundationAIUpdate::setBuiltOnObject(ObjectID)` at **`0x008582DE`** is the whole of the visual
mechanic. It early-outs when the id is unchanged, then branches on zero/non-zero:

**occupied** (`id != 0`, `0x008582FE`)
- `Object::setStatus(3 /* UNSELECTABLE */, true)` — `0x0062684D`; the plot stops being clickable.
- on the drawable: `0x006719FA(0)` (drop selection, via `TheInGameUI` vtable `+0x10C`) and
  **`0x00670A50(0x0A)` — fade out over 10 frames**.
- a `WALL_UPGRADE` plot (`tmpl+0x11A & 0x40`, KindOf **150**) takes a different branch entirely and
  keeps its decal/EVA handling.

**freed** (`id == 0`, `0x0085838B`)
- if the plot is `WALL_UPGRADE` — **skip everything**; the flag stays hidden. (This is the only
  data-only lever in the whole mechanism, and it is the wrong one: it would also keep the flag
  hidden when a player legitimately razes the building. See §6.5.)
- otherwise `Object::setStatus(3, false)`, then `0x006719FA(1)` and
  **`0x00670AA2(0x1E)` — fade in over 30 frames**, starting from opacity `0`.

That 30-frame fade-in *is* "the flag pops back up".

Two things call the freed path.

### 2.1 The active one — `GettingBuiltBehavior::onDelete`

`GettingBuiltBehavior` (instance factory `0x0064A68A`, ctor `0x00857399`) is the module a
buildable structure carries. Slot `+0x20` of its main vtable `0x00C56D24` is `0x0085757F`, a
no-argument teardown hook:

```
0085757f  56                 push esi
00857580  8b f1              mov  esi, ecx
00857582  8b 46 08           mov  eax, [esi+8]         ; my Object *
00857585  ff 70 78           push [eax+0x78]           ; m_producerID -> the plot
00857588  8b 0d 2c 41 de 00  mov  ecx, [TheGameLogic]
0085758e  e8 ee 20 bf ff     call 0x449681             ; findObjectByID
00857593  85 c0              test eax, eax
00857595  74 1d              jz   .out
00857597  8b c8              mov  ecx, eax
00857599  e8 25 4e e3 ff     call 0x68c3c3             ; getFoundationInterface(plot)
0085759e  85 c0              test eax, eax
008575a0  74 12              jz   .out
008575a2  8b c8              mov  ecx, eax
008575a4  ff 52 14           call [edx+0x14]           ; clearBuiltOn()  <-- the flag returns
```

The link it follows is the one the build path laid down: at `0x00857AEA` /`0x00857AF2` the
structure's `Object+0x78` is set to the plot and the plot's `Object+0x7C` to the structure
(`Object::setProducer` `0x0068B6A1`, sibling setter `0x0068B6B6`).

**`onDelete` is broadcast from inside `destroyObject`, not at some later reap.**
`GameLogic::destroyObject` (`0x0062BBAB`) marks the object, notifies one interface family, adds
it to the destroy list at `TheGameLogic+0x108`, and calls `0x006902FA`, whose tail is the
module walk that calls vtable `+0x20` on every module with no arguments:

```
00690343  8b b6 4c 02 00 00  mov  esi, [esi+0x24c]
0069034c  8b 01       .loop: mov  eax, [ecx]
0069034e  ff 50 20           call [eax+0x20]           ; onDelete()
00690351  83 c6 04           add  esi, 4
```

So by the time `ReplaceSelfUpgrade` reaches its creation loop, **the plot is already free and the
flag is already fading in**.

### 2.2 The backstop — the liveness poll

`FoundationAIUpdate::update` (`0x008584DB`, slot 0 of the `+0x10` vtable `0x00C56D60`) ends with:

```
008585ec  8b 46 18           mov  eax, [esi+0x18]      ; m_builtOnID  (esi = module+0x10)
008585ef  85 c0              test eax, eax
008585f1  74 14              jz   .free
008585f3  8b 0d 2c 41 de 00  mov  ecx, [TheGameLogic]
008585f9  50                 push eax
008585fa  e8 82 10 bf ff     call 0x449681             ; findObjectByID
008585ff  85 c0              test eax, eax
00858601  0f 85 e8 00 00 00  jnz  .done                ; still alive -> nothing to do
00858607  6a 00       .free: push 0
00858609  8d 4e f0           lea  ecx, [esi-0x10]
0085860c  e8 cd fc ff ff     call 0x8582de             ; setBuiltOnObject(0)
```

`findObjectByID` (`0x00449681`) is a lookup in the map at `TheGameLogic+0xB4` whose entries are
`{id, Object *}` — the same table [`live-object-model.md`](live-object-model.md) §1 documents.
An id that no longer resolves is the engine's definition of "gone".

`CastleBehavior` does the same for its keep: `0x00799B13` polls `findObjectByID(this+0x38)` on a
throttled interval, and `0x007996D3` answers "does this castle have a free plot" by walking its
member id vector at `+0x50`/`+0x74` and asking each member's **foundation interface**
`isOccupied()`. So a camp-style flag reads the same dword this patch would maintain.

### 2.3 Nothing re-adopts

`FoundationAIUpdate` does have a "look around and adopt whatever is standing on me" pass —
`0x008583E3`, slot `+0x40` of the main vtable `0x00C56E30`. It builds a geometry filter from the
plot's own footprint, asks `ThePartitionManager` for an object in it, checks the
`BASE_DEFENSE_FOUNDATION`(153)/`FS_BASE_DEFENSE`(64) pairing, and then calls
`setBuiltOnObject(found->id)` and `setProducer(found, plot)`.

It is fired from exactly one place, under the one-shot flag:

```
008584eb  80 7e 1c 00        cmp  byte [esi+0x1c], 0   ; module+0x2c, 1 from the ctor
008584ef  0f 84 83 00 00 00  jz   .skip
008584f6  8d 4e f0           lea  ecx, [esi-0x10]
008584f9  8b 01              mov  eax, [ecx]
008584fb  ff 50 40           call [eax+0x40]           ; the scan
008584fe  ...
00858505  c6 46 1c 00        mov  byte [esi+0x1c], 0   ; never again
```

It exists for structures the map places on plots at load. A plot that is freed mid-match will
never look again, which is why the vineyard cannot simply be dropped where the old building was.

## 3. What `ReplaceSelfUpgrade` does

Registration is `addModule(0x006570FE)` from `0x0065A75A`, instance factory `0x00650430`
(`sizeof` `0x20`, ctor `0x008BB174`), ModuleData factory `0x00650468` (`sizeof` `0x144`, ctor
`0x008BBA3A`), interface mask `0x8C`. The ModuleData is `UpgradeMuxData` plus **one**
`AsciiStringList` at `+0x138`; the field table is `0x00C6F6E8`, two rows, referenced once (the
`getFieldParse` thunk at `0x008BB169`).

> **Aside, worth knowing before touching the data:** `ReplaceWith` (`0x00C6F6E8`) and
> `AndThenAddA` (`0x00C6F6F8`) parse with the **same function into the same offset `0x138`**.
> They are aliases for one list, not two fields — anything named in `AndThenAddA` is treated as
> another object to spawn.

Two functions matter:

- **`0x008BB23F`** — the placement test. Sums the `ReplaceWith` templates' footprints
  (`tmpl+0xC8`), walks the objects and the terrain under the resulting strip, and refuses on a
  `WALL_HUB` clash or too much height variance (`GameData+0xA70`).
- **`0x008BB5FA`** — `upgradeImplementation`, in order:

  | address | what |
  |---|---|
  | `0x008BB682`, `0x008BB68A` | two teardown calls on self |
  | `0x008BB6A7` | `0x006718FB(1)` on the drawable — hide it |
  | `0x008BB6BE` | remove from the client-side list (`[0xDE4B40]+0x10`) |
  | **`0x008BB6C6`** | **`GameLogic::destroyObject(self)`** — and with it the `onDelete` broadcast |
  | `0x008BB6DD`.. | lay the replacements out along the old object's facing |
  | **`0x008BB8D9`** | create the replacement (`[0xDE8200]` vtable `+0x38`), `edi` = new `Object *` |
  | `0x008BB8F1`, `0x008BB900` | position it, copy the old object's orientation from `Object+0x88` |
  | `0x008BB93F` | carry a value into `newObj+0x33C` |
  | **`0x008BB955`–`0x008BB9E7`** | **walk every object and re-point references from the old id to the new object** |

That last block is the engine already solving this exact problem — for walls only:

```
008bb955  8b 46 f8           mov  eax, [esi-8]         ; the old Object * (still valid)
008bb958  8b 40 74           mov  eax, [eax+0x74]      ; its ObjectID
008bb961  89 45 c4           mov  [ebp-0x3c], eax
008bb964  e8 26 7a 0b 00     call 0x97338f             ; head of the global object list
...
008bb96d  8b 47 04    .each: mov  eax, [edi+4]         ; ThingTemplate *
008bb970  f6 80 1b 01 00 00 10  test byte [eax+0x11b], 0x10   ; WALL_HUB      (156)
008bb977  75 12              jnz  .rebind
008bb979  f6 80 1a 01 00 00 40  test byte [eax+0x11a], 0x40   ; WALL_UPGRADE  (150)
008bb980  75 09              jnz  .rebind
008bb982  f6 80 1f 01 00 00 20  test byte [eax+0x11f], 0x20   ; WALL_SEGMENT  (189)
008bb989  74 54              jz   .next
008bb98b  8b cf       .rebind: mov ecx, edi
008bb98d  e8 54 0a dd ff     call 0x68c3e6             ; the wall interface (vtable +0x80)
...        ff 50 5c          call [eax+0x5c]           ; "do you hold this id?"
...        ff 50 48          call [eax+0x48]           ; "hold this object instead"
008bb9df  8b bf 8c 00 00 00 .next: mov edi, [edi+0x8c] ; global list next
```

Note what this proves for free: **the old `Object *` is still readable after `destroyObject`** —
the destroy is deferred, only the `onDelete` broadcast is immediate.

## 4. The failure, stated exactly

1. `upgradeImplementation` calls `destroyObject(old)` at `0x008BB6C6`.
2. `destroyObject` immediately broadcasts `onDelete`; `GettingBuiltBehavior::onDelete` follows
   `old->Object+0x78` to the plot and calls `setBuiltOnObject(0)`.
3. The plot clears `UNSELECTABLE` and fades its flag in over 30 frames. It is now, to the engine
   and to the player, an empty settlement plot.
4. ~100 instructions later the vineyard is created — through `ThingFactory`, not through the
   build path — so nothing sets the plot's `m_builtOnID`, nothing sets the vineyard's
   `Object+0x78`, and the one-shot adopt scan has long since fired.
5. Every downstream rule follows from that dword: the plot offers its unclaimed command set again,
   `CastleBehavior`'s emptiness test agrees, and the mod has to hide the flag by hand and stand a
   dud on it to make the plot read as occupied.

There is no "the flag was told the building died" event to suppress. There is one link, and
`ReplaceSelfUpgrade` drops it.

## 5. The fix, as built

Keep the link. Two `call rel32` repointed at the two moments that matter, and one `.fndrbd` cave
of **`0x17A` bytes** — a `0x20`-byte ring, a `0x77`-byte stash thunk, a `0xE3`-byte rebind thunk.
Both hooks replace a `call` and tail-jump to the function that `call` named, so the stock return
value and the stock `ret` size stay the caller's and no instruction is displaced.

**Hook 1 — `0x008BB6CC`, the `call GameLogic::destroyObject`.** Entered with the dying object
already pushed and `TheGameLogic` already in `ecx`; ends `jmp 0x0062BBAB`.

```
plotId = old->[0x78]                                    ; m_producerID
plot   = findObjectByID(plotId)                         ; 0 -> NULL, no special case
iface  = plot ? plot->getFoundationInterface() : NULL   ; 0x0068C3C3
if (iface && iface->[0x08] == old->[0x74]) {            ; it really is a plot, holding *me*
    ring[free] = (old->[0x74], plotId)                  ; keyed on the dying object's id
    old->[0x78] = 0                                     ; GettingBuiltBehavior::onDelete no-ops
}
<fall through to destroyObject>
```

**Hook 2 — `0x008BB964`, the `call GameLogic::getFirstObject`** that starts the stock wall walk,
one instruction after the frame slot holding the dying object's id is filled. Entered with
`TheGameLogic` in `ecx`; ends `jmp 0x0097338F`.

```
key = [ebp-0x3c]                                        ; the dying object's id
slot = ring.find(key); if (!slot) <fall through>
plotId = slot.plotId; slot.key = 0                      ; consumed either way
new    = [ebp-0x20]                                     ; the object just created
plot   = findObjectByID(plotId); iface = plot->getFoundationInterface()
occupant = iface->[0x08]
if (occupant == 0 || occupant == key) {                 ; free, or still naming the dead object
    module = iface - 0x20
    if (module->[0x00] == 0x00C30ED8                    ; a CastleBehavior, not a plain foundation
        && new->tmpl[0x10b] & 0x10) {                   ; and the replacement is a CASTLE_KEEP
        if (module->[0x38] == key) module->[0x38] = 0   ; cut the keep naming the dead object
        if (module->[0x38] == 0) {
            module->onStructureBuilt(new)               ; 0x0079AC19 — the engine's own adoption
            module->[0x34] = 4                          ; the state the capture tick gates on
        }
    } else {
        iface->[0x08] = new->[0x74]                     ; occupied again — a direct store
    }
    new->[0x78] = plotId                                ; the replacement now owns the plot
    if (plot->[0x7c] == key) plot->[0x7c] = new->[0x74]  ; only when provably stale
}
```

Properties that make it cheap, and that the tests pin:

- **A castle plot goes through the engine's own adoption; a plain one takes the direct store.**
  §5.1 is why: `m_builtOnID` is not what a settlement flag is read by. On the direct-store path
  no visual transition happens at all — writing `+0x28` rather than calling `setBuiltOnObject` is
  deliberate, because the setter resets the drawable's opacity to `1.0` before starting its
  10-frame fade-out (`0x00670A50`), which on an already-hidden flag is a blink.
- **It covers both teardown mechanisms.** Hook 2 commits when the plot is free — the usual case,
  `onDelete` having run inside `destroyObject` — **or** when it still names the object just
  destroyed, which is what a structure carrying no `GettingBuiltBehavior` leaves behind and the
  frame poll would have cleared later. A plot claimed by anybody else in between is left alone.
- **Every write is guarded by a proof of ownership.** `Object+0x78` is `m_producerID` generally —
  on a unit it is the barracks — so hook 1 zeroes it only after resolving it to an object that has
  a foundation interface *and* is holding the dying object. `Object+0x7C` on the plot is rewritten
  only while it still names the object being replaced. Nothing is written on a guess.

Cost: **eight bytes** of `.text` (two `rel32` displacements; the `0xE8` opcodes stay put), no
struct growth, no table relocation, no INI change, no savegame change.

**Failure modes degrade to stock, never to a stuck plot.** The one path that destroys and then
bails without creating — a `ReplaceWith` naming a template `ThingFactory` does not know
(`0x008BB6F1`) — leaves the plot holding an id that no longer resolves and no ring consumer, which
is exactly the state `FoundationAIUpdate::update`'s poll exists for: the flag comes back a frame or
two later, as it does today.

**Re-entrancy.** The pair lives in a four-slot ring **keyed on the dying object's id** rather than
in a single dword, because hook 2 has that id for free in the stock frame slot the wall walk just
filled. Keying rather than stacking is what makes the failure mode safe: a nested
`ReplaceSelfUpgrade` takes its own slot, a creation that fails leaves an entry no later object can
match, and a fifth level of nesting loses a rebind instead of binding the wrong plot.

### 5.1 Why `m_builtOnID` alone is not enough on a castle plot

The first build rebound `m_builtOnID` and nothing else, on the reasoning that
`FoundationAIUpdate` and `CastleBehavior` share the interface and the field. In a match it left a
converted settlement **capturable**: the AI walked a squad onto the flag, took it, and the
replacement went with it — because the patch had made the replacement the plot's occupant, and
`CastleBehavior::forEachCastleObject` (`0x007999E2`) enumerates the occupant through interface
slot `+0x18` and hands it to whoever captures the castle.

Read live out of a running match (`sage_live`, one Edain skirmish, the two flags side by side):

| | flag holding a mine shaft | flag holding a replacement | an unbuilt flag |
|---|---|---|---|
| `Object+0x94` status | `UNSELECTABLE` | — | — |
| `module+0x28` `m_builtOnID` | the mine shaft | **the replacement** | 0 |
| `module+0x34` state | 4 | 0 | 0 |
| `module+0x38` keep | the mine shaft | 0 | 0 |

In every field but the one the patch maintained, the converted plot was **byte-identical to an
empty one**. Three mechanisms follow from that, and only the first reads `m_builtOnID`:

- `isOccupied` (`0x0097031D`) — the interface's own question, and the one the patch answered.
- **The capture tick.** `CastleBehavior`'s per-frame capture pass (`0x0079B3C4`) opens with a
  gate at `0x007983E3` that returns false — no capture — unless `module+0x34` is zero *and* the
  byte at `module+0x3c` is zero. `module+0x34` is what says "something stands on me". This is the
  whole of why an ordinary farm's flag is never captured while the farm is up, and it is the field
  the first build left at 0. (`CastleBehavior::isPlayerAllowedToCapture`, `0x0079A3D9`, is only
  *who* may capture — not already mine, and my faction is in `CastleToUnpackForFaction`. It never
  looks at occupancy, which is why the gate above has to.)
- **The keep.** `module+0x38` is polled against `findObjectByID` every update (`0x00799B13`), so
  it clears itself a frame after the replacement destroys the object it named.

`CastleBehavior::onStructureBuilt` (`0x0079AC19`) is the engine's own "a structure now stands on
me", and it sets all of it: it registers the object with its `CastleMemberBehavior`, adopts it as
the keep when the template is `CASTLE_KEEP` (`0x0079ACA4`), and ends by calling
`setBuiltOnObject(m_keepID)` itself (`0x0079ACFC`) — which is what sets `UNSELECTABLE` and fades
the flag out. The stock caller at `0x0079B734` writes `module+0x34 = 4` beside it, and hook 2
mirrors both.

**The stale keep has to be cut before the call.** `onStructureBuilt` reads a non-zero
`module+0x38` as "I already have a keep" and **destroys its argument** (`0x0079ACAD` →
`0x0079AD06`). At hook 2 time the keep still names the object just destroyed — the poll that would
clear it does not run until the next frame — so hook 2 zeroes it when, and only when, it names
that object, and otherwise falls back to the direct store rather than risk the adoption.

**What the tests check** ([`../../tests/sage_patch/test_foundation_rebind.py`](../../tests/sage_patch/test_foundation_rebind.py)).
Three things here fail silently rather than loudly, so all three are asserted statically: both
frame displacements are re-derived from the stock instructions that *fill* those slots (carried as
fingerprint windows, so the test cannot merely agree with the patch); the cave is disassembled back
and every structure offset it touches asserted, along with the fact that the only ways out of it
are two `jmp`s to the replaced functions and three `call`s to the routines it names; and each of
the nineteen fingerprint windows is disturbed in turn and has to make both `apply` and `verify`
fail. The castle fields are pinned from both ends — the offsets against `CastleBehavior`'s own
constructor and against `onStructureBuilt`, and `module+0x34` against the capture gate that reads
it — so a wrong offset fails the suite rather than silently writing into a live module.

## 6. Alternatives considered

### 6.1 Patch the poll instead (`0x00858607`)

Make `FoundationAIUpdate::update` re-run the adopt scan before clearing, so a plot that lost its
occupant looks for a new one. **This does not fix the case at hand**: the flag is freed by
`GettingBuiltBehavior::onDelete` inside `destroyObject`, in the same frame and before the
replacement exists, so the poll never sees a dangling id. It also cannot avoid the blink — the
scan reaches the plot through `setBuiltOnObject`, which restarts the fade. Worth keeping as a note
for a *different* patch (structures that vanish without `GettingBuiltBehavior`), not for this one.

### 6.2 Let the replacement inherit the old `ObjectID`

Attractive — every holder of the id would follow — and wrong. The id keys the map at
`TheGameLogic+0xB4`, the old object outlives the call on the destroy list, and one id cannot name
two objects. The blast radius is selection, orders, the AI, scripts and the replay stream.

### 6.3 Generalise to every replacement mechanism

`ReplaceObjectUpdate` and OCL-based swaps have the same hole. The hook site is specific to
`ReplaceSelfUpgrade`; the cave body is not, and could be shared. Out of scope for now, though the
narrow version being runtime-verified removes the reason to wait.

### 6.4 Opt-in keyword

If stock behaviour must be preserved for existing data, gate the rebind on a new
`ReplaceSelfUpgrade` field — `KeepFoundation = Yes`, default `No`. The price is small: the
`UpgradeMuxData` constructor (`0x00653173`) writes bytes at table-offsets `0x12C`, `0x12D` and
`0x12E` and **never touches `0x12F`**, which is alignment padding ahead of the list at `0x138` —
the same shape `terrain-resource-exp` and `queue-ignore-cp` exploited, and the three byte stores
collapse into one dword store that clears it on the way past. The keyword itself needs
`ReplaceSelfUpgrade`'s own field table (`0x00C6F6E8`, two rows) relocated to gain a row: **one
reference**, at `0x008BB169`.

**What shipped is ungated**, and the field is not implemented. A plot whose building is replaced in
place should keep the building; no mod wants the flag back *and* the old building gone, and a
keyword nobody would set to `No` is a table relocation and an INI surface for nothing. The costing
stays here because it is the price of changing that mind, not because it was paid.

### 6.5 Data-only

None that is correct. The only lever the engine offers is `KindOf = WALL_UPGRADE` on the flag,
which makes the freed branch skip the un-hide entirely (`0x0085838B`) — the flag would stay hidden
after a *legitimate* demolition too, and the plot would be unbuildable for the rest of the match.

## 7. Blast radius

- **Simulation state.** `m_builtOnID` and `Object+0x78` feed selection, the plot's command set,
  the AI's "can I build here" predicate (`0x007E66EE`) and `CastleBehavior`'s emptiness test. Every
  peer needs the patched binary; replays recorded on it will not play back on a stock one.
- **Only `ReplaceSelfUpgrade`.** Objects destroyed any other way still free their plot exactly as
  today, including the vineyard itself when it dies.
- **Only the first replacement** takes the plot when `ReplaceWith` names several. That is a
  decision, not a fallout: a plot holds one occupant, and the first entry is the one the layout
  code centres.

## 8. What the live match settled

**The patch applies, verifies and composes; none of that would have said it works in a match.**
These are the claims the running game settled, in the order they would have bitten.

1. **Which module Edain's settlement flag carries — and that sharing the interface is not enough.**
   `WirtschaftPlotFlag_Real` carries `CastleBehavior`, and the structures that stand on it are its
   **keep**: `DwarvenMineShaft`, `DorwinionVineyard` and the `VineyardControlPing` dud are all
   `CASTLE_KEEP`. The first build rebound only the field the two modules share, and the converted
   plot came out capturable — §5.1 has the live comparison and the three fields that follow, which
   hook 2 now maintains through `onStructureBuilt`. The castle's member vector (`+0x50`/`+0x74`) is
   still untouched, and reads empty on both flags of the measured match: a settlement castle keeps
   its occupant in the keep and the interface field, not in that vector. A camp whose members are
   populated is the case that has not been exercised.
2. **That `onDelete` is what pops the flag in the Iron Hills case**, i.e. that the settlement
   building really carries `GettingBuiltBehavior`. A breakpoint on `0x0085757F` during one vineyard
   conversion settles it. It is no longer load-bearing for correctness — hook 2 commits on a plot
   that is free *or* still naming the destroyed object, so the poll-only world works too — but it
   decides whether hook 1 is doing anything, and a hook that never fires should be known about.
3. **The vtable-slot names.** `+0x20` of the module vtable is `onDelete` by shape — no arguments,
   broadcast to every module from the destroy path — not by symbol. Same for `setBuiltOnObject`;
   the *behaviour* at `0x008582DE` is proven, the name is mine.
4. **The identity of `[0xDE8200]`**, the singleton whose vtable `+0x38` mints the replacement.
   Irrelevant to the patch — it hands back the new `Object *` either way — but the one function
   name in this document with nothing behind it.

The in-game test is one settlement, one conversion: build on a settlement, convert it to a
vineyard, and watch the flag. Then destroy the vineyard and watch the flag come back — the second
half matters as much as the first, because a patch that leaked the plot would look perfect until
somebody razed the building.

## 9. Address table

| what | address |
|---|---|
| `Object::getFoundationInterface()` (module `+0xC` vtable slot `+0x98`) | `0x0068C3C3` |
| foundation-interface vtable (`module+0x20`), shared by both modules | `0x00C30DE8` |
| `setBuiltOnObject(ObjectID)` (interface `+0x08`) | `0x0079AA54` → `0x008582DE` |
| `isOccupied()` (interface `+0x0C`) | `0x0097031D` |
| `clearBuiltOn()` (interface `+0x14`) | `0x008583D8` |
| `FoundationAIUpdate` instance / ModuleData factory | `0x0064A713` / `0x00653209` |
| `FoundationAIUpdate` ctor (`sizeof` `0x30`), vtables `0x00C56E30`/`0x00C56D70`/`0x00C56D60` | `0x00858217` |
| `FoundationAIUpdate::update` (`+0x10` vtable slot 0) | `0x008584DB` |
| one-shot adopt scan (main vtable slot `+0x40`) | `0x008583E3` |
| the liveness poll and its clear | `0x008585EC` … `0x0085860C` |
| `CastleBehavior` instance / ModuleData factory | `0x0064A74F` / `0x0064A78A` |
| `CastleBehavior` ctor (`sizeof` `0xAC`) / `update` | `0x0079A901` / `0x0079CF2A` |
| `CastleBehavior` keep poll / free-plot test / unpack's `setBuiltOnObject` | `0x00799B13` / `0x007996D3` / `0x0079ACFC` |
| `CastleBehavior` main vtable (`module+0x00`), the castle/foundation discriminator | `0x00C30ED8` |
| **`CastleBehavior::onStructureBuilt(Object *)`** (`ret 4`), what hook 2 calls | **`0x0079AC19`** |
| … its `CASTLE_KEEP` test / second-keep reject / keep store | `0x0079ACA4` / `0x0079ACAD` → `0x0079AD06` / `0x0079ACB9` |
| … its other two callers, and the stock `module+0x34 = 4` beside one | `0x0079B94E`, `0x0079B9C8`; `0x0079B734` |
| the capture tick, and its `module+0x34`/`module+0x3c` gate | `0x0079B3C4` / `0x007983E3` |
| `CastleBehavior::isPlayerAllowedToCapture` (who, never whether) | `0x0079A3D9`, faction test `0x007998FF` |
| `CastleBehavior::forEachCastleObject` — self, occupant (interface `+0x18`), members | `0x007999E2` |
| `CastleMemberBehavior` ctor (`sizeof` `0x28`) | `0x00797FDD` |
| `GettingBuiltBehavior` instance factory / ctor | `0x0064A68A` / `0x00857399` |
| **`GettingBuiltBehavior::onDelete`** (main vtable `0x00C56D24` slot `+0x20`) | **`0x0085757F`** |
| the build path's `setBuiltOnObject(new->id)` | `0x006AAF3B`, call at `0x006AAF93` |
| producer / back-link setters, and where the build path calls them | `0x0068B6A1` / `0x0068B6B6`, `0x00857AEA` / `0x00857AF2` |
| `GameLogic::destroyObject` | `0x0062BBAB` |
| `onDelete` broadcast (walk at `0x00690343`) | `0x006902FA` |
| `GameLogic::findObjectByID` (map at `TheGameLogic+0xB4`) | `0x00449681` |
| `Object::setStatus(bit, Bool)` | `0x0062684D` |
| `Drawable` fade-out / fade-in | `0x00670A50` / `0x00670AA2` |
| `ReplaceSelfUpgrade` registration (mask `0x8C`) | `0x0065A75A` |
| `ReplaceSelfUpgrade` instance / ModuleData factory | `0x00650430` / `0x00650468` |
| `ReplaceSelfUpgrade` ModuleData ctor (`sizeof` `0x144`) / field table / its one reference | `0x008BBA3A` / `0x00C6F6E8` / `0x008BB169` |
| `ReplaceSelfUpgrade` placement test | `0x008BB23F` |
| **`ReplaceSelfUpgrade::upgradeImplementation`** | **`0x008BB5FA`** |
| … its `destroyObject` call — **hook 1** repoints it | `0x008BB6CC` |
| … its creation call, and the frame slot it fills (`[ebp-0x20]`) | `0x008BB8D9` … `0x008BB8E0` |
| … the wall-only rebind walk, whose opening `call` **hook 2** repoints | `0x008BB955` … `0x008BB9E7` |
| `UpgradeMuxData` ctor (padding at table-offset `0x12F`) | `0x00653173` |
| `KindOf` name table | `0x00DA0E68` |
| the `.fndrbd` cave: ring / stash thunk / rebind thunk | `0x20` / `0x77` / `0xE3` bytes |

`KindOf` indices used above: `FS_BASE_DEFENSE` 64, `BASE_FOUNDATION` 104, `NEED_BASE_FOUNDATION`
105, `WALL_UPGRADE` 150, `BASE_DEFENSE_FOUNDATION` 153, `WALL_HUB` 156, `WALL_SEGMENT` 189.

`Object` fields used above: `+0x74` `ObjectID`, `+0x78` producer id, `+0x7C` the plot's back-link,
`+0x88` orientation, `+0x8C`/`+0x90` global list links, `+0x24C` module array, `+0x440` command-set
override, `+0x458` bit 0.
