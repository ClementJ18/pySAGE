# ROTWK `game.dat` patching

Reverse-engineering + binary-patch work on the ROTWK SAGE engine (build `2.01.2614.37001`). The
patches below are all engine-level — they apply to any ROTWK install of that build and benefit
every mod on it (Edain among them), not one in particular. All of them target `game.dat` except
`desert-weather-wb`, which patches `Worldbuilder.exe` from the same install:

- **`commandset-limit`** raises the `CommandSet` button limit from its stock **33** to any **N** in
  34..127, plus the INI paging rule needed to surface the extra buttons, and widens the AI's
  set-walk to the same N. The shipped build uses **N = 64**.
- **`cah-factions`** teaches the nine-name Create-A-Hero faction enum a caller-supplied list of mod
  sides plus an `All` token, so a `SubClass` can name them in `UsableFactions`.
- **`ai-revive-gate`** makes the AI evaluate a `REVIVE` command button's `NeededUpgrade` before
  recruiting or reviving through it. The engine checks that requirement for the player and for
  `UNIT_BUILD` buttons, but not on the AI's revive path — so hero slots disabled by an
  unobtainable upgrade are player-only restrictions today. The gate applies **only to callers that
  ask `canMakeUnit` directly**, which is only ever the AI's own choice of producer; the ControlBar
  and production come in through `BuildAssistant`'s `+0x64` gate and keep the stock answer.
- **`production-condition`** adds a **model condition** that is active while a structure's
  production queue is non-empty — training a unit *or* researching an upgrade. The stock engine
  has no such state: the `DOOR_n_*` conditions run *after* a unit completes, as the buffer during
  which it walks out, and `ModelConditionUpgrade` fires on an upgrade's completion. Two **opt-in**
  extras ride the same trigger: `--weapon-set-flag NAME` adds a `WeaponSetFlag`, so a
  `WeaponSet Conditions = NAME` block can give a producer a different loadout while it is busy,
  and `--locomotor-set NAME` adds a `LocomotorSetType`, so `Locomotor = NAME <template>` can give
  it a different locomotor. Both of those tables are read through their terminator rather than a
  count, so each costs a relocation and nothing else, and objects declaring neither are
  unaffected.
- **`desert-weather`** adds a third global weather, **`DESERT`**, and a **`SAND`** model condition
  for it to drive - the pairing the engine already has for `SNOWY` → `SNOW`, and only for that one.
  A map carrying `weather = 2` (a plain `Integer` in its `WorldInfo` chunk, which is how the
  engine actually gets its weather - not `map.ini`) then sets `SAND` on every drawable the way a
  snowy map sets `SNOW`, and `WeatherTexture = DESERT …` works too. Note that `SAND` is **not** a
  stock model condition: the patch creates it, out of the same name table `production-condition`
  extends, so the two compose in either order.
- **`desert-weather-wb`** is the authoring half of that, and the one patch here that targets
  **`Worldbuilder.exe`** rather than `game.dat`. Worldbuilder's map-settings weather dropdown is
  filled by a loop with a hardcoded member count, so `DESERT` never appears in it - and because
  the OK handler stores `CB_GETCURSEL` unvalidated, opening that dialog on a `DESERT` map and
  pressing OK writes `-1` back into the map and silently reverts it. The patch grows the same
  table and raises that one bound. Dropdown only: the editor *viewport* keeps drawing the
  non-`SAND` variant, which needs Worldbuilder's own model-condition table extended too.
- **`replay-outcome`** writes **each player's final victory/defeat state into the replay**, at
  the frame the recording ends - whether a player left or the game finished. A stock replay
  records inputs, not state, so no chunk says who won and
  [`sage_replay.winner`](../sage_replay/winner.py) has to infer it from who stopped issuing
  orders (and gives up entirely on elimination endings and on AI players). This adds one `0x7D0`
  chunk per player, written straight to the recorder's own file handle just before the `0x1D`
  end-of-recording marker. Client-local: nothing enters the simulation and nothing crosses the
  network, so it does **not** have to be on every peer. **Runtime-verified** on all three endings
  — see Status.
- **`skirmish-replay`** makes a **single-player skirmish record a replay**, which the stock engine
  never does, and gives each recording a **timestamp + map** name instead of overwriting
  `Last Replay`. `startRecording` has exactly one caller — the `MSG_NEW_GAME` branch of
  `RecorderClass::updateRecord` — and it whitelists the game mode against `{1, 5}`, the two
  network flavours; a skirmish emits **2** and falls off the end of the list. Everything
  downstream already works: `startRecording` has a complete non-network path that builds the
  header from `TheSkirmishGameInfo`, and the engine's own playback predicate already accepts a
  *recorded* mode of 2. So the patch replaces nine bytes of whitelist and retargets the call that
  names the file. **By default every recording is renamed**, not just skirmishes: the fixed name
  means each game overwrites the last, and a file every player has under the same name is what
  makes replays impossible to collect. That costs the replay menu's Save Replay button, which
  exists only to rescue the file before it is overwritten (`--rename added` keeps the stock
  behaviour for network games). Client-local, like `replay-outcome`. **Gate runtime-verified,
  naming re-test open** — see Status.
