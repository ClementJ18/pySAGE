# A resource spot that pays without levelling its building — reverse-engineering notes

The RE behind [`patches/terrain_resource_exp.py`](../patches/terrain_resource_exp.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-02.

## The gap

`TerrainResourceBehavior` is the module on a claimed resource spot. Once the object is activated it
wakes every `IncomeInterval` frames, computes an income, deposits it into the owning player's purse
— and then hands the **same number** to the object's `ExperienceTracker` as experience points. A
resource building therefore levels up purely by existing, at a rate set by how much money it makes,
with no way for a mod to separate the two.

The engine already knows this is a thing a mod wants to turn off. The sibling module
`AutoDepositUpdate` — the other "this structure pays you on a timer" module — ships a stock
`GiveNoXP` boolean for exactly this, and its update gates the experience grant on it while leaving
the deposit untouched (§3). `TerrainResourceBehavior` has the same code shape and no such field.

So this is not a new mechanism, and not a new name either. It is the field the engine gave one of
the two income modules and not the other, reproduced on the second one with the first one's own
gate and the first one's own keyword.

## TL;DR

- `TerrainResourceBehavior::update` (`0x008854D3`) ends by handing the integer it just deposited to
  the building's `ExperienceTracker` (`0x0088573C`-`0x00885765`). Experience per tick **equals**
  money per tick, and no INI field separates them.
- `AutoDepositUpdate` gates the identical block on a stock `GiveNoXP` boolean
  (`0x0089DD16`-`0x0089DD1D`). The patch reproduces that gate instruction for instruction.
- **`ModuleData+0x16` and `+0x17` are alignment padding** — two `Bool`s at `+0x14`/`+0x15`, then a
  4-byte `KindOfFilter` that must start at `+0x18`. A ninth `Bool` fits with **no growth**:
  `sizeof` stays `0x24`.
- The default costs **no bytes**: the constructor's two `Bool` stores rewrite into
  `and dword [esi+0x14], 0` plus the same `Visible` store, eight for eight, and the `and` clears
  the new field on its way past.
- The field-parse table has **exactly one reference** in the whole image and is read through its
  NULL terminator rather than a count, so relocating it to fit a ninth row is one 4-byte repoint
  with **no bound to raise anywhere**.
- Three edits, one `0xC5`-byte `.trexp` cave. **Every peer needs the patched binary**, and the
  keyword will not load on one without it — see §5.

## 1. Anatomy

### 1.1 Registration and the ModuleData

`addModule` (`0x006570FE`) registers the module from `0x0064BF55` (instance factory) /
`0x0064BF8D` (ModuleData factory), interface mask `0xB`.

| what | address |
|---|---|
| `ModuleData` ctor | `0x0088525D` |
| `ModuleData` `sizeof` | `0x24` |
| `buildFieldParse` | `0x008852B8` |
| field-parse table | `0x00C5FD78` |
| behaviour ctor | `0x008852C9` (`sizeof` `0x30`) |
| `update` | `0x008854D3` (slot 0 of the `+0x10` vtable `0x00C5FBCC`) |

The eight stock fields, read out of the table at `0x00C5FD78` (16-byte stride
`{const char *name, parseFn, userData, offset}`, NULL-terminated at `0x00C5FDF8`):

| keyword | parse fn | type | ModuleData offset |
|---|---|---|---|
| `Radius` | `0x0042ED00` | Real | `+0x08` |
| `MaxIncome` | `0x0042EC5E` | Int | `+0x0C` |
| `IncomeInterval` | `0x0073A429` | Duration | `+0x10` |
| `HighPriority` | `0x0042E558` | Bool | `+0x14` |
| `Visible` | `0x0042E558` | Bool | `+0x15` |
| `UpgradeMustBePresent` | `0x0076392F` | KindOfFilter | `+0x18` |
| `Upgrade` | `0x0073AF89` | UpgradeTemplate | `+0x1C` |
| `UpgradeBonusPercent` | `0x0042EEFA` | Percent | `+0x20` |

**`+0x16` and `+0x17` are padding.** Two `Bool`s land at `+0x14`/`+0x15`, the next field is the
4-byte `KindOfFilter` at `+0x18`, and `sizeof` is `0x24` — the two bytes between them are alignment
slack that nothing reads and the constructor never writes. A ninth `Bool` field costs **no growth
of the struct**, which removes the whole class of work a wider `ModuleData` would bring (the
factory's `push 0x24` at `0x0064BF99`, and every copy of the size the allocator sees).

### 1.2 What the constructor writes

```
00885275  83 66 0c 00        and   dword [esi+0x0c], 0     ; MaxIncome = 0
00885279  83 4e 10 ff        or    dword [esi+0x10], -1    ; IncomeInterval = -1
00885280  c7 06 c8 fc c5 00  mov   dword [esi], 0xc5fcc8   ; vtable
00885286  f3 0f 11 46 08     movss dword [esi+0x08], xmm0  ; Radius = 0
0088528b  c6 46 14 00        mov   byte  [esi+0x14], 0     ; HighPriority = No
0088528f  c6 46 15 01        mov   byte  [esi+0x15], 1     ; Visible = Yes
```

`operator new(0x24)` at `0x0064BF9B` does not zero the block, so a field the constructor does not
write holds heap garbage. A new field at `+0x16` therefore needs an explicit initialiser — its
default is not free. §2.1 buys it for zero bytes.

### 1.3 `update`, and where the experience comes from

`update` (`0x008854D3`) is reached with `ebx` = the `+0x10` sub-object, so `[ebx-0x0C]` is the
`ModuleData` and `[ebx-0x08]` the `Object`; it caches the `ModuleData` in `[ebp-0x18]` at
`0x008854EF` and that slot is live for the whole body.

1. **First wake** (`ModuleData+0x28` still 0): register with `TheGameLogic`'s terrain-resource
   registry (`[0x00DE412C]+0x170`, `0x0075BDC2`, taking `Radius` / `Visible` / `HighPriority`),
   mark registered, and — if `+0x29` is still set, which the behaviour ctor leaves it at — return
   `0x3FFFFFFF` and sleep. `0x008853A0` is what clears `+0x29` and wakes the module when the spot
   is claimed.
2. **Every wake after that**: resolve the controlling player (`0x0068B678`), apply the
   `Upgrade` / `UpgradeMustBePresent` bonus (`UpgradeBonusPercent`, `0x006AC2AF` + `0x006ABD0B`),
   apply the object bonus (`0x0068C82D`, bonus id `0xD`) and the difficulty/handicap curve read off
   the player template at `player+0x34 → +0x1C8/+0x1CC`.
3. `income = MaxIncome × <accumulator +0x2C> × <object bonus> × <upgrade bonus>`, floored to an
   integer in `ebx` (`0x00885650`-`0x00885675`).
4. If `ebx > 0`: rescale by the handicap curve, clamp to at least 1, **deposit** it
   (`0x007B18B8`, `player+0x90`), and put a floating `+N` on screen.
5. **Grant experience** — the block this patch gates:

```
0088573c  8b bf 6c 02 00 00  mov  edi, [edi+0x26c]   ; Object::m_experienceTracker
00885742  85 ff              test edi, edi
00885744  74 24              je   0x88576a
00885746  8b cf              mov  ecx, edi
00885748  e8 d5 7b f1 ff     call 0x79d322           ; ExperienceTracker::isTrainable
0088574d  84 c0              test al, al
0088574f  74 19              je   0x88576a
00885751  6a 00              push 0
00885753  6a 01              push 1
00885755  6a 01              push 1
00885757  6a 01              push 1
00885759  51                 push ecx
0088575a  f3 0f 2a c3        cvtsi2ss xmm0, ebx      ; ebx = the money just deposited
0088575e  8b cf              mov  ecx, edi
00885760  f3 0f 11 04 24     movss dword [esp], xmm0
00885765  e8 c9 80 f1 ff     call 0x79d833           ; ExperienceTracker::addExperiencePoints
0088576a  8b 45 e8           mov  eax, [ebp-0x18]
0088576d  8b 40 10           mov  eax, [eax+0x10]    ; sleep = IncomeInterval
```

`ebx` is the deposited amount: experience granted per tick **equals** money produced per tick.

Two details worth having on record. The `jle` at `0x0088567A` skips the deposit when the income
comes out ≤ 0 but still falls into this block, so a zero-income tick calls
`addExperiencePoints(0.0f, …)` on stock — gating the block also removes that call. And
`0x0088573C` is itself a jump target (from that `jle`), which is what makes hooking *at* it, rather
than after it, cover both paths with one edit.

`Object+0x26C` is the `ExperienceTracker`: the accessor `mov eax, [ecx+0x26c] ; ret` lives at
`0x008D7C63`, the field is written at `0x008D7C35`, and the pair
`[obj+0x26C]` → `isTrainable` → `addExperiencePoints` is the engine's standard idiom — fifteen call
sites of `0x0079D833`, of which `0x00885765` is this one and `0x0089DD4A` is `AutoDepositUpdate`'s.

## 2. The patch

Three edits, one appended section. Two of the three are in-place byte rewrites; only the field
table needs to move.

### 2.1 The default — 8 bytes, in place, at `0x0088528B`

```
old  c6 46 14 00        mov   byte  [esi+0x14], 0
     c6 46 15 01        mov   byte  [esi+0x15], 1
new  83 66 14 00        and   dword [esi+0x14], 0     ; +0x14..+0x17 = 0
     c6 46 15 01        mov   byte  [esi+0x15], 1     ; Visible = Yes
```

Eight bytes for eight. `and dword [esi+0x14], 0` clears `HighPriority`, `Visible`, the new
`GiveNoXP` at `+0x16` and the remaining pad byte in one go; the following store puts `Visible`
back to `Yes`. It is the constructor's own idiom — `and dword [esi+0x0c], 0` sits three
instructions earlier — and it costs no cave, no hook and no displaced instruction.

`GiveNoXP` therefore defaults to `No`, and a `.ini` that never names the keyword produces a
byte-identical `ModuleData` to stock.

### 2.2 The field table — relocate, then one 4-byte repoint

The table at `0x00C5FD78` has no room to grow: the eight rows are followed immediately by the
terminator at `0x00C5FDF8` and then by unrelated `.rdata`, and the keyword strings its rows point
at (`0x00C5FD44`-`0x00C5FD6C`) sit immediately *before* it. So the table is rebuilt into the cave —
the same move [`patches/utils/name_tables.py`](../patches/utils/name_tables.py) makes for the name tables, at
its cheapest possible size:

**there is exactly one reference to `0x00C5FD78` in the whole image**, the `push` immediate at
`0x008852BF` inside `buildFieldParse`:

```
008852b8  8b 4c 24 04        mov  ecx, [esp+4]
008852bc  6a 00              push 0
008852be  68 78 fd c5 00     push 0xc5fd78            ; <- the 4 bytes at 0x008852bf
008852c3  e8 0f 66 ba ff     call 0x42b8d7            ; MultiIniFieldParse::add(table, extraOffset)
```

The rebuilt table is the eight stock rows copied verbatim — their name pointers are absolute and
keep pointing at the stock strings — plus one appended row and the terminator:

```
{ <cave>+0x00, 0x0042E558, 0, 0x16 }      ; "GiveNoXP", the engine's Bool parser, ModuleData+0x16
{ 0, 0, 0, 0 }
```

`0x0042E558` is the stock `Bool` parser; its tail is `mov ecx, [esp+0xc] ; mov byte [ecx], al`, a
single byte store through the pointer the INI reader forms as `store + offset` — which is why a
`Bool` can live in a padding byte at all.

The table is read through its NULL terminator and never through a count (`parse_table`'s own walk
and `MultiIniFieldParse::add` at `0x0042B8D7` both stop on a null name pointer), so there is **no
count bound to raise** anywhere — the one thing that made `commandset-limit` expensive does not
apply here.

### 2.3 The gate — 6 bytes hooked at `0x0088573C`

The stock window from `0x0088573C` to the first `push` at `0x00885751` is 21 bytes and holds 21
bytes of code, so the three instructions the gate needs (load the `ModuleData`, compare, branch)
do not fit in place. Hook the 6-byte load instead:

```
0088573c  e9 <rel32 to cave+gate>  jmp  <gate>
00885741  90                        nop
```

and in the cave:

```
gate:
  8b 45 e8              mov  eax, [ebp-0x18]        ; ModuleData (the update's own cached slot)
  80 78 16 00           cmp  byte [eax+0x16], 0     ; GiveNoXP
  75 0b                 jne  skip
  8b bf 6c 02 00 00     mov  edi, [edi+0x26c]       ; the displaced instruction
  e9 <rel32>            jmp  0x00885742
skip:
  e9 <rel32>            jmp  0x0088576a
```

25 bytes. `[ebp-0x18]` is the slot `update` itself uses — it is written once at `0x008854EF` and
read again by the very next stock instruction at `0x0088576A`, so the gate reads exactly what the
function reads and nothing needs re-deriving. `eax` is dead at the hook on both incoming paths (the
`jle` from `0x0088567A` and the fall-through from `0x00885737`), `edi`/`ebx` are untouched, and
`0x0088576A` is where both stock rejections already land, so `Yes` takes an edge the engine
already has.

### 2.4 Cave layout

One appended section, `.trexp`, allocated with `allocate_section` (never a fixed RVA — README
"Composing patches", rule 1):

| offset | bytes | what |
|---|---|---|
| `+0x00` | 9 | `"GiveNoXP\0"`, padded to keep what follows dword-aligned |
| `+0x0C` | `0xA0` | the rebuilt field table: 9 rows + terminator |
| `+0xAC` | 25 | the gate |

`0xC5` bytes of content for the default keyword, one `0x200`-byte raw section; every offset past
the string is a function of the keyword's length, which is what lets `verify` recompute them. On a
clean image the section lands at RVA `0xAD4000`, but the RVA is computed rather than named, so it
moves up if another patch's cave is already there. There is no relocation directory in this image
(no `.reloc`, `DllCharacteristics = 0`), so repointing an absolute immediate needs no fixup.

### 2.5 Parameters

`TerrainResourceExpPatch(keyword="GiveNoXP")`. The keyword is the only thing worth parameterising
— everything else (the offset, the row, the two rel32s) is derived from it and from where the cave
landed. The default is the name the stock `AutoDepositUpdate` already uses for this exact field
(§3), so a mod writes one keyword for one concept across both income modules; `--keyword NAME`
takes any other, and is refused for a name the module already parses.

## 3. The precedent: `AutoDepositUpdate::GiveNoXP`

The stock engine already implements this exact field on the other income module, and the patch is
shaped to match it rather than to invent something.

`AutoDepositUpdate` — registration `0x0064E1D5`, `ModuleData` ctor `0x00653EBA`, `sizeof` `0x24`,
field table `0x00C07FD8`, `update` `0x0089DB5D` — carries eight fields, and two of them are `Bool`s
the constructor initialises with `mov byte [esi+0x20], bl` / `mov byte [esi+0x21], bl` at
`0x00653EFB`:

| keyword | type | offset |
|---|---|---|
| `DepositTiming` | Duration | `+0x08` |
| `DepositAmount` | Int | `+0x0C` |
| `InitialCaptureBonus` | Int | `+0x10` |
| `Upgrade` | UpgradeTemplate | `+0x14` |
| `UpgradeBonusPercent` | Percent | `+0x18` |
| `UpgradeMustBePresent` | KindOfFilter | `+0x1C` |
| **`GiveNoXP`** | **Bool** | **`+0x20`** |
| `OnlyWhenGarrisoned` | Bool | `+0x21` |

and its update gates the grant like this:

```
0089dd08  e8 ab 3b f1 ff     call 0x7b18b8            ; deposit the money
0089dd0d  8b 46 f8           mov  eax, [esi-8]        ; Object
0089dd10  8b b8 6c 02 00 00  mov  edi, [eax+0x26c]    ; ExperienceTracker
0089dd16  8b 46 f4           mov  eax, [esi-0xc]      ; ModuleData
0089dd19  80 78 20 00        cmp  byte [eax+0x20], 0  ; GiveNoXP
0089dd1d  75 30              jne  0x89dd4f            ; -> skip the grant, keep the money
0089dd1f  3b fb              cmp  edi, ebx
0089dd21  74 2c              je   0x89dd4f
0089dd23  8b cf              mov  ecx, edi
0089dd25  e8 f8 f5 ef ff     call 0x79d322            ; isTrainable
...
0089dd4a  e8 e4 fa ef ff     call 0x79d833            ; addExperiencePoints
0089dd4f  ...
```

`cmp byte [ModuleData+off], 0` / `jne <past the grant>`, sitting immediately before the tracker
null-test, after the deposit. §2.3 is that gate, instruction for instruction, relocated into a cave
because `TerrainResourceBehavior`'s copy of the block has no nine spare bytes in it.

Two consequences worth stating plainly:

- **The semantics are already defined by the engine.** `GiveNoXP = Yes` on `AutoDepositUpdate`
  keeps the money and drops the experience. `GiveNoXP = Yes` here does the same thing, on the same
  edge, with the same field type and the same default.
- **It is evidence the split is intentional, not an oversight in the module.** Whoever added
  `GiveNoXP` to `AutoDepositUpdate` did not add it to `TerrainResourceBehavior`; the patch closes a
  gap between two modules rather than second-guessing a design.

## 4. What this does *not* do

- **Only `TerrainResourceBehavior`.** The `[obj+0x26C]` → `isTrainable` → `addExperiencePoints`
  idiom appears at fifteen call sites (`ProductionUpdate` twice, the special-ability updates, the
  slaughter contains, `ShareExperienceBehavior`, the production-exit updates, `AutoDepositUpdate`
  …). One is gated. The rest keep granting experience exactly as they do now.
- **The income is untouched.** `GiveNoXP = Yes` changes nothing about `MaxIncome`,
  `IncomeInterval`, the upgrade bonus, the handicap curve, the deposit, the floating `+N` text or
  the sleep the update returns. The only instruction that stops running is the
  `addExperiencePoints` call (and the two tests in front of it).
- **It does not stop the building levelling by other routes.** An object with an
  `ExperienceScalarUpgrade`, a `ShareExperienceBehavior` sponsor (`ExperienceTracker+0x38`, which
  `addExperiencePoints` walks) or any other grant still gains experience from those. This gates one
  producer, not the tracker.
- **`TerrainResourceClientBehavior` is a different module** with no `ModuleData` and no experience
  path; it is not touched.
- **`sage_ini` does not model the field yet.** The keyword exists in the patch and nowhere else,
  deliberately: adding `GiveNoXP: Bool` to `sage_ini.model.behaviors.TerrainResourceBehavior` would
  have the library accept a keyword no shipped binary understands. That is a one-line change to
  make when a build carrying this patch ships.

## 5. Determinism and compatibility

**Every peer must run the same patched binary, and this one is stricter than a data-shape change.**
Experience feeds `ExperienceTracker`, veterancy level is logic-side `Object` state, and the engine
CRCs it — a patched and an unpatched client running the same mod would diverge on the first income
tick of any building whose `.ini` sets `GiveNoXP = Yes`, and replays would not cross. That puts it
in the same class as `production-condition`, not `replay-outcome`.

**The keyword is fatal on an unpatched binary.** SAGE's INI reader treats an unknown field name in
a known block as a parse error — the same failure the `CommandSet` limit produces as
`"Error parsing field '34'…"`. A mod that writes `GiveNoXP` into a `TerrainResourceBehavior` block
will not load on a stock `game.dat` at all. There is no graceful-degradation path here and none is
worth engineering: the field is only usable by a mod that ships the patched binary.

**Savegames are unaffected.** `ModuleData` is compile-time configuration read from `.ini` at load,
not per-object state, and is never `Xfer`'d; `+0x16` is padding a savegame has never carried.
Nothing about the save format changes, and a save taken on a patched build loads on another patched
build normally.

## 6. Composition

No bundled patch touches any of the three sites (`0x0088528B`, `0x008852BE`, `0x0088573C`), reads
the table at `0x00C5FD78`, or derives anything from bytes this one rewrites. The nearest neighbours
are `production-condition` and `unique-production-id`, both of which live in `ProductionUpdate`
(`0x008A1B9F` / `0x008A18FA`) — a different module and a different function. The cave is allocated
with `allocate_section` and found again with `find_section`, so `.trexp` composes in any order with
`.cmdext`, `.cahfac`, `.prodmc`, `.prodid`, `.rpout` and `.rpskir` the way the README's three rules
require.

## Status

**Static-verified (2026-08-02) and runtime-verified in a game.**

```sh
sage-patch apply terrain-resource-exp --in game.dat.backup --out game.dat
sage-patch verify terrain-resource-exp game.dat
```

`verify` re-derives, from the keyword alone: the eight rewritten constructor bytes; that the `push`
immediate at `0x008852BF` equals the table's address in the cave; that the cave's nine rows are the
eight stock rows verbatim plus `{<keyword>, 0x0042E558, 0, 0x16}` followed by the terminator; that
the keyword string is where the ninth row's name pointer says it is; and that the gate's bytes and
both rel32 targets (`0x00885742`, `0x0088576A`) resolve correctly from wherever `.trexp` landed.
Structural and disassembler-free, like the rest.

What the static pass proved, applying to a real `game.dat`:

- ✅ **The three edits install and `verify` comes back clean**, with the cave allocated at the next
  free RVA rather than a named one.
- ✅ **Every site disassembles to what §2 says it should** — the constructor to
  `and dword [esi+0x14], 0` / `mov byte [esi+0x15], 1`, `buildFieldParse` to a `push` of the cave's
  table, the hook to `jmp <cave>` / `nop`, and the gate to `mov eax, [ebp-0x18]` /
  `cmp byte [eax+0x16], 0` / `jne` with both rel32s landing on `0x00885742` and `0x0088576A`.
- ✅ **It composes with `unique-production-id` in either order**, both patches verifying clean in
  both builds and the section table staying RVA-sorted.
- ✅ **An independent reader agrees.** `python scripts/module_defaults.py <patched game.dat>`
  recovers the module table straight out of the binary, knowing nothing about this patch, and
  reports what §1.1 and §2.1 claim:

  ```
  sizeof(ModuleData) = 0x24
    +0x14  HighPriority   Bool  default No
    +0x15  Visible        Bool  default Yes
    +0x16  GiveNoXP       Bool  default No
    +0x18  UpgradeMustBePresent …
  ```

Reading a *patched* binary asks two things of that script, both neutral on a stock one: it has to
follow a table pointer into any section, not just `.rdata`/`.data`, because a relocated table is
in neither; and it has to treat `and dword [x], 0` as defaulting all four bytes rather than one,
or a `Bool` packed beside an `Int` reads as having no compiled-in default. Regenerated against
an unpatched `game.dat`, [`module-reference.json`](module-reference.json) is unchanged across all
329 modules.

Open, and needing one session in-game:

1. **A spot with `GiveNoXP = Yes` still pays the same money per tick.** The gate sits after the
   deposit and touches neither the amount nor the floating `+N`, but nothing static proves the
   deposit path is untouched at runtime.
2. **Its building stops levelling**, while a second spot without the field keeps levelling
   normally — the actual behaviour the field exists for, and the one thing only a game can show.
3. **A `.ini` naming the keyword loads at all.** The row parses on paper; the INI reader has never
   seen it.

Where the pieces live:

| piece | where |
|---|---|
| `TerrainResourceExpPatch` | [`patches/terrain_resource_exp.py`](../patches/terrain_resource_exp.py) |
| the `terrain-resource-exp` CLI name | [`registry.py`](../registry.py) |
| the three sites, the table and its stock bytes | [`addresses.py`](../addresses.py) |
| tests | [`tests/sage_patch/test_terrain_resource_exp.py`](../../tests/sage_patch/test_terrain_resource_exp.py) |

## Address index

`TerrainResourceBehavior` registration `0x0064BF55` / `0x0064BF8D` (mask `0xB`) · `ModuleData` ctor
`0x0088525D` (`sizeof` `0x24`, free padding `+0x16`/`+0x17`) · default stores `0x0088528B` ·
`buildFieldParse` `0x008852B8`, its `push` immediate `0x008852BF` · field-parse table `0x00C5FD78`
(8 rows, terminator `0x00C5FDF8`, **one** reference) · behaviour ctor `0x008852C9` (`sizeof` `0x30`)
· vtables `0x00C5FC94` / `0x00C5FBD8` (`+0x0C`) / `0x00C5FBCC` (`+0x10`) / `0x00C5FBC8` (`+0x20`) /
`0x00C5FBB8` (`+0x24`) · `update` `0x008854D3` (slot 0 of `0x00C5FBCC`), its `ModuleData` slot
`[ebp-0x18]` written at `0x008854EF` · activation `0x008853A0` · income floor `0x00885675`,
`jle` past the deposit `0x0088567A`, deposit `0x007B18B8` at `0x008856B0` · **the experience block
`0x0088573C`-`0x00885765`, rejoin `0x0088576A`** · sleep return `0x0088576D`.

`Object` `m_experienceTracker` `+0x26C` (accessor `0x008D7C63`, written `0x008D7C35`) ·
`ExperienceTracker::isTrainable` `0x0079D322` · `ExperienceTracker::addExperiencePoints`
`0x0079D833` (15 call sites) · its sponsor chain `ExperienceTracker+0x38`, scalar `+0x1C`, object
`+0x34`.

`AutoDepositUpdate` registration `0x0064E1D5` · `ModuleData` ctor `0x00653EBA` (`sizeof` `0x24`,
`GiveNoXP` `+0x20` zeroed at `0x00653EFB`) · field table `0x00C07FD8` · `update` `0x0089DB5D` ·
**its `GiveNoXP` gate `0x0089DD16`-`0x0089DD1D`**, skip target `0x0089DD4F`.

`Bool` parser `0x0042E558` · `MultiIniFieldParse::add` `0x0042B8D7` · `addModule` `0x006570FE` ·
`operator new` `0x0042F6E0` · `TheGameLogic` `0x00DE412C` (terrain-resource registry `+0x170`,
add `0x0075BDC2`, remove `0x0075BCD9`) · `TheGameText` `0x00DE4B04` · `ThePlayerList` `0x00DE4928`.
