# `castle-unpack-clearance` — stop a castle unpack silently dropping structures

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), recovered **statically**
2026-09-07 against this repo's `game.dat`, which `sage-patch sagepatch` reports as carrying no
known patch; every site cited is stock `.text`.

**Status: implemented as `castle-unpack-clearance`**
([`../patches/castle_unpack_clearance.py`](../patches/castle_unpack_clearance.py)), applying and
verifying against the real `game.dat`. §4 is the design space it was chosen from and §4.2 is what
was built; §5 records the choice and §6 what is and is not tested. **Not runtime-verified** — the
disassembly and the tests are two readings of the same evidence, and only the running game is a
third.

## TL;DR

- Both symptoms are **one gate**. `CastleBehavior`'s per-entry builder calls the build-legality
  test at `0x00798973` and, on any non-zero answer, **abandons that entry for good**
  (`0x0079897A` → `0x00798849`). There is no retry, no nudge, no diagnostic; the caller passes the
  resulting `NULL` to `onStructureBuilt`, which null-checks and does nothing. A camp comes up with
  a hole in it and the game never mentions it.
- **An object in the way is a veto.** Flag bit `0x4` in the `push 5` at `0x00798968` turns on
  `BuildAssistant::isLocationClearOfObjects`, which answers "blocked" for anything that is not
  `SHRUBBERY`, `CLEARED_BY_BUILD`, `INERT` or `AIRCRAFT` — so a unit standing on the spot, a rock,
  a neutral prop or somebody's building each delete a structure from the prefab.
- **Rotation is a veto by proxy.** The prefab is placed through the flag's own transform matrix
  (`0x0079889E`–`0x0079891E`), so the layout itself is rigid and rotating it cannot make siblings
  collide. What rotation changes is the *ground and the scenery the camp now sits on*: flag bit
  `0x1` in the same `push 5` runs the footprint flatness and pathfind-cell tests, and a camp turned
  30° samples different terrain and sweeps different props. Hence "risks not all the objects
  spawning" — it is terrain- and map-dependent, not deterministic.
- **The keep is already exempt.** `0x00798951` skips the whole gate when the entry's template is
  `KindOf COMMANDCENTER`. So the fortress always appears and only the rest of the camp is at risk,
  which is exactly the shape of the reported bug.
- The cheapest fix is **one byte**: `6a 05` → `6a 00` at `0x00798968`. The map-bounds test inside
  the legality function is unconditional and survives that, so nothing lands off the map.
- The fix that was built is **one hook over the 5-byte `call`**, running the stock test and then a
  second test with flags `0`; accept when the second one passes, refuse when it does not. That
  keeps every unconditional safety test in force and needs no new logic.
- **Logic-side.** Which structures exist changes object ids and the frame CRC, so every peer needs
  the same binary and replays will not play back on a stock one.

## 1. The unpack, end to end

`CastleBehavior::unpack` is `0x0079BE6A` (`ret 4`). Reached from `MSG_CASTLE_UNPACK` (`0x43D`) and
from the initiate/timer path; see [`ai-plot-builder.md`](ai-plot-builder.md) §2 for the message
side and [`foundation-rebind.md`](foundation-rebind.md) §1 for what the flag object is.

| step | address | what |
|---|---|---|
| explicit-object path | `0x0079BEB1`–`0x0079BED9` | when `module+0x98` names a template, build **that one object** and skip both loops |
| **the structure loop** | `0x0079BF05` → `0x0079B903` | walk the prefab's entries and build each one |
| the second loop | `0x0079BF16` → `0x0079B881` | the same walk over a second entry list, feeding `0x0079AB88` |
| stamp the members | `0x0079BF76`, `0x0079BFEA` | write each member's `CastleMemberBehavior` `+0x14` / `+0x18` (castle centre id, keep id) |
| hide the flag | `0x0079C07E` | `setStatus(UNSELECTABLE)` and the fade |

**Only the structure loop is affected.** The explicit-object path (`0x0079B98B`) reaches the
foundation interface's create slot directly and asks no legality question at all, so a plot built
through `CASTLE_UNPACK_EXPLICIT_OBJECT` — Edain's route, per
[`ai-plot-builder.md`](ai-plot-builder.md) §5 — already spawns unconditionally. Both defects are
specific to unpacking a **prefab camp or castle**.

