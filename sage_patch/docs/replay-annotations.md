# Writing the score screen into a replay — reverse-engineering notes

The RE behind [`patches/replay_annotations.py`](../patches/replay_annotations.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-15.

[`replay-outcome`](replay-outcome.md) proved a recording client can write facts the order stream
cannot carry. This is the second record in that channel, and the one with the best value per
byte: the engine keeps a full **`ScoreKeeper` per player** — units and structures built, lost and
destroyed, money earned and spent — and the replay never sees any of it.

## TL;DR

- The `ScoreKeeper` is **embedded at `Player+0x3DC`**, not a pointer. 107 `lea reg, [reg+0x3DC]`
  sites in `.text` hand that address to methods clustered in `0x0079DB00`–`0x0079DD00`.
- **The cross-check that pins the base**: `0x3DC + 0xF0 = 0x4CC`, and `Player+0x4CC` is the
  defeat frame `replay-outcome` already writes and has runtime-verified. The shipped patch has
  been reading a `ScoreKeeper` field all along without naming it.
- Six of the counters are **contiguous** — `Int[20]` units destroyed, units built, units lost,
  `Int[20]` structures destroyed, structures built, structures lost — so the cave copies all 44
  dwords with one `rep movsd` instead of 44 loads.
- The two `Int[20]` arrays are indexed by the **victim's `m_playerIndex`** (§2.2), which makes
  them a **kill matrix**: not "units destroyed" but *units of player j destroyed by player i*.
- The `0x1D` branch has exactly two calls and `replay-outcome` owns the first, so this patch
  takes the second — the `call stopRecording` at `0x0077F992`. Its chunks land *after* the
  `0x1D` marker, at the same frame, which keeps the header's `num_timecodes` cross-check intact.
- Nothing enters the simulation and nothing crosses the network, so an unpatched peer is
  unaffected and the two patches compose in either order.

## 1. Where the score lives — `ScoreKeeper` at `Player+0x3DC`

### How it was found

Not from the score screen. The engine carries a **stats-file writer** — the Generals-lineage
`StatsCollector` — whose column header is written at `0x00819C46` and whose sample row is written
at `0x00819E12`. The header pushes 19 literal column names; the last eight are at
`0xC5033C`–`0xC503FC`:

```
ScoreKeeper_BuildingsLost   ScoreKeeper_BuildingsBuilt   ScoreKeeper_BuildingsDestroyed
ScoreKeeper_UnitsLost       ScoreKeeper_UnitsBuilt       ScoreKeeper_UnitsDestroyed
ScoreKeeper_MoneyEarned     ScoreKeeper_MoneySpent
```

and the sample row reaches them through the local player:

```asm
00819f64  mov  eax, [0xde4928]      ; ThePlayerList
00819f69  mov  eax, [eax + 0x10]    ;   ->m_localPlayer
00819f77  add  eax, 0x3dc           ; <-- the ScoreKeeper
00819f86  mov  eax, [eax + 8]       ; money spent
00819f95  mov  eax, [eax + 4]       ; money earned
00819fa7  call 0x79dc87             ; sum of the units-destroyed array
00819fb8  mov  eax, [eax + 0x70]    ; units built
00819fc7  mov  eax, [eax + 0x74]    ; units lost
00819fd9  call 0x79dc5d             ; sum of the structures-destroyed array
00819fea  mov  eax, [eax + 0xc8]    ; structures built
00819ffc  mov  eax, [eax + 0xcc]    ; structures lost
```

Each value is written as a delta against a baseline the collector keeps (`[ebx+0x30]`…), which is
also the proof these counters are **live and continuously updated**, not computed at the end.

### The layout

| offset | field | evidence |
|---|---|---|
| `+0x04` | money earned | the sample row, against the `MoneyEarned` column |
| `+0x08` | money spent | the sample row, `MoneySpent` |
| `+0x20` | `Int[20]` **units destroyed, per victim** | incremented at `0x0079F3B2` (§2) |
| `+0x70` | units built | the sample row |
| `+0x74` | units lost | incremented at `0x0079F52C`, bulk-added at `0x0079F619` |
| `+0x78` | `Int[20]` **structures destroyed, per victim** | incremented at `0x0079F36A` |
| `+0xC8` | structures built | the sample row |
| `+0xCC` | structures lost | incremented at `0x0079F4E2` |
| `+0x108` | **units alive** | decremented (floored at 0) at `0x0079F525` |
| `+0x10C` | **structures alive** | decremented (floored at 0) at `0x0079F4DB` |
| `+0x110` | `Bool` scoring enabled | gates every increment; setters `0x0079DC9E`/`0x0079DCAB` |
| `+0xF0` | end / defeat frame | `= Player+0x4CC`; getter `0x0079DC0C` |
| `+0x118`, `+0x170` | parallel `Int[20]` copies | incremented in lockstep with `+0x78`/`+0x20` |
| `+0x16C`, `+0x1C4` | parallel loss counters | incremented with `+0xCC`/`+0x74` |

**The live counts at `+0x108`/`+0x10C` are a bonus** the column names never mention: the army and
base size at the moment the recording ends, for free.

**Do not call the array getters.** `0x0079DC87` (units destroyed) and `0x0079DC91` (structures at
`+0x170`) both go through the summing helper at `0x0079DC74`, which *ignores the array pointer
its caller pushes* and always sums `this+0x20`:

```asm
0079dc74  push 0x14
0079dc78  add  ecx, 0x20            ; the pointer at [esp+4] is never read
0079dc7c  add  eax, [ecx]
0079dc84  ret  4
```

So the `+0x170` getter returns the `+0x20` sum. The sibling helper at `0x0079DC49` (used for
`+0x78` and `+0x118`) reads its argument correctly. The cave sidesteps the whole question by
copying the fields, not calling anything.

## 2. What the counters mean — the accounting functions

Column names say what a counter is called. These two say what it counts.

### 2.1 `addObjectDestroyed` (`0x0079F303`)

```asm
0079f308  mov  eax, [0xde412c]
0079f30d  cmp  byte [eax + 0x98], 0     ; scoring live at all?
0079f321  push 0x4c
0079f325  call 0x44ddec                 ; Object::testStatus(0x4C) -> bail if set
0079f335  call 0x68b678                 ; the destroyed object's owning Player
0079f33a  mov  esi, [eax + 0x54]        ; <-- m_playerIndex of the VICTIM
0079f33d  mov  eax, [ebx + 4]           ; its ThingTemplate
0079f340  add  eax, 0x108               ;   +0x108: the KindOf-ish name keys
0079f354  call 0x70b8c7                 ; is it a structure?
0079f36a  inc  dword [edi + esi*4 + 0x78]    ;   structures destroyed[victim]
0079f36e  inc  dword [edi + esi*4 + 0x118]
0079f396  call 0x7640c1                 ; else: TheGameData+0x1168, the ObjectsThatScore filter
0079f3b2  inc  dword [edi + esi*4 + 0x20]    ;   units destroyed[victim]
0079f3b6  inc  dword [edi + esi*4 + 0x170]
```

Three facts fall out at once:

1. **The array index is `Player::m_playerIndex`** — read from the victim's own `Player`, the same
   field `replay-outcome` writes into a chunk's number. So an entry lines up with a replay slot by
   the rule `sage_replay` already applies to every order, with no new assumption.
2. **"Destroyed" means killed by this player**, structures and units split by the template's own
   name keys, and units filtered by `ObjectsThatScore` — the `GameData` field whose ini name sits
   at `0xC0187C`. Rubble, effects and non-scoring props never reach a counter.
3. `+0x118`/`+0x170` are **duplicates**, incremented in the same breath. Presumably one is
   resettable (WOTR per-battle scoring); the patch records only the primaries.

### 2.2 `addObjectLost` (`0x0079F486`)

The mirror, on the owner rather than the killer: the same `TheGameLogic+0x98` gate, the same
`testStatus(0x4C)`, the same structure/unit split and the same `ObjectsThatScore` filter, then
`inc [this+0xCC]` for a structure or `inc [this+0x74]` for a unit — each preceded by the
floored decrement of the live count at `+0x10C`/`+0x108`.

**One thing is not mirrored.** `addObjectDestroyed` tests `[this+0x110]` — the *killer's*
scoring-enabled flag — at `0x0079F35D` and `0x0079F3A9`, before every increment.
`addObjectLost` never reads `+0x110` at all.

### 2.3 Why `lost` never equals the enemy's `destroyed`

A readback shows the two ledgers close but not equal, always in the same direction
(`lost >= enemy's destroyed[owner]`). That is structural, not measurement error: a loss and a
kill are written by different code on different paths, and there are strictly more ways to
reach the first.

**The call census.** `addObjectDestroyed` has **exactly one** caller in the image,
`0x00695738`. `addObjectLost` has **six** — `0x006956DE`, `0x0079487A`, `0x00883EE5`,
`0x00883F50`, `0x00884028`, `0x008A5D9B` — plus a seventh path, the bulk add at `0x0079F60E`
(called from `0x008837B6`), which charges a whole horde to `+0x74` in one instruction.

**The guards.** Both calls appear in one death handler, `0x006955BC`, where `edi` is the
victim's `Player` and `ebx` the killer's. The loss goes in at `0x006956DE`; three tests then
stand between it and the credit at `0x00695738`:

```asm
006956d1  test edi, edi
006956d3  je   0x6956e3        ; no victim owner -> no loss either
006956de  call 0x79f486        ; <-- LOSS RECORDED
006956e8  call 0x68d7ab        ; a containment predicate on the killer
006956ef  jne  0x6957b2        ;   nonzero -> no credit
006956f5  cmp  ebx, edi
006956f7  je   0x6957b2        ;   killer's Player == victim's -> no self-credit
006956fd  test ebx, ebx
006956ff  je   0x695748        ;   no killer Player -> no credit
00695738  call 0x79f303        ; <-- KILL CREDITED
```

So **friendly fire and self-inflicted deaths credit nobody**, and **anything killed by the
world, a script or its own expiry credits nobody** — an expiring summon is a loss with a null
killer. Neither is a bug; the score screen is asking "what did *you* kill", not "what died".

**And the victims with no row.** The write loop walks `TheVictoryConditions->m_players`, so
only participating, non-observer seats get a record — but the destroyed arrays are indexed by
*any* `m_playerIndex`. `PlyrCreeps` (engine player 2, confirmed live) therefore appears as a
column in every kill matrix and never as a row, and its own kills against the players are
credited to a keeper no record carries. That is the largest single contributor to the gap on a
creep map, and it is why `destroyed_by_slot` drops out-of-range indices rather than guessing.

## 3. The hook — the second call of the `0x1D` branch

`replay-outcome` documents why every ending funnels through `RecorderClass::updateRecord`'s
`MSG_CLEAR_GAME_DATA` branch. That branch contains exactly two calls:

```asm
0077f981  or   dword [0xda570c], -1
0077f988  push esi
0077f989  mov  ecx, edi
0077f98b  call 0x0077d8fc      ; writeToFile(msg)   <-- replay-outcome owns this one
0077f990  mov  ecx, edi
0077f992  call 0x0077d8c8      ; stopRecording()    <-- and this patch takes this one
0077f997  lea  ecx, [edi+0x14]
```

**Why not share the first site.** The framework's composition rule is that two patches never edit
the same bytes ([`patcher.py`](../patcher.py)), and `apply_byte_patch` asserts the original bytes,
so the second patch to reach a shared site raises. Taking the `stopRecording` call keeps the two
patches disjoint — and the 20-byte fingerprint `replay-outcome` verifies covers
`0x0077F977`–`0x0077F98A`, which these five bytes also sit clear of. Both orders of application
verify; `TestInstalledBinary` measures exactly that on the real binary.

**Why the site is safe.** It is a 5-byte `call rel32`, so no instruction is displaced: the cave
tail-`jmp`s to `0x0077D8C8` and `stopRecording`'s own `ret` returns to `0x0077F997`. `ecx` is set
two bytes earlier and `pushad`/`popad` carries it across. The file is still open — closing it is
what `stopRecording` is about to do — so this is the last moment anything can be appended.

### The chunks land after the `0x1D` marker

`writeToFile` has already run, so the end-of-recording chunk is on disk before ours. That is a
real change from `replay-outcome`, and it is sound because:

- **the header still cross-checks.** `stopRecording` back-patches `num_timecodes` from
  `TheGameLogic->m_frame`, and our chunks carry that same frame, so `num_timecodes` still equals
  the last chunk's timecode and `parse_replay`'s consistency check passes unchanged;
- **`sage_replay` parses to end-of-file**, and `winner.py` finds the `0x1D` marker by type, not by
  position, so the point-of-view attribution is unaffected;
- and the alternative — hooking upstream of `writeToFile` — would mean either sharing
  `replay-outcome`'s bytes or displacing instructions inside its verified fingerprint.

## 4. The records

Both use `writeToFile`'s own chunk layout, and Integers only: the argument-type vocabulary every
existing reader already handles.

**`0x7D1` manifest**, once, first: `(schema version, kinds bitmask, writer id)`. It exists so that
absence is unambiguous — "this build does not record scores" is a different fact from "this game
scored nothing", and only the manifest can tell them apart.

**`0x7D3` player score**, one per player. At **schema v1** this was `1 + 5 + 44 = 50` Integers:
the schema version, the five scalars read individually, then the six contiguous counters copied
wholesale.

**Schema v2 appends eight more**, read off the `Player` rather than its keeper (§4.1), for
`58` Integers — 247 bytes per player, still inside the format's 255-values-per-pair ceiling.
Growing the record moved the section's `FILE*` slot from `+0xF8` to `+0x120` and the code from
`+0x100` to `+0x140`: the record now ends at `+0x117`, and a record that overran the handle
would corrupt it mid-loop, so the test suite asserts the gap.

The player number is `Player+0x54`, exactly as `replay-outcome` writes it, so
`ReplayFile.slot_index` maps the chunk with no new rule.

### 4.1 The v2 tail — what the keeper does not hold

| argument | field | source | why it is not derivable |
|---|---|---|---|
| 50 | `faction_name_key` | `Player+0x34` → `PlayerTemplate+0x10` | the **resolved** faction. The header's slot carries the *lobby* value, so a `Random` seat never resolves in it — and AI difficulty, contrary to §7's old claim, the header already records |
| 51 | `resources` | `Player+0x94` | the spendable balance. `money_spent` carries a setup charge never deducted from it (below), so only this says what a seat could afford |
| 52–53 | `power_points`, `power_points_total` | `Player+0x24`, `+0x1C` | spellbook economy; only `+0x24` falls on a purchase |
| 54–57 | `command_points_used`, `_cap`, `_bonus`, `_hard_cap` | `Player+0x68`, `+0x64`, `+0x6C`, `+0x70` | the army ceiling actually played under |

**Why four command-point fields and not one total.** `Player::getCommandPointsAvailable` computes
`min(base + bonus + <filtered extras>, hard)`, where the extras are a vector at `+0x80`/`+0x84`
whose entries carry an `ObjectFilter` that must be evaluated against the world. The cave calls
nothing, so it copies the four flat fields and lets the reader publish `min(cap + bonus, hard)`
as an explicit **lower bound** (`PlayerScore.command_point_ceiling`).

**Why `Player+0x3E0` is deliberately absent.** It is lifetime income and reads byte-identical to
`ScoreKeeper+0x04` on every sample — measured live 2026-08-16 at 1760/1760, 1800/1800, 1840/1840
across 130 frames. Recording it would duplicate a field.

**What that same measurement found about `money_spent`.** It sat unchanged at `5000` from before
the first order through frame 2798, while `units_built` stayed `0` and `resources` tracked
`starting purse + money_earned` exactly. So `money_spent` is **not** the sum of purchases: it
carries a setup charge. `resources` is what closes the books, and the pair together isolate the
charge. This is why the readback's "both players spent more than they earned" is two effects,
not one — a setup charge on both seats, plus (on a scripted map) money handed to the AI.

### Schema discipline

Integer 0 of every record is the version, a later schema **appends** arguments, and an argument
position once shipped never changes meaning. The reader takes whichever prefix a record carries:
the v1 prefix is required (a record shorter than it is malformed and is skipped), the v2 tail is
`| None` when absent, and a record from a *later* schema than the reader knows is read for the
part it does know. That is what keeps the corpus recorded under v1 readable.

### The order types cannot collide

`updateRecord` copies `0x1D` plus the open range `0x3E8 < type < 0x7CF`, and the
`GameMessage::Type` enum stops at `0x47B` ([`message-stream.md`](message-stream.md)). Everything
at `0x7D0`+ is unreachable for the engine. The block `0x7D0`–`0x7EF` is reserved for this channel;
`0x7D0` is the outcome record, `0x7D1` and `0x7D3` are this patch, and the registry is
append-only.

## 5. Reading them back

[`sage_replay/annotations.py`](../../sage_replay/annotations.py) is the reader:
`manifest(replay)` and `player_scores(replay)`, both returning empty for the entire existing
corpus rather than raising. `python -m sage_replay annotations <replay>` prints them, and
`aggregate` folds them into per-faction medians split by outcome — the question the counters exist
to answer being *what did the winners do differently*. A part-patched corpus keeps its own
denominator (`score_games`), so a metric never quietly divides by the faction's game count.

Schema handling is described in §4's *Schema discipline*; the reader's half of it is
`SCORE_FIELDS`, which carries each field's introducing version and is asserted field-for-field
against the patch's own table.

## 6. Status

**Schema v1 is play-tested; v2 is applied and verified but not yet recorded from.** A v1
recording (`annotation test.BfME2Replay`, 2026-08-16, Heubris, 20:47) produced exactly the
predicted shape: one `0x7D1` and one `0x7D3` per participating player at frame 6201, after the
`0x1D` marker, with `num_timecodes` still equal to the last chunk's timecode. The v2 tail has
been through apply → verify → detect and its emitted templates parse, but no match has been
recorded under it yet.

The patch ships unflagged - it
is not in `patches/experimental/` and does not set `Patch.experimental`, so `sage-patch apply`
prints no warning for it. That flag marks a patch that has not been exercised at scale; this one
is a single teardown-time write on a settled hook site, so it does not carry that warning. Not
being flagged is not a claim that it has been observed working - the open items below are open.

What is settled: the addresses hold their stock bytes in `game.dat`; apply → verify → detect
round-trips; both orders of composition with `replay-outcome` verify; the emitted templates parse
through `sage_replay`'s own chunk parser and reader; and the guard fingerprints refuse a build
whose layout moved.

### Open items

1. ~~**Record a match and read it back.**~~ **Done for v1** (see Status). The destroyed arrays
   reconcile with the opponent's losses to within a gap that §2.3 now explains structurally.
   Still unmeasured: `units_built` against what the score screen actually shows, which needs a
   screenshot of the same match. **Redo for v2** — nothing has been recorded under the new tail.
2. **Play a patched replay back in the game.** The playback reader (`0x0077DC91`) appends every
   chunk to `TheCommandList` except types `0x3E8` and `0x1D`, and `updatePlayback` (`0x0077E100`)
   reads by timecode — so chunks after the `0x1D` marker *are* read and *are* appended. An
   unhandled type should fall through every translator harmlessly, but that is an expectation, not
   a measurement, and it applies equally to `replay-outcome`'s chunks.
3. **Confirm `+0x108`/`+0x10C` against a live game.** They are read as live counts from the
   decrement sites alone; `sage_live` can watch them move.
4. **Establish what `+0x118`/`+0x170` reset on.** If one of them is per-battle rather than
   per-match, it is a second, finer record worth having in WOTR.

## 7. What else the block could carry

The catalogue this patch came out of, unbuilt, in the order worth building:

| type | record | what it answers | why it is not here yet |
|---|---|---|---|
| `0x7D2` | name dictionary | what every id in this file means, without the game that made it | needs a used-id bitmap on the write path |
| ~~`0x7D4`~~ | ~~setup truth~~ | — | **shipped in schema v2's `0x7D3` tail instead** (§4.1): the resolved faction is a per-player fact written in the loop that already has the `Player`, so a second record per player bought nothing. AI difficulty needed no patch at all — the replay header's slot already carries it, which this table previously got wrong |
| `0x7D5` | hero ledger | which hero, by name — the one content order static data cannot resolve | mid-game hook, so item 2 above gates it |
| `0x7D7` | periodic samples | economy and army curves over the match | mid-game, and needs the money/CP reads |
| `0x7D6` | object census | what every runtime `ObjectId` was; where things died | volume: needs a `KindOf` + owner filter |
| `0x7D8` | button press log | which button was pressed, disambiguating the overloaded `0x417` | largely redundant if `0x7D5` and `0x7D6` ship |

## Address index

`ScoreKeeper` at `Player+0x3DC` · accessor block `0x0079DB00`–`0x0079DD00` · summing helpers
`0x0079DC49` (correct) and `0x0079DC74` (ignores its argument) · array getters `0x0079DC5D`
(`+0x78`), `0x0079DC87` (`+0x20`), `0x0079DC67` (`+0x118`), `0x0079DC91` (`+0x170`, returns the
`+0x20` sum) · end-frame getter `0x0079DC0C` · `addObjectDestroyed` `0x0079F303` (increments
`0x0079F36A`, `0x0079F36E`, `0x0079F3B2`, `0x0079F3B6`) · `addObjectLost` `0x0079F486`
(`0x0079F4E2`, `0x0079F52C`; live-count decrements `0x0079F4DB`, `0x0079F525`) · bulk loss add
`0x0079F60E`.

Owner resolution `0x0068B678` · `Object::testStatus` `0x0044DDEC` (status `0x4C`) · the name-key
test `0x0070B8C7` against `0x00DE8294` / `0x00DE82B0` · `ObjectFilter::allow` `0x007640C1` ·
`ObjectsThatScore` at `TheGameData+0x1168` (ini name at `0xC0187C`) · scoring gate
`TheGameLogic+0x98`.

Stats-file writer: header `0x00819C46`, sample row `0x00819E12`, column literals
`0xC5033C`–`0xC503FC`.

Recorder: the hook `0x0077F992` (`call stopRecording`) inside the `0x1D` branch at `0x0077F977` ·
`stopRecording` `0x0077D8C8` · `writeToFile` `0x0077D8FC` · `m_file` `+0x10` · `m_mode` `+0x1C` ·
playback chunk reader `0x0077DC91` (append gate `0x0077DCED`) · `updatePlayback` `0x0077E100`.

`ThePlayerList` `0x00DE4928` · `TheGameLogic` `0x00DE412C` (frame `+0x40`) · `TheRecorder`
`0x00DE7CD8` · `TheVictoryConditions` `0x00DE89AC` · `TheGameData` `0x00DE4364` · `fwrite`
`[0x00BD053C]` · `fflush` `[0x00BD065C]`.
