# A second resource type — what it would cost

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the clean
`sage_patch/engine/game.dat.backup`.

**Scope of the idea:** a second spendable currency alongside gold, with (1) an internal counter per
player, (2) a HUD element next to the existing one, (3) an INI block that grants it per tick, and
(4) an INI field that makes an object cost it to build or recruit.

**Status: assessed, not attempted.** Nothing here has been built or runtime-verified. The measured
facts (addresses, table shapes, call-site counts) are read out of the binary; the effort claims are
judgement.

**Verdict up front:** pieces 1–3 are small-to-medium and reuse patterns
[`sage_patch`](../../sage_patch/README.md) has already proven — a cave-resident counter like
[`unique-production-id`](../../sage_patch/docs/unique-production-id.md), a name/field-table relocation
like [`production-condition`](../../sage_patch/docs/production-model-condition.md). Piece 4 is the
driver, and the real blocker behind it is **the AI**, not the engine. A grant-and-display-only
version is a genuinely useful mod primitive on its own and costs a fraction of the whole.

## 1. Internal counter per player

Money lives in a `Money` subobject at `Player+0x90`:

```
Player +0x90   Money m_money         (Snapshot subobject, so +0x90 is its vptr)
       +0x94   UnsignedInt  current spendable         <- pinned live, see engine-globals.md
       +0x3DC  ScoreKeeper stats block
       +0x3E0    cumulative collected (stats+0x04)    monotonic, never falls
       +0x54   Int m_playerIndex
```

| what | VA | note |
|---|---|---|
| `Money::withdraw(amount, stats, playSound)` | `0x7b17ef` | **clamps to available and returns what it took — never refuses** |
| `Money::deposit(amount, stats, playSound)` | `0x7b18b8` | |

The clamp matters: affordability is *always* decided upstream of the withdrawal, never by it.

```
008a129c  add  ecx, 0x90                              ; ecx = &player->m_money
008a12a2  call 0x7b17ef                               ; withdraw(cost, player+0x3DC, TRUE)
```

**Storage: use a side table, not a grown `Player`.** `UInt32 g_res2[20]` in a cave, indexed by
`Player::m_playerIndex` — `MAX_PLAYER_COUNT` is 20 and
[cannot practically be raised](../../sage_patch/docs/max-player-count.md) anyway. No struct growth,
no ctor edit, no allocation-size hunt. Same shape as `unique-production-id`'s `.prodid` counter.

Two real costs hide in this otherwise-cheap piece:

- **Init.** Something has to zero the table on new game and seed it from a `StartMoney2` equivalent.
  One hook, but it has to be the right one — `PlayerList::newGame` skips the neutral side and the
  slot census is not the participant census (a solo skirmish still carries five `Player` slots).
- **Savegame.** A cave-resident counter is not `Xfer`'d, so a load resets it.
  `unique-production-id` [accepted exactly this trade](../../sage_patch/docs/unique-production-id.md)
  for a production id, where it costs at most one collision. For a resource *pool* it is a visible
  bug, not a narrow window. Extending `Player::xfer` is a savegame format change. Budget it, or
  declare saves unsupported and say so in the patch docstring.

## 2. UI element

Better news than expected: **the resource bar is data-bound, not hand-drawn.** `TheAptPlayer`
(`0x00DE3F0C`) holds a binding map at `+0xa4`. The HUD object's constructor at `0x6d61bc` registers
paths against pointers into its own members, and the teardown at `0x6d4b6e` unregisters them:

| binding path | bound to | register call |
|---|---|---|
| `Palantir/ResourceBar/Resources/` | `this+0x0C` (Int) | `0x6241ce` |
| `Palantir/ResourceBar/CommandPoints/` | `this+0x10` (Int) | `0x6241ce` |
| `Palantir/ResourceBar/ResourceMultiplier/` | `this+0x18` (Real) | `0x6241ce` |
| `ResourceBar/ResourceIcon` | string → `Resource_Icon` | `0x6236f6` |

```
006d61d7  lea  edi, [esi+0xc]                         ; &this->resources
006d61da  lea  ebx, [esi+0x10]                        ; &this->commandPoints
...
006d6299  push 0xc18f5c                               ; "Palantir/ResourceBar/Resources/"
006d62b4  mov  [ebp-0x10], edi                        ; closure captures the *pointer*
006d62b7  call 0x6d55ea                               ; make watcher: 12 bytes, vtable 0xc18e74,
006d62c6  call 0x6241ce                               ;   +0x08 = the captured pointer
```

The watcher holds a **pointer to the value** and the movie re-reads it every frame, so there is no
display code to write and no per-frame push to schedule. The **icon is data-bound too**, so a second
icon costs nothing extra in code.

Engine half: one more binding registered in a cave, with a new path string and a mirror Int fed from
`g_res2[localPlayerIndex]`. Feed a *mirror* rather than binding `&g_res2[i]` directly — the local
player can change (observer, replay playback) and the watcher captures the pointer once.

**The cost is the other half: the movie.** The text field and icon have to be added to the Palantir
`.apt` (`APT:PalantirResources`, `0xc19050`). [`sage_apt`](../../sage_apt/README.md) round-trips and
edits APT pairs, but its own README says it is *"not yet fully functional and largely untested…
don't rely on it for production edits yet."* **That is the schedule risk in this piece** — plan on
hardening the APT round-trip as part of the work, not as a given.

## 3. INI block for granting per tick

`AutoDepositUpdate` already *is* this module:

```
AutoDepositUpdate ModuleData    size 36, ctor 0x653eba
  +0x08  DepositTiming          Duration
  +0x0c  DepositAmount          Int
  +0x10  InitialCaptureBonus    Int
  +0x14  Upgrade                UpgradeTemplate
  +0x18  UpgradeBonusPercent    Percent
  +0x1c  UpgradeMustBePresent   KindOfFilter
  +0x20  GiveNoXP               Bool
  +0x21  OnlyWhenGarrisoned     Bool
  +0x22  ---- alignment padding ----
```

Fields end at `+0x21` and the block is 36 bytes, so **`+0x22..+0x23` is alignment padding** and a
`DepositAmount2` as `UInt16` (cap 65535/tick, ample) fits with **no ModuleData growth at all**. One
field-table entry plus a hook on the module's deposit to also credit resource 2.

Add a `StartMoney2` on `PlayerTemplate` in the same pass (`StartMoney` is a sub-block at `+44`).

## 4. INI block for cost — the driver

Two sub-problems, and the second is much worse than the first.

### 4a. Storage and parsing — tractable

`Object.BuildCost` is a `UInt16` at `ThingTemplate+0x5EA`; `RefundValue` follows at `+0x5EC`. The
Object field-parse table:

```
base         0x00DA3DF8       in .data (writable, 0xC0000040)
entries      191 x 16 bytes   { const char *name; ParseFn; void *userdata; UnsignedInt offset; }
terminator   0x00DA49E8       all-zero entry
references   5 to the base    0x73bdf5 0x73befc 0x73bf50 0x73c143 0x73e8ca
             1 interior       0x7162a4 -> 0xDA45E8 (index 127, "OcclusionDelay")

0x00DA4028   { 0xc10b70 "BuildCost", 0x42ec11 (UInt16 parser), 0, 0x5ea }
```

Five base references is a **smaller repoint job than `production-condition`'s sixteen**, and
[`patches/name_tables.py`](../../sage_patch/patches/name_tables.py) already implements the move:
read the live table, rebuild it into a cave with the new entry, repoint every reference. The
interior reference has to be re-derived rather than copied.

For the 2 bytes of storage, there is a **gap at `ThingTemplate+0x5E8`** (`CampnessValue` is an Int
at `+0x5E4`, ending at `+0x5E8`; `BuildCost` starts at `+0x5EA`). **Do not assume it is free.**
Alignment does not explain it — a `UInt16` at `+0x5E8` would have been perfectly aligned — so it is
most likely a non-INI member the field scan cannot see. **Verify this before committing to
Phase 2**; the fallback is growing `ThingTemplate`, which is a step up in cost but not a wall.

`Upgrade.BuildCost` is a separate `Int` at `+52` in a separate field table, and needs the same
treatment if upgrades are to cost resource 2.

### 4b. Enforcement — the actual work

There are **22 call sites of `Money::withdraw` and 35 of `Money::deposit`**. Not all matter, but a
coherent second currency has to reach at least:

| path | site |
|---|---|
| unit + hero production withdrawal | `0x8a12a2` (in `ProductionUpdate::queueCreateUnit` `0x8a11d2`) |
| pre-production affordability gate | `BuildAssistant` vtable `+0x64`, `0x793ecb` |
| AI producer choice | `BuildAssistant::canMakeUnit` `0x794f38` |
| structure placement | its own withdrawal among the 22 |
| upgrade research | `Upgrade.BuildCost`, its own withdrawal |
| cancel / refund | `GameData.RefundPercent` |
| "not enough" UI | `0x940a4a`, `0x83e798`; tooltip `0x807e8c` |

Call it 6–10 sites, each needing its own hook and its own verification. That is the bulk of the
project.

### 4c. The AI — the real blocker

The AI's economy reasoning (`EconomyBuilderMinMoney`, `AIMoneyLender`, the build manager) knows
exactly one pool. **A second cost the AI cannot see means AI players either stall permanently or
queue things they can never pay for.** Teaching the AI about resource 2 is plausibly as large as
everything above combined, and it is the piece most likely to be discovered late.

## Cross-cutting

- **Every peer must run the same binary.** Affordability changes what gets built, so a patched and
  an unpatched client desync and replays do not cross. That is the `production-condition` rule, and
  it is stricter than `replay-outcome`'s client-local guarantee. Even the grant-only Phase 1 inherits
  this the moment anything reacts to the counter.
- **Tail work in the Python tooling is cheap**: one annotation in
  [`sage_ini/model/ini_objects.py`](../../sage_ini/model/ini_objects.py) (`BuildCost: Int = 0`,
  line 78), the cost analysis in [`sage_lint/analysis.py`](../../sage_lint/analysis.py) (line 26),
  `sage_live`'s economy observation, and regenerating `module-reference.json` / `ini-types.json`.

## Recommended shape

**Phase 1 — grant and display.** Counter + APT binding + `DepositAmount2` + `StartMoney2`. Nothing
*costs* resource 2, so nothing can stall and the AI stays correct by construction. This de-risks the
APT pipeline early and is already useful on its own (a scored or prestige currency, a captured-point
tally, a faction-specific meter). Comparable in size to `production-condition`.

**Phase 2 — cost.** The field table, the `+0x5E8` storage question, and the 6–10 enforcement sites,
gated to human-buildable things. Multi-week, and larger than any patch currently in the tree.

**Phase 3 — AI awareness.** Scope separately. Do not fold it into Phase 2's estimate.

## Verify before committing

1. Is `ThingTemplate+0x5E8` genuinely unused, or a non-INI member? (Decides whether Phase 2 has to
   grow `ThingTemplate`.)
2. Does `AutoDepositUpdate`'s ModuleData padding at `+0x22` survive its ctor untouched?
3. Which of the 22 withdrawal sites is structure placement, and which is upgrade research?
4. Does `sage_apt` round-trip the Palantir movie byte-stably today? (`python -m sage_apt check`.)