- **`terrain-resource-exp`** adds a **`GiveNoXP`** boolean to `TerrainResourceBehavior`, so a
  resource spot can pay its owner without levelling its own building. The module hands the integer
  it just deposited to the building's `ExperienceTracker` on every income tick, and no INI field
  separates the two — while the sibling `AutoDepositUpdate` has shipped exactly this boolean, under
  exactly this name, since the stock build. The new field lands in `ModuleData+0x16`, alignment
  padding the constructor never wrote, so nothing grows.
- **`unique-production-id`** mints the `ProductionID` **game-wide** instead of per building. The
  stock counter lives on the producer, so every building's first production is id 1 — and hero
  recruitment keys the player's revive bookkeeping on that id, so recruiting a hero from a second
  building while the first is still producing collides, and the click takes the money without
  starting anything.
- **`hero-mana`** gives special powers a **regenerating per-object cost** — `SpecialPower.ManaCost`
  for the price of one activation, and `Object.ManaPool` / `Object.ManaRegen` for the caster's
  single pool that all of its abilities draw on. The stock `UnitCost` field cannot do
  this: all three sites that read it ask `Object+0x258` for the horde interface first and, when
  it is absent, branch to *the same label as "cost is zero"* — so on a lone hero `UnitCost` is
  not a weak mechanic, it is a **no-op**. The patch grows `SpecialPowerTemplate` `0x88 → 0x94`,
  relocates both the `SpecialPower` field-parse table (**two** references, the smallest repoint
  here) and the `Object` one (**five**, and no interior reference despite what
  `second-resource-type` records),
  and enforces the cost at `SpecialPowerStore::canUseSpecialPower` — the one predicate the
  player's UI, the AI and every activation path all share, so **the AI is gated for free**. The
  pool is *computed on read* from the logic frame rather than ticked, which is what lets it need
  no per-frame hook (avoiding a collision with `live-bridge`), no init hook, no destroy hook and
  no savegame change. A `ManaCost` line joins the stock `UnitCost` one in a button's description,
  from the `TOOLTIP:ManaCost` key and carrying **both the price and what the caster currently has**;
  a `ManaPool` line sits under a hero's level on its revive/recruit button. `ManaCost = 0`, the default, leaves a power exactly as it is today.

- **`command-point-upkeep`** makes a large army **cost a player income**: the more command points
  they have in the field, the less their resource buildings pay. Two new `PlayerTemplate` fields
  declare the curve per faction — `UpkeepCommandPointStep` (how many command points move a player
  one tier; **0, the default, is upkeep off**) and `UpkeepValues` (the percentage of income kept
  at each tier, the last entry held for everything past it). It is not a new mechanic so much as a
  second dial on an old one: `ResourceModifierValues` — the per-building "inflation" every Edain
  faction sets — is read in exactly **one** place, `AutoDepositUpdate::update`, which turns a
  *count* into a percentage and scales the deposit by it. Upkeep swaps the count for command
  points and multiplies the same slot, so the two stack and the engine's "never round income below
  1 gold" floor still applies. Only income the faction's own `ResourceModifierObjectFilter`
  accepts is taxed, because `AutoDepositUpdate` is *all* tick income and would otherwise catch
  captured neutral structures too. The per-faction rows live in the cave keyed by the template's
  `NameKeyType`, not by a pointer — a `PlayerTemplate` is parsed into a **stack temporary** before
  being copied into the store's vector — which is also what leaves **no savegame change and no
  init hook**. The `PlayerTemplate` field table has **one** reference, the smallest repoint here.
  The palantir's command-point readout gains the current loss: `500/1500 (-10%)`, produced by the
  engine's own formatter with a third vararg, so it needs no `.apt` and no `.csf`/`.str` edit
  (a mod's `APT:PalantirCommandPoints` string is a design-time placeholder the engine overwrites
  every refresh). `--no-hud` leaves the text stock.

Uses [pyBIG](..)/capstone/pefile and Ghidra headless.

## CLI

Bring your own `game.dat` (this repo ships the patch recipe, never the copyrighted binary):

```sh
sage-patch list                                  # the registered patches
sage-patch apply commandset-limit --count 64 \
    --in game.dat.backup --out game.dat          # --in is read, never modified
sage-patch verify commandset-limit --count 64 game.dat   # exits non-zero on any mismatch

sage-patch apply cah-factions --sides Rohan,Lothlorien \
    --in game.dat.backup --out game.dat
sage-patch verify cah-factions --sides Rohan,Lothlorien game.dat

sage-patch apply ai-revive-gate --in game.dat.backup --out game.dat   # no parameters
sage-patch verify ai-revive-gate game.dat

sage-patch apply production-condition --condition PRODUCING \
    --in game.dat.backup --out game.dat
sage-patch verify production-condition --condition PRODUCING game.dat

# the same patch with both optional halves; verify takes the arguments apply was given
sage-patch apply production-condition --condition PRODUCING \
    --weapon-set-flag PRODUCING --locomotor-set SET_PRODUCING \
    --in game.dat.backup --out game.dat

sage-patch apply unique-production-id --in game.dat.backup --out game.dat   # no parameters
sage-patch verify unique-production-id game.dat

sage-patch apply replay-outcome --in game.dat.backup --out game.dat         # no parameters
sage-patch verify replay-outcome game.dat

sage-patch apply skirmish-replay --in game.dat.backup --out game.dat  # --modes 2 --rename all
sage-patch verify skirmish-replay game.dat

# --pool is the fallback maximum in whole points, --regen the fallback refill in hundredths of a
# point per logic frame (30 == one point per second at 30fps); a SpecialPower may override both.
sage-patch apply hero-mana --pool 100 --regen 30 --in game.dat.backup --out game.dat
sage-patch verify hero-mana --pool 100 --regen 30 game.dat

# per-faction upkeep thresholds come from playertemplate.ini; --no-hud keeps the palantir's
# command-point text exactly as the stock engine draws it
sage-patch apply command-point-upkeep --in game.dat.backup --out game.dat
sage-patch verify command-point-upkeep game.dat

# rename only the skirmish recordings, leaving network ones (and Save Replay) as stock
sage-patch apply skirmish-replay --rename added --in game.dat.backup --out game.dat

sage-patch apply terrain-resource-exp --in game.dat.backup --out game.dat   # --keyword GiveNoXP
sage-patch verify terrain-resource-exp game.dat
```