The structure loop at `0x0079B903` is nine instructions of substance:

```asm
0079b918  call 0x799021                  ; the prefab name for this faction
0079b927  call 0x72bb37                  ; construct a 0x80-byte entry on the stack
0079b939  .next:
0079b943  mov  ecx, esi
0079b946  call 0x7987ee                  ; build this entry  -> Object * or NULL
0079b94b  push eax
0079b94e  call 0x79ac19                  ; CastleBehavior::onStructureBuilt(that)
0079b95b  mov  ecx, [0xde77a0]           ; TheSidesList
0079b962  call 0x72d72f                  ; getEntry(name, index, &entry) -> bool
0079b969  jne  .next
```

`0x0072D72F` looks the prefab up by name in the map's own castle-template table (`TheSidesList
+0x24`) and copies out entry *index* from a vector of **0x80-byte** records (`sar edx, 7`). The
fields the builder reads are the template name at `+0x00`, the offset vector at `+0x0C`/`+0x10`/
`+0x14`, and the entry angle at `+0x20`.

`onStructureBuilt` (`0x0079AC19`) opens with `test edi, edi / je 0x79ADD9`, so handing it the
`NULL` from a refused entry is safe and silent. **A dropped structure produces no error, no log
line and no retry, and the loop moves straight to the next entry.**

## 2. The per-entry builder, and the gate

`0x007987EE`, one caller (`0x0079B946`). `edi` is the module, `[edi+8]` the camp flag object,
`[edi+4]` the module data, `[ebp+8]` the entry.

### 2.1 Placement is a rigid transform

```asm
00798896  mov   eax, [edi+8]             ; the flag object
00798899  movss xmm4, [ebx+0x10]         ; entry.offset.y
0079889e  movss xmm0, [eax+0xc]          ; flag transform m[0][1]
...
0079891e  addss xmm2, [eax+0x34]         ; + m[2][3]
00798923  movss [ebp-0x34], xmm0         ; world position
00798937  movss xmm1, [eax+0x44]         ; the flag's angle
0079893c  addss xmm1, xmm0               ; + entry.angle
0079894c  call  0x644fd0                 ; normalise
```

`Object+0x08` is a 3×4 world matrix and `Object+0x44` the facing, so the prefab is placed through
the flag's full transform. **Rotation is applied correctly and rigidly**: every offset and every
facing turns together, so relative clearances inside the camp are preserved exactly. Nothing about
rotation can make two camp structures collide with each other.

### 2.2 Three template filters, then the gate

| address | test | effect |
|---|---|---|
| `0x00798850` | `KindOf OPTIMIZED_PROP` | entry skipped entirely, always |
| `0x00798859` | `KindOf WALK_ON_TOP_OF_WALL` | sets `module+0x44` |
| `0x0079887C` | `FilterValidOwnedEntries` (module data `+0x30`) | on failure the structure is given to the neutral player instead of the unpacker, **not** dropped |
| **`0x00798951`** | **`KindOf COMMANDCENTER`** | **skips the legality gate** — the keep is exempt |

and then the gate itself:

```asm
00798951  test byte [esi+0x10a], 2       ; COMMANDCENTER
0079895c  jne  0x798980                  ; the keep: build it unconditionally
0079895e  mov  eax, [edi+8]
00798967  push eax                       ; the flag object (the "builder")
00798968  push 5                         ; <-- the flags word
0079896a  push ecx
0079896b  fstp [esp]                     ; the angle
0079896e  push esi                       ; the template
0079896f  lea  eax, [ebp-0x34]
00798972  push eax                       ; the position
00798973  call 0x797a96                  ; the legality thunk
00798978  test eax, eax
0079897a  jne  0x798849                  ; non-zero -> esi = 0, return NULL
```

`0x00797A96` is a five-line thunk: it ORs `0x100` into the flags word and forwards to
`TheBuildAssistant` (`0x00DE8200`) vtable `+0x44`, which is
`BuildAssistant::isLocationLegalToBuild` at **`0x00796810`**. So the castle unpack asks with
flags `0x105`.

### 2.3 What the flags word buys, and what it cannot buy back

Reading `0x00796810`, the answer is a small integer, `0` meaning legal. Each non-zero code comes
from exactly one test, and most tests are gated on a flag bit:

| bit | test | address | refusal |
|---|---|---|---|
| — | position inside the map's playable extent | `0x0079683D` | `6` |
| `0x1` | pathfind layer under the centre cell | `0x00796AB6` | `6` |
| `0x1` | footprint flatness, twice, against `GlobalData+0xA70` | `0x00796B70`, `0x00796BE4` | `5`, or `6` if a cell is flagged bad |
| `0x1` | slope ratio, for `KindOf PORT` | `0x00796C0B` | `6` |
| `0x2` / `0x8` | builder-relationship test | `0x00796A46` | `2` |
| **`0x4`** | **`isLocationClearOfObjects`** | `0x007968FD` | **`8`** |
| `0x20` | a second `isLocationClearOfObjects` pass | `0x0079693B` | `8` |
| — | `KindOf CANNOT_BUILD_NEAR_SUPPLIES` proximity | `0x00796942` | `3` |
| — | `KindOf WALL_HUB` anchor proximity | `0x00796C66` | `9` |

The castle unpack sets `0x1` and `0x4`. **The three unflagged tests fire regardless of what the
flags word says** — which is what makes the one-byte fix safe: map bounds keep their veto.

### 2.4 What counts as "an object in the way"

`isLocationClearOfObjects` is vtable `+0x48`, `0x00796D37`. It builds the template's geometry at
the requested position **and angle** (`0x007939DF`), queries `ThePartitionManager` over a circle of
`template->geometry.majorRadius + GlobalData+0x1220`, and for each candidate asks the predicate at
`0x007940A6`:

```c
if (!obj)                            return false;   // blocks
if (tmpl->isKindOf(INERT))           return false;   // ignored elsewhere, see below
if (tmpl->isKindOf(TAINT))           return false;
if (tmpl->isKindOf(SHRUBBERY))       return true;    // ignorable
if (tmpl->isKindOf(CLEARED_BY_BUILD))return true;    // ignorable
return obj->[0x458] & 1;
```

plus two rejections in the caller: `KindOf AIRCRAFT` (`0x00796E80`) and `KindOf INERT`
(`0x00796E8D`) are skipped. So trees, bushes and props authored with `CLEARED_BY_BUILD` already
step aside. **Everything else blocks**: any ground unit, any structure, any wall, any non-inert
rock or ruin, any plot flag. There is no clearing step anywhere on this path — `CLEARED_BY_BUILD`
is consulted only to *ignore* an object, never to destroy one.

## 3. So why does rotating the camp lose structures

Three facts settle it.

1. **The layout is rigid** (§2.1). Rotation cannot change any distance inside the prefab.
2. **The gate is evaluated in world space, per entry** (§2.2), against the terrain and the object
   population that happen to be under each rotated position.
3. **A refusal is permanent and silent** (§1).

So rotating a camp does not break the camp; it moves the camp's footprints onto ground and
scenery the prefab was never authored against. Two of the four live tests are the ones that then
fire:

- **flatness and cell type** (`0x1`). A camp turned any amount sweeps its buildings over a
  different patch of terrain. Anything steeper than `GlobalData+0xA70` across a footprint, or a
  centre cell whose pathfind layer is not the plain one, is a refusal.
- **objects** (`0x4`). The rotated footprints sweep over different map scenery, and any of it that
  is not `SHRUBBERY`/`CLEARED_BY_BUILD`/`INERT` refuses.

That is also why it presents as a risk rather than a rule: it depends on the map under the camp,
so the same rotation is fine in one spot and drops three buildings in another.

One residual that rotation does **not** explain but is worth knowing: `KindOf WALL_HUB` entries
have their own unflagged veto (code `9`, `0x00796C66`), and a camp whose walls are hubs can lose
them for a reason no flags word suppresses. Not investigated further.

## 4. What a fix looks like

Three shapes, cheapest first; §4.2 is the one that was built. All of them live inside
`CastleBehavior::buildCastleMember`; none touches `BuildAssistant`, so nothing else in the game
changes behaviour.

### 4.1 One byte: relax the flags word

`6a 05` → `6a 00` at `0x00798968`.

- Fixes both reports completely. Terrain stops vetoing, objects stop vetoing.
- Map bounds, `CANNOT_BUILD_NEAR_SUPPLIES` and `WALL_HUB` spacing keep their veto (§2.3), so
  nothing lands off the map.
- **Cost:** one byte, no cave, no INI, trivially composable with everything.
- **Risk:** a structure can now materialise on top of whatever was standing there. The blocker is
  not destroyed or pushed; a unit ends up inside a building and a pre-placed prop ends up inside a
  wall. On the maps this is meant for — a camp the mod placed itself — the blocker is usually
  scenery, so this is cosmetic. It is not obviously fine when the blocker is a live unit.
- Intermediate variants: `6a 01` keeps the terrain test and drops only the object veto (report 2
  alone); `6a 04` does the reverse.

### 4.2 Built: hook the call, ask twice

Replace the five bytes of `call 0x797a96` at `0x00798973` with a `call` into a cave that:

1. forwards the five arguments to the stock thunk with the caller's own flags word, `5`;
2. returns that answer when it is `0`;
3. otherwise calls the thunk **again with flags `0`** and returns *that* answer.

The second call runs only the three unflagged tests, so the meaning is exactly "refuse only for a
reason the flags word never controlled". Behaviour is identical to §4.1 for the two reported
defects, and identical to stock for off-map, supply-proximity and wall-hub refusals — but it says
so structurally instead of relying on the reader knowing which tests are unflagged.

- **Cost:** as built, a `.cstunp` cave of `0x36` bytes allocated with `allocate_section`, and the
  five hooked bytes. The hook repoints the `call`'s **target** rather than displacing the `call`,
  so the cave is entered exactly as the thunk was and ends in the same `ret 0x14` — a callee, not a
  jumped-to fragment, which is what keeps the builder's stack balanced.
- **Risk:** the same overlap risk as §4.1, and nothing more.

### 4.3 With clearing, and an INI keyword

On top of §4.2, when the first answer is `8` (objects), sweep the footprint through
`ThePartitionManager` and remove what may be removed before accepting — the natural policy being
"destroy anything not `IMMOBILE`, refuse if a real structure is there". This is the only option
that leaves a clean camp rather than an overlapping one.

- **Cost:** materially more cave, a partition query and a `destroyObject` loop, and a policy
  decision about enemy units standing on a camp being unpacked. This is a follow-up, not part
  of a first cut.
- An INI surface is affordable if wanted: `CastleBehavior`'s module data is `0x78` bytes with the
  last named field at `+0x75`, so **`+0x76` and `+0x77` are free** and a new `Bool` keyword needs
  no growth of the struct — only a relocated, extended copy of the field-parse table. A
  Worldbuilder twin would be needed for the editor to parse the same keyword (see the README's
  note on twins).

## 5. What was built

§4.2, as `castle-unpack-clearance`: default-on, no INI, no parameters. It is small, it is honest
about which vetoes it drops, and it addresses both reports. §4.3 is left as a follow-up, because
"what should happen to the thing that was in the way" is a design question and not a bug.

The cave, from the patched binary:

```asm
00ed3000  55            push ebp
00ed3001  8bec          mov  ebp, esp
00ed3003  ff7518        push [ebp+0x18]        ; the flag object
00ed3006  ff7514        push [ebp+0x14]        ; the caller's own flags word
00ed3009  ff7510        push [ebp+0x10]        ; the angle
00ed300c  ff750c        push [ebp+0x0c]        ; the template
00ed300f  ff7508        push [ebp+0x08]        ; the position
00ed3012  e87f4a8cff    call 0x797a96          ; the stock question
00ed3017  85c0          test eax, eax
00ed3019  0f8413000000  je   0xed3032          ; legal: that is the answer
00ed301f  ff7518        push [ebp+0x18]
00ed3022  6a00          push 0                 ; only the tests no flag controls
00ed3024  ff7510        push [ebp+0x10]
00ed3027  ff750c        push [ebp+0x0c]
00ed302a  ff7508        push [ebp+0x08]
00ed302d  e8644a8cff    call 0x797a96
00ed3032  5d            pop  ebp
00ed3033  c21400        ret  0x14
```

If the diagnosis itself is ever in doubt, §4.1 remains a one-byte experiment that answers it in a
single match.

## 6. Testing

- **Static — done.** [`tests/sage_patch/test_castle_unpack_clearance.py`](../../tests/sage_patch/test_castle_unpack_clearance.py)
  disassembles the cave back and asserts the calling convention, that the first ask is the stock
  question bit for bit, that the retry differs in exactly one dword, and that the retry is reached
  only on a refusal. It fingerprints seven windows the patch does not rewrite — the keep exemption,
  the argument setup, the refusal edge, the thunk, both flag gates, and the `.rdata` vtable slot
  that names `0x00796810` — and runs the apply / verify round-trip on a synthetic image, so the
  suite needs no `game.dat`. Apply and verify were also run against the real binary.
- **Live, report 2.** Place a camp flag, walk a battalion onto a spot the prefab wants, unpack.
  Stock drops that building; patched builds it.
- **Live, report 1.** Same camp on broken ground, unpacked at 0° and at 45°; count the structures.
  Stock loses some at 45° and none at 0°; patched matches at both. `sage_live info`'s object census
  is the cheap way to count without eyeballing.
- **Regression.** Unpack a stock RotWK camp on a stock map at its authored angle and confirm the
  census is unchanged — this patch must be a no-op wherever the prefab already fits.

## 7. Still unknown

- The `KindOf WALL_HUB` refusal (code `9`, `0x00796C66`) and what `0x0073CDD8` returns for a wall
  hub. If a rotated camp loses walls specifically, this is where to look next, and no flags word
  suppresses it.
- `Object+0x458 & 1`, the last clause of the ignorable-object predicate (`0x007940DD`).
- Whether the second entry loop (`0x0079B881` → `0x0079AB88`) can drop entries the same way. It
  does not go through `buildCastleMember` and was not read.
- `FACE_AWAY_FROM_CASTLE_KEEP` (`0x008587EF`) overrides the computed angle from the castle centre,
  gated on `DisableStructureRotation` (module data `+0x74`, read at `0x0085887E`). During an unpack
  the flag's own `CastleMemberBehavior` ids are still unset — they are stamped after the build loop
  (§1) — so the override appears to be inert for the unpack itself and live only for structures
  built on plots later. Not confirmed at runtime.

## Appendix: addresses

| what | address |
|---|---|
| `CastleBehavior::unpack` | `0x0079BE6A` |
| … the structure loop / the second loop / the explicit-object build | `0x0079B903` / `0x0079B881` / `0x0079B98B` |
| `SidesList::getCastleTemplateEntry` (entries are `0x80` bytes) | `0x0072D72F`, `TheSidesList` `0x00DE77A0` |
| the prefab-name lookup (`CastleToUnpackForFaction`, module data `+0x68`) | `0x00799021` → `0x00798F70` |
| **`CastleBehavior::buildCastleMember`** | **`0x007987EE`** |
| … `OPTIMIZED_PROP` skip / `WALK_ON_TOP_OF_WALL` / `FilterValidOwnedEntries` | `0x00798850` / `0x00798859` / `0x0079887C` |
| … the world transform / the angle sum | `0x0079889E`–`0x0079891E` / `0x00798937` |
| … **the `COMMANDCENTER` exemption / the flags word / the call / the refusal** | **`0x00798951` / `0x00798968` / `0x00798973` / `0x0079897A`** |
| … the refusal target (`esi = 0`, return `NULL`) | `0x00798849` |
| the legality thunk (ORs `0x100`, forwards to vtable `+0x44`) | `0x00797A96` |
| `BuildAssistant::isLocationLegalToBuild` | `0x00796810` (vtable `0x00C307D8` `+0x44`) |
| `BuildAssistant::isLocationClearOfObjects` | `0x00796D37` (vtable `+0x48`) |
| the ignorable-object predicate | `0x007940A6` (a second copy at `0x008582A5`) |
| the footprint sampler (rotation-aware, `sinf`/`cosf` at `0x00A3CF84`/`0x00A3CF90`) | `0x00793A6E` |
| the foundation interface's create slot, and the object creator behind it | `0x00859198` (vtable `0x00C30DE8` `+0x10`) → `0x00858701` (`+0x1C`) |
| `CastleBehavior::onStructureBuilt`, and its `NULL` guard | `0x0079AC19`, `0x0079AC2F` |
