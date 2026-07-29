# Hero recruitment across two buildings — reverse-engineering notes

The RE behind [`patches/unique_production_id.py`](../patches/unique_production_id.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-07-30.

## The report

> Recruit hero A from building A, then click hero B on building B: the money is taken and no
> recruit starts. It can happen several times in a row. Recruiting several heroes from the *same*
> building is fine.

## TL;DR

- Hero recruitment is a **revive**, and a revive is bookkept on the **player's** revive manager
  (`Player+0x758`), keyed by the `ProductionID` of the production that started it.
- `ProductionUpdateInterface::requestUniqueUnitID` (`0x008A18FA`) mints that id from a counter
  held on the **producer** (`ProductionUpdate` module `+0x30`, seeded to 1). Every building
  therefore mints the same ids: 1, 2, 3, …
- `ReviveMgr::startRevive` (`0x007812B2`) refuses an id another entry already holds — correctly,
  because cancel and complete both find their entry by that id.
- `ProductionUpdate::queueCreateUnit` (`0x008A11D2`) **withdraws the cost before** it calls
  `startRevive`, and its failure edge deletes the queue entry without refunding.
- So the id space is per-building and the check that reads it is per-player. The patch makes the
  mint game-wide: ten bytes replacing ten, plus a four-byte counter in an appended section.

## The path a recruit takes

A `Command = REVIVE` button reaches production through `Object::doCommandButton` (`0x00696FD2`),
whose revive case is at `0x006973CB`:

```
006973ce  prod := producer->getProductionUpdateInterface()      ; 0x0068C327
006973d3  idx  := btn->m_attachedRevivable                      ; CommandButton+0xC0, -1 when unattached
006973e0  if (!prod || idx == -1) return
006973f7  id   := prod->requestUniqueUnitID()                   ; vtable +0x08
00697406  prod->queueCreateUnit(NULL, idx, id, ...)             ; vtable +0x20
```

`getProductionUpdateInterface` walks the object's module list and asks each module's second
vtable (`module+0x0C`, slot `+0x70`) for its production interface; `ProductionUpdate` answers
with the subobject at `module+0x20`, so throughout `queueCreateUnit` `this-0x1C` is the module
data, `this-0x18` the owning `Object`, `this+0x10` the id counter and `this+0x14` the queue
length.

The `UNIT_BUILD` case at `0x006977C5` has the identical shape with `(what, -1, id)`, which is
what makes the argument order readable: `queueCreateUnit` is `ret 0x1C` — seven dwords — and the
callers push four, call `requestUniqueUnitID` for the third, then push three more.

```c
Bool queueCreateUnit(const ThingTemplate *what, Int reviveIndex, ProductionID id, ...);
```

### `ProductionUpdate::queueCreateUnit` (`0x008A11D2`)

```
008a11d8  isRevive := reviveIndex != -1 ; if (isRevive) what := NULL
008a1205  if (TheBuildAssistant->vt[0x64](owner, what, reviveIndex) != 0) return FALSE
008a120c  if (queueLength >= moduleData->maxQueueEntries) return FALSE
008a121b  player := owner->getControllingPlayer()
008a1231  cost := isRevive ? player->reviveMgr->costOf(reviveIndex, owner)   ; 0x00780AD3
008a1257                   : what->costToBuild(player, owner, -1)           ; 0x0073C25F
          ; ---- the loop, once per unit ----
008a1284  if (queueLength >= moduleData->maxQueueEntries) return TRUE
008a12a2  player->money(+0x90)->withdraw(cost, player->stats(+0x3DC), TRUE)  ; <-- MONEY MOVES
008a12ad  player->stats->recordSpend(what, cost)
008a12b2  entry := new ProductionEntry(0x54)
008a12e9  entry->m_productionID(+0x10) := id
008a12f3  if (!isRevive) { ...template path... }
008a1371  else if (!player->reviveMgr->startRevive(reviveIndex, entry->m_productionID, &entry->+0x38))
008a13d8       { delete entry; return FALSE }                                ; <-- NO REFUND
008a13b0  appendToQueue(entry)
```

`Player+0x90` being the `Money` subobject squares with
[`engine-globals.md`](engine-globals.md): its spendable dword is `Player+0x94`, already pinned
from the read side by watching it fall by exactly the amount spent.

**The withdrawal is 310 bytes before the failure edge, and nothing between them can put the
money back.** That is the "takes the money and does nothing" half of the report.

### `ReviveMgr::startRevive` (`0x007812B2`)

The revive manager is `Player+0x758`: a vector of `0xE8`-byte entries between `+0x04` and `+0x08`
(`findByIndex` at `0x007808AB` divides the span by `0xE8`). Two fields matter here — `entry+0xA8`,
the frame the revive started, `-1` when idle; and `entry+0xB4`, the `ProductionID` that started
it, `0` on a fresh entry and `-1` after a cancel.

```
007812bb  if (findByProductionID(id) != NULL) return FALSE     ; 0x007808DB   <-- THE COLLISION
007812ca  entry := findByIndex(reviveIndex)
007812d1  if (!entry) return FALSE
007812ec  if (entry->m_startFrame(+0xA8) != -1) return FALSE   ; already being revived
007812f7  entry->m_productionID(+0xB4) := id
00781303  entry->m_startFrame := TheGameLogic->frame
0078130c  *out := completionFrame(entry)
00781313  return TRUE
```

`findByProductionID` is a linear scan comparing `entry+0xB4` — it has no notion of *which*
building started the revive, because nothing hands it one. The same key drives
`cancelRevive` (`0x00780C64`, which resets `+0xA8` and `+0xB4` to `-1`) and the completion
lookup in `ProductionUpdate` (`0x008A24EF` / `0x008A250A`), so the refusal is right: two live
revives of one player sharing an id would make cancel and complete pick the wrong hero.

## The defect

`requestUniqueUnitID` is ten bytes:

```asm
008a18fa  8b 41 10        mov  eax, [ecx+0x10]      ; ProductionUpdate module +0x30
008a18fd  8d 50 01        lea  edx, [eax+1]
008a1900  89 51 10        mov  [ecx+0x10], edx
008a1903  c3              ret
```

and the constructor (`0x008A17D8`) seeds that field to 1:

```asm
008a180d  33 ff           xor  edi, edi
008a1814  47              inc  edi
008a1841  89 7e 30        mov  [esi+0x30], edi      ; the counter = 1
```

So **the id is unique within one producer and repeats across producers**, while the only
consumer that treats it as a key ranges over one *player's* revives. Every building's first hero
recruit asks for production id 1.

That reproduces the report line by line:

| step | what happens |
|---|---|
| recruit hero A from building A | A mints id 1; `startRevive(0, 1)` finds no entry holding 1; the revive starts and hero A's entry records `+0xB4 = 1` |
| recruit hero B from building B, while A is still coming | B mints id **1** as well; `findByProductionID(1)` finds hero A's entry; `startRevive` returns FALSE **after** the withdrawal |
| click again | B's counter advanced to 2 even though the queue failed, so the retry gets id 2 and works |
| several heroes queued at A | A holds ids 1, 2, 3 …, so B's first three clicks all collide — "it can happen multiple times" |
| several heroes from the *same* building | one counter, distinct ids, never a collision |

Note the entries are **erased** from the revivable list when a recruit completes
(`finishRevive`'s tail at `0x00781722` calls the erase-by-production-id helper at `0x007813FF`),
so an id stops occupying the space once its hero is out. That is why the bug needs the two
recruits to overlap in time, rather than being permanent.

## The fix

Replace the mint with a game-wide counter. Ten bytes for ten, so there is no hook and no cave:

```asm
008a18fa  b8 <counter>    mov  eax, <counter>       ; the appended .prodid section
008a18ff  ff 00           inc  dword [eax]
008a1901  8b 00           mov  eax, [eax]
008a1903  c3              ret
```

The section is four bytes of zero-initialised, writable, **non-executable** data — unlike the
other bundled caves, nothing in it is code.

**Why the mint and not the check.** `startRevive`'s refusal states a real invariant. The two
alternatives both fail on ownership of the write: widening the revive entry to record the
producer as well as the id means changing a structure the savegame carries, and renumbering
inside `startRevive` means writing the new id back through a caller that has already stamped the
old one onto its `ProductionEntry` (`0x008A12E9`, 200 bytes earlier) and has no idea it changed.
Minting a genuinely unique id fixes the cause and leaves every consumer untouched.

**Why post-increment.** The stock counter starts at 1 and is read before it advances; the new one
starts at 0 and is read after. Both mint 1, 2, 3, … — and neither ever mints **0**, which matters:
`0` is what `entry+0xB4` holds on a hero who has never been recruited, so an id of 0 would collide
with every idle hero the player has. `-1` is likewise reserved, by `cancelRevive`.

**The field it stops using is private.** `module+0x30` is written by the constructor and by this
function, and read by nothing else — a scan of every function named in `ProductionUpdate`'s five
vtables finds no other access. After the patch it stays at its constructed 1 and is simply dead.

**`ProductionUpdate` is the only implementer.** `0x008A18FA` appears in exactly one vtable slot in
the image, `0x00C67DB8` — the production interface's `+0x08`. Patching the function covers every
caller, and `apply` asserts that slot still names it before writing.

## Why no refund is added

After this patch, a click cannot reach the withdrawal and then fail. `queueCreateUnit` consults
`TheBuildAssistant`'s vtable `+0x64` (`0x00793ECB`) before the money moves, and that function's
revive answer ends in `BuildAssistant::canMakeUnit` → `ReviveMgr::canRevive(index)`
(`0x00780C46`), which is exactly `findByIndex(index) && entry->+0xA8 == -1`. So `startRevive`'s
other two refusals — an unknown index, and a hero already being revived — are both pre-empted,
including for a second click in the same frame, since orders are applied one at a time. The id
collision was the one refusal that the pre-check could not see, because nothing about a
`ProductionID` is visible until the id has been minted.

That leaves the failure edge at `0x008A13D8` unreachable from a player click rather than merely
rarer, which is why the patch fixes the cause instead of adding a refund that would mask it.

## Determinism

The counter advances once per production request, on the logic thread, driven by the order
stream — so every peer walks the same sequence and mints the same ids. That is the property the
*stock* per-building counters already needed: their ids are compared inside the revive manager,
so a peer that minted a different one would diverge. Moving the state from one dword per producer
to one dword per game does not weaken it; the ten call sites are

| site | caller |
|---|---|
| `0x006973FC`, `0x006977F7` | `Object::doCommandButton` — the REVIVE and UNIT_BUILD cases |
| `0x008A12DE` | `queueCreateUnit`'s own loop, for units past the first |
| `0x0077A824`, `0x0088462B`, `0x008B84EC` | engine production paths (spawn/OCL) |
| `0x008F6AB4`, `0x009A1A5C`, `0x009B901C`, `0x009EDBAC` | AI and script production |

and none is client-side. Nothing in the order stream changes, so replays are unaffected in
shape — but the ids inside a *saved game* are not, see below.

## Scope

**Loading a savegame.** The counter lives in the appended section, which is not part of the save,
so a loaded game starts minting from 1 again while any revive that was in progress when the game
was saved still holds its old id. If one of those old ids is small, one recruit can collide once
and lose its money before the counter passes it. That is the stock bug in a much narrower
window — it needs a save taken mid-recruit, and it clears itself — and closing it means
persisting the counter through `Xfer`, which is a savegame format change. Not attempted.

**Cancelling.** `cancelRevive` resets `entry+0xB4` to `-1`, which no counter value can equal, so
a cancelled recruit frees its slot as before.

**Ordinary unit production is unaffected in behaviour.** It never compared ids across producers;
it just gets larger numbers now.

## Status

**Static-verified, not yet runtime-verified.** The patch applies to a clean `game.dat`, `verify`
passes, and the rewritten function disassembles to the four intended instructions ending exactly
on the boundary of the next function (`0x008A1904`). Confirming in-game that a hero can be
recruited from a second building while the first is still producing is open.