`verify` re-derives the expected tables, the repointed references and every patched site from the
same parameters and checks them against the file — a structural, disassembler-free pass/fail.

## Telling the linter what the engine now accepts

A patch that adds an INI field or a name-table token changes what *valid data* looks like, and
`sage_ini`'s model describes the stock engine — so on a patched game the mod's own data reads as
a pile of unknown attributes and unknown enum tokens. `sagepatch` closes that: it reads the binary
and writes the `.sagepatch` that `sage_ini` and `sage_lint` load (see
[`sage_ini/engine.py`](../sage_ini/engine.py)).

```sh
sage-patch sagepatch game.dat -o /path/to/mod/.sagepatch   # commit it beside .sagelint
sage-patch sagepatch game.dat                              # to stdout, to review first
sage-patch sagepatch game.dat --check /path/to/mod/.sagepatch   # non-zero if it has drifted
sage-patch sagepatch --patch hero-mana --patch commandset-limit  # by name, no binary
```

It reads the **binary**, not a list of names you type, because that is the only thing that knows
what was actually built: which patches are in it, at what count, under which keyword, and which
token landed on which bit. Two passes do it, and they cover for each other — each patch is offered
the image through `Patch.detect` (which recovers its parameters) and contributes its declared
`Patch.ini_surface`, while the name tables are read live so *any* token past the stock ones is
recorded with its real index, including ones added by a patch applied under a custom name or by a
patch this package has never heard of. The `--patch` form skips the binary for a project that
would rather not wire a path into CI, at the cost of describing every patch with its defaults.

`--check` is the drift guard: run it in CI, and a committed `.sagepatch` that no longer matches
the binary the team ships fails the build instead of silently mislinting.

## The patch framework

`apply_patches(game_dat, patches, output=None)` applies an ordered list of `Patch` subclasses to a
copy of the binary and writes the result (in-place if `output` is omitted). Each `Patch` verifies
the bytes it expects before writing, so a list either applies in full or raises without leaving a
half-patched file.

```python
from sage_patch import AiReviveGatePatch, apply_patches, CahFactionsPatch, CommandSetLimitPatch

apply_patches(
    "game.dat.backup",
    [
        CommandSetLimitPatch(count=64),
        CahFactionsPatch(sides=["Rohan", "Lothlorien"]),
        AiReviveGatePatch(),
    ],
    output="game.dat",
)
```

