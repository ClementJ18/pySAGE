# `MAX_PLAYER_COUNT` — why a map can only have 20 sides, and what raising it would cost

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified against the
clean `engine/game.dat.backup`.

**Verdict up front:** this is *not* a byte-patch job like
[the CommandSet limit](commandset-button-limit.md). `MAX_PLAYER_COUNT` is baked into the layout of at
least a dozen structures as a *mid-struct* fixed array, so raising it shifts the offset of every
member declared after it. That is a recompile-scale change, not an edit-in-place change. The one
genuinely cheap piece is `PlayerList` itself, and on its own it fixes nothing.

## The constant

`MAX_PLAYER_COUNT = 0x14` (20). ROTWK raised it from the `16` that
[Generals ships with](https://github.com/electronicarts/CnC_Generals_Zero_Hour/blob/0a05454d8574207440a5fb15241b98ad0b435590/Generals/Code/GameEngine/Include/Common/GameCommon.h#L107).

```
0x006a844e  8b442404   mov  eax, [esp+4]                  ; PlayerList::getNthPlayer(i)
0x006a8452  85c0       test eax, eax
0x006a8454  7c0b       jl   0x6a8461                      ; i < 0 -> NULL
0x006a8456  83f814     cmp  eax, 0x14                     ; <-- MAX_PLAYER_COUNT
0x006a8459  7d06       jge  0x6a8461
0x006a845b  8b448118   mov  eax, [ecx + eax*4 + 0x18]     ; m_players[i]
```

```
sizeof(PlayerList) = 0x68            allocated once, at 0x63c0ce: push 0x68 / call operator new
  +0x00  vptr
  +0x0c  vptr2                       (SubsystemInterface + Snapshot, multiple inheritance)
  +0x10  Player *m_local
  +0x14  Int     m_playerCount
  +0x18  Player *m_players[20]       0x18 + 20*4 = 0x68 exactly -> array is the LAST member
sizeof(Player)     = 0x778           each Player separately heap-allocated in the ctor loop
  Player +0x50  m_playerNameKey      (compared in findPlayerWithNameKey @0x6a8466)
  Player +0x54  m_playerIndex        (stored from the ctor arg @0x6b1ad4)
```

## Why the limit bites

`PlayerList::newGame` skips only the empty-name neutral side and gives every other side a slot,
**with no bounds check at all**:

```cpp
if (pname.isEmpty()) continue;            // neutral, already m_players[0]
Player* p = m_players[m_playerCount++];   // no clamp, no assert in release
```

So on a 4-player map the budget is `20 − 1 neutral − 4 Player_N − 4 Plyr*` = **11
`Skirmish<Faction>` slots**. Side 21 writes `m_players[20]`, one dword past the end of a 104-byte
heap block. Silent corruption, not a clean failure — which is why a surplus faction presents as
"not controllable by the AI" rather than a crash.

### Map census (585 maps: `Maps.big`, `_patch201maps.big`, `____edain_maps.big`, 0 parse errors)

| slots consumed | maps |
|---|---|
| ≤15 | 87 |
| 16 | 45 |
| 17 | 22 |
| 18 | 143 |
| 19 | 227 |
| **20 (full)** | **53** — 28 playable + 25 `libraries\` templates |

Nothing exceeds 20 anywhere. A distribution that stops dead at the constant with zero overshoot is
independent confirmation of the value. **28 playable maps are already full**, including
`map edain linhir`, `murmenalda`, `nancurir`, `carasIannath`, `castamirs island`, and most of the
`wor` set. The 227 maps at 19 have room for exactly one more faction.

### Not to be confused with `MPPositionList`

The `.map` chunk literally named `MPPositionList` is a *different* limit: one entry per multiplayer
start position, and it is **8 in all 585 maps**. `Player_1` / `SkirmishAngmar` are `SidesList`
entries, not `MPPositionList` entries. Raising the start-position count is a separate, much smaller
job:

| site | what |
|---|---|
| `.rdata 0xc7fbc8` | INI field-parse table, stride 16 — `displayName`, `description`, `supplyPosition`, `techPosition`, `Player_1_Start`…`Player_8_Start`, `InitialCameraPosition`. Same format as the CommandSet table we rebuilt into `.cmdext`. |
| `.data 0xda3038` | `TheKey_Player_N_Start` NameKey array, 8 entries × 8 bytes |
| `0x701b17` | `cmp dword ptr [ebp-4], 8`, beside the `MPPositionInfo` ctor at `0x701b3d` |

## The patch surface, in three tiers

Enumerated from the Generals source (`MAX_PLAYER_COUNT`: **27** struct members, **9** stack arrays,
**80** loop/comparison sites across 16 files, **32** other uses). BFME2 is a direct descendant, so
the shape carries over even where addresses do not.

### Tier 1 — cheap, and insufficient on its own

`PlayerList` is the one place where the array is the **last** member, so growing it only extends the
object. Nothing is laid out after it to shift.

| site | edit |
|---|---|
| `0x63c0ce` | `push 0x68` → `push (0x18 + N*4)` — the sole allocation |
| `0x6a8456` | `cmp eax, 0x14` — `getNthPlayer` bounds check |
| `0x6a8a0c` | `cmp ebx, 0x14` — ctor loop, `new Player(i)` ×N |
| `0x6a83f8` | `mov [ebp-0x10], 0x14` — dtor loop |
| `0x6a84db`, `0x6a84f3`, `0x6a850b`, `0x6a8523`, `0x6a8541` | `push 0x14 / pop edi` per-player update/reset loops |

Doing only Tier 1 gets you a `PlayerList` that can *hold* more players while every other subsystem
still indexes 20-element arrays with an index that can now reach N−1. That is strictly worse than
the current state: it converts a "faction doesn't work" bug into out-of-bounds writes across the
shroud, script, and scoring systems.

### Tier 2 — the blocker: mid-struct arrays

Every one of these embeds a `[MAX_PLAYER_COUNT]` array **in the middle** of its owner. Growing it
shifts the offset of every following member, so *every instruction that touches those later members
must be re-encoded* — and any `disp8` that crosses 127 grows to `disp32`, changing instruction
length and invalidating every branch across it.

| structure | arrays sized by `MAX_PLAYER_COUNT` | multiplicity |
|---|---|---|
| **`PartitionCell`** | `ShroudLevel m_shroudLevel[N]`, `Int m_threatValue[N]`, `Int m_cashValue[N]` — followed by `m_coiCount`, `m_cellX`, `m_cellY` | **per map grid cell** |
| **`PartitionData`** | `ObjectShroudStatus m_shroudedness[N]`, `m_shroudednessPrevious[N]`, `Bool m_everSeenByPlayer[N]` — followed by `m_lastCell` | **per object** |
| `Player` | `Bool m_attackedBy[N]`, `Int m_visionSpiedBy[N]` | per player (`sizeof` 0x778) |
| `SidesList` | `SidesInfo m_sides[N]`, `SidesInfo m_skirmishSides[N]` | singleton — **this is the map-side cap itself** |
| `ScriptEngine` | `m_objectCounts[N]`, `m_triggeredSpecialPowers[N]`, `m_midwaySpecialPowers[N]`, `m_finishedSpecialPowers[N]`, `m_completedUpgrades[N]`, `m_acquiredSciences[N]` | singleton |
| `InGameUI` | `SuperweaponMap m_superweapons[N]`, `ObjectList m_idleWorkers[N]` | singleton |
| `ScoreKeeper` | `m_totalUnitsDestroyed[N]`, `m_totalBuildingsDestroyed[N]`, `ObjectCountMap m_objectsDestroyed[N]` | per player |
| `MissionStats` | `m_unitsKilled[N]`, `m_buildingsKilled[N]` | per player |
| `VictoryConditions` | `Player *m_players[N]`, `Bool m_isDefeated[N]` | singleton |
| `ShroudStatusStoreRestore` | `std::vector<UnsignedByte> m_foggedOrRevealed[N]` | per save/restore |

`PartitionCell` is the expensive one twice over. Structurally it is mid-struct, so its accessors all
shift. And it is allocated **one per grid cell**, so at ~10 bytes of growth per extra player per
cell, a large map costs roughly **1–2 MB per additional player slot** — 20→32 would be on the order
of 20 MB of extra resident memory in a 32-bit address space that BFME2 already strains.

`SidesList::m_sides[MAX_PLAYER_COUNT]` deserves special note: it is the array the map's sides are
read *into*. Even with `PlayerList` widened, the map loader still cannot hold more than 20 sides
until this one grows too.

### Tier 3 — mask, serialization, and the wire

- **`PlayerMaskType`.** Generals guards it explicitly:
  ```c
  #if MAX_PLAYER_COUNT <= 16
      typedef UnsignedShort PlayerMaskType;
      const PlayerMaskType PLAYERMASK_ALL = 0xffff;
  #else
      #error "this is the wrong size"
  #endif
  ```
  ROTWK runs at 20, so EA widened this to 32-bit. Confirmed empirically: the dword `0x000FFFFF`
  — exactly 20 bits set — occurs **74 times** in `.text`. Every one is a `PLAYERMASK_ALL` that must
  be widened to `(1 << N) - 1`.
- **Savegame/replay format.** `ScriptEngine::xfer`, `ScoreKeeper::xfer`, `MissionStats::xfer`,
  `Player::xfer` and `PartitionCell::xfer` all serialize `MAX_PLAYER_COUNT`-sized blocks, and
  several write the count as a header field and hard-fail when it differs
  (`"MAX_PLAYER_COUNT has changed, ... size is now different"`). Raising N **breaks every existing
  save and replay**, by design.
- **Multiplayer.** Changing serialization and per-player state changes the version hash and the
  lockstep state. Patched clients desync against unpatched ones — same caveat as the CommandSet
  build, but with a far larger surface.

## Hard ceilings

Two independent caps, whichever binds first:

| cap | source | limit |
|---|---|---|
| **32 players** | 32-bit `PlayerMaskType`; a 64-bit mask would touch every mask operation in the engine | N ≤ 32 |
| **25 players** | `push 0x68` at `0x63c0ce` is `6a 68` (imm8). `0x18 + N*4` must stay ≤ 127, else it sign-extends negative and `operator new` gets a garbage size | N ≤ 25 |

The imm8 cap is the same encoding cliff as the CommandSet work, but far more tractable here: it is
**one** site, not five, so a `push imm32` (3 bytes longer) behind a small trampoline is plausible.
The 32-player mask ceiling is not negotiable without a wholesale change.

## Assessment

| | CommandSet 33→64 (done) | `MAX_PLAYER_COUNT` 20→N |
|---|---|---|
| arrays to grow | 1, and it was last in the object | ~12, most mid-struct |
| member offsets shifted | none | every member after each array, in ~12 structures |
| allocation sites | 1 | ~12, several per-cell / per-object |
| loop bounds | 14 edits | 80+ in the source; more after inlining |
| extra constants | — | 74 `PLAYERMASK_ALL` sites |
| memory cost | nil | ~1–2 MB per extra player on a large map |
| breaks saves/replays | no | yes, by design |

The CommandSet patch worked because the array sat at the end of one object and nothing else in the
engine knew its size. `MAX_PLAYER_COUNT` is the opposite: it is a shared layout constant, and the
offset-shift problem means there is no in-place edit that leaves the binary consistent. Realistically
this needs either full symbol recovery of every affected structure plus relocated code, or the
structures relocated wholesale behind trampolines — a project on the scale of the ControlBar
widening we scoped and declined, several times over.

## Cheaper alternatives worth pricing first

1. **Reclaim slots.** The four `Plyr*` sides (`Civilian`, `Creeps`, `Neutral`, `Wild`) appear on
   nearly every map. If any can be consolidated, each one recovered buys a faction on the 227 maps
   currently at 19, with zero binary risk. This is the highest value-per-effort option.
2. **Share `Skirmish<Faction>` sides.** If two factions can be driven from one AI side selected at
   runtime, the per-faction side cost drops.
3. **Accept 20 and gate content per map.** Ship faction subsets per map rather than every faction on
   every map.

## Verification notes

Verified directly against `game.dat.backup`: the `0x6a8456` bounds check, the `PlayerList` layout and
`0x68` allocation, the ctor/dtor loop bounds, `sizeof(Player) = 0x778`, the 74 `0x000FFFFF`
occurrences, `MPPositionList == 8` across 585 maps, and the side census.

Taken from the Generals source and **not yet individually confirmed at ROTWK addresses**: the Tier-2
structure inventory, the loop-site counts, and the `xfer` guards. Those are structural claims about a
common ancestor; each would need its own address before any patch work started.
