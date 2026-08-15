# `spawn-union` — make every `SpawnBehavior` answer, not just the first

**Status: implemented as `spawn-union`** ([`../patches/spawn_union.py`](../patches/spawn_union.py)),
applying and verifying against the real `game.dat`. Every address below is from the ROTWK
SAGE-engine `game.dat` build `2.01.2614.37001` (ImageBase `0x400000`), derived statically with
`scripts/pe.py`, and confirmed in a running process - the patch is runtime-verified, and §7
lists the claims the live match settled.

## 1. What the engine does today

`SPAWNS_ARE_THE_WEAPONS` is `KindOf` index **84**. The name table is at `0x00DA0E68`
(`"SPAWNS_ARE_THE_WEAPONS"` at `0x00C16230`, slot 84), the mask lives at **`ThingTemplate+0x108`**
(from the `Object` field-parse table entry at `0x00DA4148`, alongside `CommandSet` `+0x70` and
`Behavior` `+0x2E4`), and `Object+0x04` is the template — so the test compiles everywhere to:

```
mov  eax, [obj+4]                  ; ThingTemplate *
test byte ptr [eax+0x112], 0x10    ; KindOf bit 84
```

There are **eight** such sites: `0x0066BEB8`, `0x00691333`, `0x006C888C`, `0x006C8A2D`,
`0x00745840`, `0x0081DA13`, `0x0081DA5A`, `0x0082D057`. Six of them are immediately followed by a
`call 0x0068C3A3`, and that call is the whole of the problem:

```
0068c3a3  56                 push esi
0068c3a4  8b b1 4c 02 00 00  mov  esi, [ecx+0x24c]      ; the module list
0068c3aa  eb 0f              jmp  .next
0068c3ac  8d 48 0c           lea  ecx, [eax+0xc]        ; module's second vtable
0068c3af  8b 01              mov  eax, [ecx]
0068c3b1  ff 50 78           call [eax+0x78]            ; getSpawnBehaviorInterface()
0068c3b4  85 c0              test eax, eax
0068c3b6  75 09              jnz  .done                 ; <-- first non-NULL wins
0068c3b8  83 c6 04           add  esi, 4
0068c3bb  8b 06     .next:   mov  eax, [esi]
0068c3bd  85 c0              test eax, eax
0068c3bf  75 eb              jnz  .ask
0068c3c1  5e        .done:   pop  esi
0068c3c2  c3                 ret
```

`Object::getSpawnBehaviorInterface` walks the NULL-terminated `BehaviorModule*` array at
`Object+0x24C` (the same list `getProductionUpdateInterface` at `0x0068C327` walks — see
[`live-object-model.md`](live-object-model.md) §5) and **returns on the first module that answers**.
It is 32 bytes, `__thiscall`, no arguments, `ret`; the next function starts at `0x0068C3C3`.

`SpawnBehavior` answers with the subobject at `module+0x20`, whose vtable is **`0x00C58D94`**. Chain
of evidence: registration at `0x00657F5F` pushes `interfaceMask = 0x87` with the name
`"SpawnBehavior"` (`0x00C0BCF4`); the module create fn `0x0064B0EE` allocates `0x64` bytes and calls
the constructor `0x00862606`, which writes `[this] = 0xC58E94`, `[this+0x0C] = 0xC58DD8` (the second
vtable) and `[this+0x20] = 0xC58D94`; slot `+0x78` of `0xC58DD8` is `0x008A18E0`
(`lea eax,[ecx-0xc] / add ecx,0x14 / neg / sbb / and` — "`this` ? `this+0x14` : NULL", and
`(module+0x0C)+0x14 = module+0x20`). Of the 125 second-vtable bases recovered from constructor
`mov [reg+0x0C], imm32` stores, **`0xC58DD8` is the only one with a non-generic slot `+0x78`**, so
`SpawnBehavior` looks like the sole implementer. That is a strong scan, not a proof — a constructor
that sets the pointer some other way would be missed.

## 2. Where it bites

`rohantheodredturm.ini` is the case in hand. `RohanTheodredTurm_Reinforcements` declares two:

```
Behavior = SpawnBehavior ModuleTag_SpawnAttacker       ; 8x IsenfurtWachter_SlavedTheodred
Behavior = SpawnBehavior ModuleTag_SpawnAttackerBigWave ; 16x ...Reinforcement, OneShot = Yes
```

Both **spawn** normally — spawning is each module's own update, and nothing routes it through the
interface. What goes through the interface is everything the *tower* does with its slaves, so the
big wave exists on the map and is never ordered to attack, never counted when the tower asks
whether it can attack a target, and never consulted for the closest slave.

Which module is "first" is INI merge order in `Object+0x24C`: `ModuleTag_SpawnAttacker` is
overridden in place by the child object and `ModuleTag_SpawnAttackerBigWave` is appended, so the
8-unit garrison should win and the 16-unit wave should be inert. **Unverified** — see §7.