| module | what |
|--------|------|
| [`patcher.py`](patcher.py) | the `Patch` base class (`apply` / `verify` / CLI hooks) + `apply_patches` driver |
| [`cli.py`](cli.py) | the `sage-patch` console script (`apply` / `verify` / `list` / `sagepatch`) |
| [`sagepatch.py`](sagepatch.py) | reads a patched binary back as the `.sagepatch` describing the INI it accepts — patch detection plus a live read of every engine name table |
| [`registry.py`](registry.py) | the name→`Patch` map the CLI dispatches over; register a patch here to expose it |
| [`addresses.py`](addresses.py) | every address of the target build, in one place — the globals, the hooked functions and the labels inside them that the caves jump to |
| [`asm.py`](asm.py) | the tiny label-resolving x86 emitter the caves are written with |
| [`utils.py`](utils.py) | PE/byte helpers (`allocate_section`/`find_section` — the pair that makes caves order-independent — plus `apply_byte_patch`, `va_to_offset`, `image_base`, …) operating on an in-memory `bytearray` |
| [`patches/commandset.py`](patches/commandset.py) | `CommandSetLimitPatch` — raise the CommandSet button limit to any N (grow the object + relocate/enlarge the field-parse table + widen the AI's set-walk) |
| [`patches/cah_factions.py`](patches/cah_factions.py) | `CahFactionsPatch` — add mod sides + an `All` token to the CAH faction enum (superset name table + a `UsableFactions` parser wrapper) |
| [`patches/ai_revive_gate.py`](patches/ai_revive_gate.py) | `AiReviveGatePatch` — route `canMakeUnit`'s revive branch through the engine's own `NeededUpgrade` check |
| [`patches/production_condition.py`](patches/production_condition.py) | `ProductionConditionPatch` — name the first unused model-condition bit and drive it from `ProductionUpdate`'s queue, optionally with a weapon-set flag and a locomotor set on the same trigger |
| [`patches/name_tables.py`](patches/name_tables.py) | the three moves every name-table extension makes — read the live table, rebuild it into a cave by pointer, repoint every reference — shared by the three table owners below |
| [`patches/model_conditions.py`](patches/model_conditions.py) | owner of the `ModelConditionFlags` table: its 16 references, its 10 count bounds and the `xfer` blob width |
| [`patches/weapon_set_flags.py`](patches/weapon_set_flags.py) | owner of the `WeaponSetFlags` table: 8 references, `Object+0x38C`, and the count that must **not** move |
| [`patches/locomotor_sets.py`](patches/locomotor_sets.py) | owner of the `LocomotorSetType` table: 8 references, and `chooseLocomotorSet` on the AI module |
| [`patches/terrain_resource_exp.py`](patches/terrain_resource_exp.py) | `TerrainResourceExpPatch` — add a `GiveNoXP` boolean to `TerrainResourceBehavior` (rebuild its field table into a cave by pointer, put the new `Bool` in the struct's padding, gate the experience grant on it) |
| [`patches/unique_production_id.py`](patches/unique_production_id.py) | `UniqueProductionIdPatch` — rewrite `requestUniqueUnitID` to mint from one game-wide counter instead of one per producer |
| [`patches/replay_outcome.py`](patches/replay_outcome.py) | `ReplayOutcomePatch` — write every player's final victory/defeat state into the replay as the recorded game is torn down |
| [`patches/skirmish_replay.py`](patches/skirmish_replay.py) | `SkirmishReplayPatch` — add the skirmish game mode to the recorder's whitelist, and name the file by timestamp and map |

`CommandSetLimitPatch(count=N)`. **`count` may be 34–127**; every offset, the object size, the
field-parse table, the slot-name strings and the AI's scan bound are derived from it.

`CahFactionsPatch(sides=[...])`. **At most 22 sides**, each matching a `PlayerTemplate`'s `Side`
string exactly; the table, the name strings, the parser wrapper and the resolver's scan bound are
all derived from the list. `All` is always added, and expands to every bit at parse time so no
gate needs patching. See [`docs/cah-faction-limit.md`](docs/cah-faction-limit.md).

`AiReviveGatePatch()`. **No parameters** — there is one revive branch and one correct edge to add.
It hooks 6 bytes and adds a 58-byte `.aigate` cave whose only job is to reach the engine's existing
upgrade gate with the matched slot already counted — and only when the caller asked
`canMakeUnit` directly, which is only ever the AI deciding which producer to use. Anything that
came in through `BuildAssistant`'s `+0x64` gate (the ControlBar, `queueCreateUnit`, scripts) takes
the stock edge, so the patch cannot hide a button or refuse a production. See
[`docs/ai-revive-gate.md`](docs/ai-revive-gate.md).

`ProductionConditionPatch(condition="PRODUCING", weapon_set_flag=None, locomotor_set=None)`.
**One condition**, plus the two opt-in extras. It extends the `ModelConditionFlags` name table
into a `.prodmc` cave, repoints its 16 references, raises 10 count bounds and hooks the 5-byte
entry of `ProductionUpdate::update`; each extra adds its own table to the same cave and repoints
its own 8 references. All three blocks are **level-triggered**, guarding on their own state rather
than on one shared edge — the model-condition bit survives a savegame and the weapon-set bit does
not, so an edge-triggered hook would come back from a load with the two disagreeing for good. See
[`docs/production-model-condition.md`](docs/production-model-condition.md) §10-11.

It installs one because it implements one *trigger*, not because bits are scarce: 591 names sit in
a 19-dword mask, leaving 17 slots, and savegames store conditions as a **list of names** rather
than a bit layout, so the count does not affect them. **If you only need more conditions and not
more triggers, you probably need no patch at all** — the stock table already carries 75 `USER_*`
conditions with no engine behaviour of their own, of which Edain references 49, leaving ~26 free.

> **Every peer must run the same patched binary.** The bit lives on the logic-side `Object` and is
> part of what the engine CRCs, so a patched and an unpatched client desync as soon as a building
> starts producing, and replays do not cross. That is stricter than the other bundled patches,
> which are data-shape changes.

`ReplayOutcomePatch()`. **No parameters** — there is one moment a recorded game ends and one
state to write at it. It retargets the five-byte `call writeToFile` at `0x0077F98B`, inside
`RecorderClass::updateRecord`'s `MSG_CLEAR_GAME_DATA` branch — the consumer every ending
converges on, since the message itself has **thirteen** emitters and a quit and a finished game
use different ones — into a `.rpout` cave that walks `TheVictoryConditions`' player list and
`fwrite`s one 23-byte chunk per player to the recorder's own `FILE*`: order type `0x7D0`, the
player's `m_playerIndex` in the chunk's number field, then two Integers (outcome
0 undetermined / 1 victorious / 2 defeated, and the frame that player was defeated on).
`sage_replay.winner.recorded_outcomes` reads them back and `infer_winner` prefers them over the
concession heuristic outright. See [`docs/replay-outcome.md`](docs/replay-outcome.md).

> **This one does not need every peer.** The cave writes to a file the client already owns and
> injects nothing into the message stream, so a patched and an unpatched client stay in sync and
> replays still cross. That is the opposite of `production-condition`, whose bit is CRC'd.

`SkirmishReplayPatch(modes=(2,), rename="all")`. **`modes` are the `MSG_NEW_GAME` game modes to
record on top of the stock `{1, 5}`**; 2 is the one the skirmish setup screen emits, and a mode
the engine already records is refused rather than silently accepted. Two edits, both inside the
recorder: the nine-byte whitelist tail at `0x0077F910` (`cmp eax, 5` / `jne`) becomes a jump into
a `.rpskir` cave that tests 5 plus the table and lands back on the recorder's own accept
(`0x0077F919`) or reject (`0x0077F9DD`); and the `call` at `0x0077EA45` that asks for the file's
base name is retargeted to a second routine that writes `YYYY-MM-DD HH-MM-SS <map>`.

**`rename="all"` (the default) renames every recording**, so no two replays collide and a file
can be handed to someone as-is. `rename="added"` renames only the modes `modes` enables and
tail-jumps to the stock helper otherwise, leaving network recordings byte-identical. The trade
is the replay menu's Save Replay button — see Status. See
[`docs/skirmish-replay.md`](docs/skirmish-replay.md).

> **Do not read `RecorderClass::m_gameMode` from inside `startRecording`.** `updateRecord`
> caches the mode there, but `startRecording`'s first act is `reset()`, which overwrites it with
> the sentinel 9 (`0x0077D7D2`) before the file is named. The mode is `startRecording`'s own
> second argument, `[ebp+0x0C]` — the value it writes into the header. This cost a build.

> **Also client-local, and it composes with `replay-outcome`.** The two hook opposite ends of
> `RecorderClass::updateRecord` — the `MSG_NEW_GAME` whitelist and the `MSG_CLEAR_GAME_DATA`
> `writeToFile` call — and neither reads what the other writes. Applied together, a skirmish
> records **and** names its winner, which is the only way `sage_replay` can resolve a game
> against an AI at all: the concession heuristic needs orders, and an AI issues none.

`UniqueProductionIdPatch()`. **No parameters** — there is one id mint and one right answer. It
rewrites the ten bytes of `ProductionUpdateInterface::requestUniqueUnitID` in place (ten for ten,
so no hook and no displaced instruction) to draw from a four-byte counter in a `.prodid` section
instead of the per-producer one at `ProductionUpdate+0x30`. The first id minted is still 1, and 0
is still never minted — which matters, because 0 is what an idle hero's revive entry holds in the
field the id is matched against. See [`docs/unique-production-id.md`](docs/unique-production-id.md).

`TerrainResourceExpPatch(keyword="GiveNoXP")`. **One keyword**, and the default is the name the
stock `AutoDepositUpdate` already gives the same field, so a mod writes one keyword for one concept
across both income modules. Three edits and a `0xC5`-byte `.trexp` cave: the constructor's two
`Bool` stores become `and dword [esi+0x14], 0` plus the same `Visible` store — eight bytes for
eight, and the `and` clears the new field on the way past, so the default costs nothing; the
field-parse table is rebuilt in the cave with a ninth row, which is **one** 4-byte repoint because
the table has exactly one reference and is read through its terminator rather than a count; and a
6-byte hook on the experience block runs `AutoDepositUpdate`'s own gate, `cmp byte
[ModuleData+off], 0` / `jne <past the grant>`, instruction for instruction. See
[`docs/terrain-resource-exp.md`](docs/terrain-resource-exp.md).

> **Every peer must run the same patched binary**, and a mod using the keyword cannot run without
> it at all — an unknown field in a known block is an INI parse error, not a warning. See Status.

### Composing patches

**Any subset of the bundled patches applies in any order**, and a patch is only considered done
when it holds that. `apply_patches` takes a list precisely so they can be stacked:

```sh
sage-patch apply commandset-limit --count 64 --in game.dat.backup --out game.dat
sage-patch apply cah-factions --sides Rohan,Lothlorien --in game.dat --out game.dat
```

Three rules make that work, in decreasing order of how mechanically they hold:

| rule | enforced by | if broken |
|---|---|---|
| Allocate a cave with `allocate_section` (never a fixed RVA) and find it again with `find_section` | the helper — a patch that uses it cannot get this wrong | the section table comes out unsorted when another patch's cave is already present |
| Do not edit bytes another patch edits | not prevented, but `apply_byte_patch` asserts the original bytes first | the second patch to reach the site **raises**; nothing is silently corrupted |
| Do not derive your output from bytes another patch rewrites | nothing — this is the one the framework cannot catch | both orders "succeed" and disagree; declare the dependency in the docstring instead |

No bundled patch touches another's bytes or reads what another writes, and all three allocate their
cave the same way — so any order produces binaries that differ only in which cave landed first
(and therefore in the pointers to it), all verifying clean.

The one pair worth naming: `commandset-limit` and `ai-revive-gate` both edit
`BuildAssistant::canMakeUnit` — the hook at `0x7950ce` (6 bytes) and the AI scan bound at
`0x7950e2` (4 bytes), 20 bytes apart, no intersection. `ai-revive-gate`'s cave jumps only to
`0x79502a`, `0x7950dc` and `0x7950df`, all below the bound, so neither reads what the other writes.
[`tests/sage_patch/test_ai_revive_gate.py`](../tests/sage_patch/test_ai_revive_gate.py) asserts
both halves of that.

Placement being computed rather than hardcoded costs nothing: on an unpatched image
`next_section_rva` returns exactly the `0xAD3000` that `commandset-limit` used to name as a
constant, so a lone `commandset-limit` build still puts `.cmdext` where it always did.

> **Why 127 and not more.** Six patch sites encode the limit as a *signed 8-bit* immediate
> (`6a NN` push, `83 fa NN` / `83 fb NN` / `83 7d f8 NN` cmp). At 128 the byte `0x80` decodes as
> `-128`, and one of those pushes supplies `rep stosd`'s counter — the constructor would zero ~4
> billion dwords. Going higher means re-encoding those six as imm32 (3 bytes longer apiece), which
> no longer fits in place and needs relocated code, not a byte patch.

Tests live in [`tests/sage_patch/test_patching.py`](../tests/sage_patch/test_patching.py) and
[`tests/sage_patch/test_ai_revive_gate.py`](../tests/sage_patch/test_ai_revive_gate.py), including
a byte-identity check that `count=64` reproduces the shipped `game.dat`.

> **Rebuild `engine/game.dat` once after this change.** `commandset-limit` now writes a 15th
> Phase-1 edit (the AI scan bound), so a `count=64` build no longer matches an `engine/game.dat`
> produced before it, and the byte-identity check will fail until the artifact is rebuilt from
> `game.dat.backup`.

## Layout

| path | what |
|------|------|
| [`engine/`](engine/) | thin build CLI ([`patch.py`](engine/patch.py), over the framework), verifiers, the clean input `game.dat.backup`, and the shipped `game.dat`. Start at [`engine/README.md`](engine/README.md). |
| [`docs/commandset-button-limit.md`](docs/commandset-button-limit.md) | full RE writeup: how the limit is enforced, the object layout, every patch site, and how to raise it to N. |
| [`docs/push-visible-command-range.md`](docs/push-visible-command-range.md) | the paging mechanism + the `start+count ≤ N` rule (and the exact crash it prevents). |
| [`docs/max-player-count.md`](docs/max-player-count.md) | why a map caps at 20 sides (`MAX_PLAYER_COUNT`), the map census, and a costing of what raising it would take. **Assessed, not attempted.** |
| [`docs/upgrade-mask-limit.md`](docs/upgrade-mask-limit.md) | why the engine caps at 1152 upgrades, and why passing it corrupts neighbouring masks instead of crashing. **Assessed, not attempted.** |
| [`docs/cah-faction-limit.md`](docs/cah-faction-limit.md) | full RE writeup for `cah-factions`: the nine-side enum, the three gates that read its mask, every repointed site, and the two cheaper-but-cruder alternatives that were rejected. |
| [`docs/ai-revive-gate.md`](docs/ai-revive-gate.md) | full RE writeup for `ai-revive-gate`: `BuildAssistant::canMakeUnit`'s two branches, why only one checks `NeededUpgrade`, the three AI-only call sites that make the fix player-safe, the slot-accounting argument, and what the patch deliberately leaves alone. |
| [`docs/production-model-condition.md`](docs/production-model-condition.md) | full RE writeup for `production-condition`: the `ModelConditionFlags` anatomy (591 names in 19 dwords, 17 spare), why the 74-byte `xfer` window makes **exactly one** new condition free, the terminator-driven parser that needs no patch, the ten count bounds, `ProductionUpdate`'s queue, and why `update` never sleeping is what makes a single entry hook correct. Settles the `Object`-vs-`Drawable` question left open by `ai-revive-gate`. |
| [`docs/replay-outcome.md`](docs/replay-outcome.md) | full RE writeup for `replay-outcome`: the `VictoryConditions` layout and its defeat latch, `RecorderClass`'s file handle and chunk writer, why the recordable range being the *network* range rules out injecting a message, the thirteen emitters of `MSG_CLEAR_GAME_DATA` and why the hook belongs on the consumer instead, and the header fields that stay consistent. |
| [`docs/skirmish-replay.md`](docs/skirmish-replay.md) | full RE writeup for `skirmish-replay`: the `MSG_NEW_GAME` branch that is the whole decision to record, the game-mode enum recovered from its emitters (and why 2 is skirmish), why `startRecording`'s non-network path and the engine's playback predicates already handle it, the three helpers behind the file name and the second caller that makes the *call site* the patchable thing. |
| [`docs/terrain-resource-exp.md`](docs/terrain-resource-exp.md) | full RE writeup for `terrain-resource-exp`: the module's field table and the two padding bytes the new `Bool` goes in, the experience block at the tail of `update` and why its first instruction is the right thing to hook, the constructor rewrite that buys the default for nothing, and `AutoDepositUpdate::GiveNoXP` — the stock field, and stock gate, this reproduces. |
| [`docs/hero-mana.md`](docs/hero-mana.md) | full RE writeup for `hero-mana`: why `UnitCost` is inert on a hero (the shared no-horde branch, at three sites), the activation path and the six callers of `canUseSpecialPower` that make one hook reach the AI too, `Object+0x74` as the object id, the `SpecialPower` table's two references and the `0x88 → 0x94` struct growth, and the compute-on-read pool that needs no per-frame, init, destroy or savegame hook. |
| [`docs/unique-production-id.md`](docs/unique-production-id.md) | full RE writeup for `unique-production-id`: the path a hero recruit takes from `doCommandButton` to `ProductionUpdate::queueCreateUnit`, the per-player revive manager at `Player+0x758` and the `ProductionID` it keys entries on, where the money moves relative to the failure edge, and why the fix belongs at the mint rather than at the check or as a refund. |
| [`docs/command-point-upkeep.md`](docs/command-point-upkeep.md) | full RE writeup for `command-point-upkeep`: the one reader of `ResourceModifierValues` and the three properties upkeep inherits from it, the command-point bookkeeping at `Player+0x60`, why a `PlayerTemplate` cannot hold the numbers (no hole, 24 size literals, and a parse-time `this` that is a stack temporary) and why its `NameKeyType` can, the one-reference field table, and the cdecl vararg rule that decides where the palantir hook goes. |
| [`docs/runtime-re-workflow.md`](docs/runtime-re-workflow.md) | the static+dynamic RE method (Ghidra, Cheat Engine, INI field tables) used to recover these offsets, with the verified `Player`/`ThingTemplate` layouts. |
| [`docs/message-stream.md`](docs/message-stream.md) | `TheMessageStream` (`0x00DE6398`), `appendMessage` (vtable `+0x48`) and all eleven `append*Argument` helpers - the order-injection path - plus the authoritative 147-name `GameMessage::Type` network enum recovered from `getCommandTypeAsAsciiString`. Closes OPEN 10 of [`order_space_map.md`](../sage_replay/order_space_map.md). |
| [`docs/engine-globals.md`](docs/engine-globals.md) | the 88 named engine singletons (`TheGameLogic`, `ThePlayerList`, `TheThingFactory`, `TheUpgradeCenter`, ...), the `PlayerList` layout and the `Player` economy/identity offsets. The starting point for any live-memory work. |
| [`docs/live-object-model.md`](docs/live-object-model.md) | enumerating live objects: `TheGameLogic`'s id table, the `Object` layout (template, transform, position, horde links) and the body module holding health. Solves unknowns 1-2 of [`live-api.md`](../docs/live-api.md). |
| [`docs/module-reference.md`](docs/module-reference.md) | every engine module, its INI fields and their compiled-in defaults - 330 modules, 2658 fields, 97% of them typed. Generated by [`scripts/module_defaults.py`](scripts/module_defaults.py); `module-reference.json` is the same data machine-readable. |
| [`docs/ini-types.json`](docs/ini-types.json) | everything a field's type alone cannot say: the 200 INI block types the loader dispatches on (`Object`, `Weapon`, `Locomotor`, `GameData`, ...) with 4247 fields of their own, the members behind every enum and flag type, the lookup lists, and the keywords of every nested sub-block. Same generator. |
| [`scripts/build_wiki.py`](scripts/build_wiki.py) | renders those files into a browsable static site under `build/wiki/` - a page per module and per block type, plus the type and enum pages. Field tables take values, check them against the field's type and write them into a copyable INI block, and `check.html` validates a whole pasted block the same way. Fields the engine parses as plain strings are annotated with what `sage_ini` says they name (`&rarr; Upgrade`, `&rarr; Object`), the one thing on the site that is modelled rather than read from the binary. |
| [`ghidra_scripts/`](ghidra_scripts/) | headless Ghidra analysis scripts + `run_ghidra.bat` runner (needs JDK 21). |
| [`scripts/`](scripts/) | standalone capstone/pefile analysis helpers used during RE. |

## Module reference

```sh
python scripts/module_defaults.py game.dat \
    --json docs/module-reference.json \
    --markdown docs/module-reference.md \
    --enums docs/ini-types.json         # needs your own game.dat
python scripts/build_wiki.py            # -> build/wiki/index.html, no game.dat needed
```

A field's type is its parse function, and those are identified from what the code does:
the constant a real is scaled by (`pi/180` is degrees in, radians out), the range the
parser complains about (`expected > 0`), the name array a token is resolved against, the
field table a nested block hands to the INI reader.

Block types are found the same way. The loader dispatches a block on `{keyword, parser}`
pairs in the data sections; a candidate is kept only when its parser really does hand a
field table to the INI reader, which is what makes it a block type rather than a string
that happens to sit next to a function pointer. Where the parser also allocates and
constructs its instance, the same constant tracking recovers that block's defaults.

The site is a build artefact and is not committed; the JSON it reads is.

## Reproduce the build

```sh
cd engine
OUT=game.dat python patch.py   # clean game.dat.backup -> N=64 game.dat  (COUNT=N for another limit)
python verify.py && python finalcheck.py
```

## Key addresses (VA, ImageBase 0x400000)

Named in [`addresses.py`](addresses.py) where a patch needs them; this is the quick index.

field-parse table `0xc4f3d8` · `parseCommandButton` `0x80c9e1` · ctor `0x80c949` ·
alloc `0x720298` · `getCommandButton` `0x80c837` · new `.cmdext` table `0xed3000` (on a clean
image; the RVA is computed, so it moves up if another patch's cave is already there) ·
ControlBar singleton `0xde7744` (fixed 33-slot arrays at `+0xdc` / `+0x160`) ·
paging-crash site `0x75d244`.

`ModelConditionFlags` name table `0xd9fad8` (591 entries, 19 dwords wide) · `getBitCount`
`0x444df5` · INI name→bit parser `0x4b3b5b` · `xfer` `0x4b8d87` · validating setter `0x8e2c1f` ·
`Object` model-condition mask `+0x10c` · `Object::onModelConditionFlagsChanged` `0x68b53c` ·
`ProductionUpdate::update` `0x8a1b9f` (vtable `0xc67e2c` slot 0) · its queue head `module+0x28`.

`TheBuildAssistant` `0xde8200` (vtable `0xc307d8`) · `BuildAssistant::canMakeUnit` `0x794f38`
(vtable `+0x68`, five call sites) · the `+0x64` gate `0x793ecb` that reaches it by a virtual
self-call at `0x793f56` (14 callers, incl. the ControlBar's `0x940a3b`/`0x940b84`/`0x942ea9`/
`0x942f3f` and `queueCreateUnit`'s `0x8a1205`) · its accept path `0x7950ad` ·
its upgrade gate `0x79502a` · its revive branch `0x7950ce` · slot-count bump
`0x7950dc` · next-slot step `0x7950df` · AI scan bound `0x7950e2` · `GUICOMMAND_REVIVE` = 46
(name table `0xda4d10`, 61 entries) · the pre-production gate `0x793ecb` (vtable `+0x64`), which
is how `queueCreateUnit` reaches `canMakeUnit`.

`TerrainResourceBehavior` `ModuleData` ctor `0x88525d` (`sizeof` `0x24`, free padding `+0x16`/`+0x17`) · its two `Bool` defaults `0x88528b` · `buildFieldParse` `0x8852b8`, its `push` immediate `0x8852bf` · field-parse table `0xc5fd78` (8 rows, terminator `0xc5fdf8`, **one** reference) · `update` `0x8854d3` (slot 0 of `0xc5fbcc`), its `ModuleData` slot `[ebp-0x18]` · deposit `0x7b18b8` at `0x8856b0` · the experience block `0x88573c`-`0x885765`, rejoin `0x88576a` · `Object` `m_experienceTracker` `+0x26c` · `ExperienceTracker::isTrainable` `0x79d322` · `addExperiencePoints` `0x79d833` (15 call sites) · `AutoDepositUpdate`'s stock `GiveNoXP` gate `0x89dd16` (field at its `ModuleData+0x20`) · `INI::parseBool` `0x42e558` · `MultiIniFieldParse::add` `0x42b8d7`.

`ProductionUpdateInterface` vtable `0xc67db0` (the subobject at `module+0x20`) ·
`requestUniqueUnitID` `0x8a18fa` (slot `+0x08`) · `queueCreateUnit` `0x8a11d2` (slot `+0x20`) ·
its money withdrawal `0x8a12a2` and revive failure edge `0x8a13d8` · per-producer id counter
`module+0x30`, seeded by the ctor `0x8a17d8` · `ReviveMgr` `Player+0x758` (`0xe8`-byte entries;
start frame `+0xa8`, `ProductionID` `+0xb4`) · `startRevive` `0x7812b2` ·
`findByProductionID` `0x7808db` · `findByIndex` `0x7808ab` · `canRevive` `0x780c46` ·
`cancelRevive` `0x780c64`.

`TheVictoryConditions` `0xde89ac` (vtable `0xc4f108`, `sizeof` `0x94`) · `Player *m_players[20]`
`+0x18` · `Bool m_isDefeated[20]` `+0x70` · `update` `0x808f53` and its defeat latch `0x80908a` ·
`hasAchievedVictory` `0x808aa8` (slot `+0x38`) · `hasBeenDefeated` `0x80953c` (slot `+0x40`) ·
`Player` `m_playerIndex` `+0x54`, `m_isObserver` `+0x35a`, `m_defeatedFrame` `+0x4cc`,
`m_isDefeated` `+0x754` · `TheRecorder` `m_file` `+0x10` / `m_mode` `+0x1c` (RECORD 0, PLAYBACK 1,
NONE 2) · `writeToFile` `0x77d8fc` · `updateRecord` `0x77f8b0` (records `0x1D` plus
`0x3e8 < type < 0x7cf`) · `stopRecording` `0x77d8c8` · `TheCommandList` `0xde639c` ·
`GameLogic::clearGameData` `0x625e36`, hook site `0x625e84`, `0x1D` append `0x625e91` ·
`fwrite` `[0xbd053c]` · `fflush` `[0xbd065c]`.

`RecorderClass::startRecording` `0x77ea03` (only caller `0x77f96e`) · `m_gameMode` `+0xed4`
(stored at `0x77f923`) · `updateRecord`'s `MSG_NEW_GAME` branch `0x77f8d1`, the game-mode
whitelist `0x77f910` (9 bytes, accepts 1 and 5), accept `0x77f919`, reject `0x77f9dd` ·
`GameLogic::startNewGame` `0x77948e`, `m_gameMode` `TheGameLogic+0x110`, coarse game type
`+0x114` (set to 3 at `0x779f20`) · the skirmish start handler `0x9287d9` (mode 2 at `0x928817`)
· `TheGameInfo` `0xde892c` · `TheSkirmishGameInfo` `0xde8930` (ctor `0x628b3a`, `sizeof` `0xe9c`)
· `GameInfo::m_map` `+0x40`, `getMap` `0x627692`, `setMap` `0x801c46` · `getReplayDir` `0x77de6f`
· `getLastReplayFileName` `0x77defd` (2nd caller `0x817e49`) · `getReplayExtension` `0x77dee3` ·
the name call site `0x77ea45` · `UnicodeString::UnicodeString(const WideChar *)` `0x437770` ·
`swprintf` `[0xbd0490]` · `GetLocalTime` `[0xbd01d4]` · `_wfopen` `[0xbd052c]`.