Two things this is *not*. It is not fixable by merging the two modules: `SpawnTemplateName` does
take a list (`RohanTheodredTurm_PitchThrowers` uses one), but `SpawnNumber`, `SpawnReplaceDelay`
and `OneShot` are per-module, and `OneShot = Yes` on a subset of a merged list is not expressible.
And it is not only an attack-path defect — see the next section.

## 3. The interface, and what "all of them" has to mean

Interface vtable `0x00C58D94`, 16 slots, `this = SpawnBehavior+0x20`, slave list at `this+0x2C` (a
circular list; each node's `+8` is an `ObjectID` resolved through `TheGameLogic` `0x00DE412C` →
`findObjectByID` `0x00449681`). Thirteen call sites reach it through `0x0068C3A3`; eleven distinct
slots. Argument counts are read off the call sites, which is authoritative here.

| slot | impl | args | reached from | aggregation |
|---|---|---|---|---|
| `+0x04` | `0x00862DAB` | 2 | `0x006938BD` slave death | **broadcast** |
| `+0x08` | `0x0086292C` | 1 (`Coord3D*`) | `0x0081DA1E`, `0x0081DA65`, `0x0082D062` | **min over all** |
| `+0x0C` | `0x008637BE` | 3 | `0x0066BEC3` attack target | broadcast |
| `+0x10` | `0x00863807` | 3 | `0x00772369` attack position | broadcast |
| `+0x18` | `0x008629ED` | 4 | `0x006C8A01` | OR, short-circuit |
| `+0x1C` | `0x00862A4E` | 0 | `0x00691406` | OR, short-circuit |
| `+0x20` | `0x00863850` | 1 | `0x0077205F` | broadcast |
| `+0x24` | `0x008623D6` | 0 | `0x006993EB`, `0x00886B3D` | broadcast (clears `this+0x30`) |
| `+0x28` | `0x00862E4F` | 0 | `0x008569CA` | broadcast |
| `+0x2C` | `0x0086277F` | 0 | `0x00889BC8` | OR (reads `this+0x30`) |
| `+0x30` | `0x0086327C` | 0 | `0x006993EB` | broadcast |

Slots `+0x00`, `+0x14`, `+0x34`, `+0x38`, `+0x3C` are never reached through this getter.

Two rows deserve their own paragraph.

**`+0x04` is an existing bug, not just a missing feature.** `0x006938BD` takes a dying slave, finds
its spawner by `ObjectID` (`[slave+0x78]`), and reports the death to the spawner's *first* spawn
behavior. `onSpawnDeath` (`0x00862DAB`) opens with a `find` over its own slave list
(`0x0076EC18`) and, when the id is not in it, returns having done nothing — no list removal, no
`dec [this+0x34]` live count, no respawn timer armed at `this+0x28`. So today a second
`SpawnBehavior`'s slaves die into a hole. Broadcasting is the correct fix *and* is safe, because
every implementation already filters by membership.

**`+0x08` cannot be "first non-NULL".** `getClosestSlave` (`0x0086292C`) keeps a running minimum of
`0x0066137C` (distance from an object to the passed `Coord3D`), so a union has to re-run that
comparison across each behavior's answer or it silently returns "closest slave of whichever module
came first", which is the bug with extra steps.

## 4. Option A — an aggregating proxy (built)

One edit: a 5-byte `jmp` over the head of `0x0068C3A3` into a cave. The cave re-walks
`Object+0x24C`, counts the modules answering `+0x78`, and:

- **0** → return NULL (stock);
- **1** → return it (stock, and this is every object in the game bar a handful — the common path
  costs one extra compare);
- **2+** → return a proxy: `{void *vtbl; Object *obj;}` living in the cave, with a 16-slot vtable
  whose stubs re-walk the module list and forward per the table above.

This works because every caller uses the pointer the way the disassembly shows —
`mov edx,[eax] / mov ecx,eax / call [edx+N]` — and none of the thirteen stores it past its own
basic block.

What it cost: **one 5-byte edit and a `0x4A7`-byte cave** — 13 stubs, 3 `int3` fillers, a 16-slot
vtable, the ring, and the entry walk.

Four things it had to get right, and how:

1. **Reentrancy.** `orderSlavesToAttackTarget` runs slave AI that can re-enter
   `getSpawnBehaviorInterface` (the slave's own attack checks at `0x006C8652` do). A single static
   proxy would be clobbered mid-call, so the cave holds a **ring of eight** with a rotating index;
   the proxy carries no state but the `Object *`, so a nested call simply takes the next slot.
2. **`ret n` per stub.** Each stub cleans the same stack its real method does: `+0x04`→8,
   `+0x08`→4, `+0x0C`/`+0x10`/`+0x14`→0xC, `+0x18`→0x10, `+0x00`/`+0x20`→4, the rest 0. Read off
   the call sites and cross-checked against each implementation's own `ret`.
3. **The forwarding displacement.** Every stub saves `esi` and `edi` whether or not it uses both,
   so one rule covers all of them: pushing the arguments back out in reverse order makes each
   argument's index plus its push count constant, which is why the engine's own forwarding loops
   repeat a single `push dword [esp+d]`. The `_arg_displacement` arithmetic is asserted per slot
   in the tests, because nothing downstream would notice it being off by a dword.
4. **No short-circuit.** Every predicate here is pure — each only reads its own slave list — but
   all of them are asked regardless, which costs two indirect calls on an object with two
   behaviors and removes the purity assumption entirely. Note the stock implementations abort
   their *own* slave scan on certain intermediate results (`+0x18` returns FALSE outright when
   `0x0068B5FA` answers 2 or 3), so OR-ing per behavior is a faithful generalization of "any slave
   can" and not byte-identical to what one merged list would have produced.

The proxy also fixes `+0x04` for free, and applies to all thirteen call sites rather than only the
`SPAWNS_ARE_THE_WEAPONS`-gated ones — which is right: nothing about the first-only rule is specific
to that `KindOf`.

The build fingerprint is four independent checks, all of which must pass before a byte is written:
the getter's own 32 bytes (which carry `0x24C`, `+0x0C` and `+0x78` as immediates, so one
comparison pins every constant the cave reuses), `SpawnBehavior`'s second-vtable answer at `+0x78`,
all sixteen entries of the interface vtable, and the distance helper's prologue.

## 5. Option B — patch the gated call sites

Leave `0x0068C3A3` alone and rewrite the six `KindOf`-gated sites (`0x0066BEC3`, `0x0081DA1E`,
`0x0081DA65`, `0x0082D062`, `0x006C8A01`, `0x00691406`) to loop the module list themselves. More
surgical in blast radius, worse in every other way: six caves instead of one, each with the host
function's own register and stack discipline, six sites' original bytes to fingerprint, and it
leaves `onSpawnDeath` broken. Only reach for it if §7 turns up a caller that cannot tolerate a
synthetic `this`.

## 6. Composition and reach

- One 5-byte edit at `0x0068C3A3`, plus an `allocate_section` cave (`.spwnun`) per the
  [composition contract](../patcher.py). No bundled patch touches `0x0068C3xx` or the
  `SpawnBehavior` vtables; `banner-filter` is the nearest neighbour conceptually and edits
  `0x0089Axxx`.
- **This is a simulation change.** Unlike `replay-outcome` / `skirmish-replay`, it changes what
  units do, so it must be on **every peer**, and replays recorded against it will not play back on
  a stock build. The proxy is deterministic — module list order is INI order, identical everywhere.
- No struct grows, no savegame surface: the proxy is never stored in an object, so nothing new
  needs `Xfer`.
- `ini_surface` is `STOCK`: no new field, no new token. The patch changes what existing INI means,
  which `sage_ini` has no way to express and does not need to.

## 7. What is checked, and what still is not

Two of the four opened here are closed, both statically.

- **Closed: `+0x28` and `+0x30` do not touch shared state.** They were read here only as far as
  their first loop, which is not enough to broadcast to safely. Read to the end: `+0x28`
  (`0x00862E4F`) walks each of *its own* slaves, finds that slave's own module answering second-
  vtable slot `+0x68`, and calls its `+0x04` with the spawner; `+0x30` (`0x0086327C`) walks
  `this+0x28` — the pending-respawn list, not the slave list — compares each entry's `+8` against
  the current frame (`TheGameLogic+0x40`) and calls `0x00862A88` on the module when one is due.
  Neither reaches past its own behavior, so broadcasting cannot double-apply.
- **Closed: `SpawnBehavior` is the only implementer of slot `+0x78`.** Two independent scans, and
  the intersection is a single vtable. The constructor scan (`mov [reg+0x0C], imm32` over `.text`,
  125 bases) and a window scan over `.rdata`/`.data` for 46-slot runs of mostly-generic stubs agree
  on exactly `0x00C58DD8`. Still not a proof — a constructor that sets the pointer some other way
  would be missed by both — but it is now two methods rather than one.

Two were settled by the live match that runtime-verified the patch, by this procedure.

1. **That the second behavior is actually the inert one.** Attach to a live match with a built
   `RohanTheodredTurm_Reinforcements`, walk `Object+0x24C`, and match `[module+0x00]` against
   `0xC58E94` to find both `SpawnBehavior`s in list order (the technique from
   [`live-object-model.md`](live-object-model.md) §5 — match the vtable, do not call it). Confirms
   both the merge order and that two modules really are present.
2. **That the big wave's slaves are unordered without the patch, and ordered with it.** Same
   session: give the tower a target and check which slaves acquire it.

## 8. Where it lives

Patch `spawn-union`, in [`../patches/spawn_union.py`](../patches/spawn_union.py) as
`SpawnUnionPatch`, registered in [`../registry.py`](../registry.py), with the stubs asserted by
disassembly in [`../../tests/sage_patch/test_spawn_union.py`](../../tests/sage_patch/test_spawn_union.py).
No parameters: the first-only rule is either in force or it is not.
