# Named engine subsystem globals — RotWK 2.01 `game.dat`

88 engine singletons, recovered statically 2026-07-29. ImageBase `0x400000`, no ASLR
assumptions beyond that — verify against your own build before trusting any address.

**Why this exists.** Almost every runtime question in [`live-api.md`](../../docs/live-api.md) §9
starts with "where is subsystem X". The engine answers that itself: each singleton is registered
by name at startup, so the binary contains a name→global-pointer table in plain sight. One scan
replaces a great deal of pointer-chasing.

## The idiom

`GameEngine::init` registers every subsystem through a common helper, pushing the singleton's
name and the **address of the global that will hold it**:

```asm
0063c0ce  push 0x68              ; sizeof(PlayerList)
0063c0d0  call 0x42f6e0          ; operator new
0063c0e3  call 0x6a89a5          ; PlayerList::PlayerList
...
0063c0f7  push 0xbfeca8          ; "ThePlayerList"
0063c100  call 0x4374e0          ; AsciiString ctor
0063c105  push 0x00de4928        ; &ThePlayerList   <-- the global
0063c10a  call 0x637ff0          ; initSubsystem
```

So the recovery is: find every `TheXxx\0` literal in `.rdata` (147 of them), anchor on the
`68 <literal>` push-immediate byte pattern, decode forward to the next push of a `.data`
address. 88 resolve. A linear disassembly sweep of `.text` does **not** work — it desyncs on
inlined data and recovers nothing; anchoring on the 5-byte `push imm32` encoding is what makes
this reliable.

**Independent confirmation:** this scan produces `TheMessageStream = 0x00DE6398`, which
[`message-stream.md`](message-stream.md) reached by a completely different route (counting
`mov ecx,[global]` sites feeding vtable slot `+0x48`). Two methods, same address.

## The table

Ordered by address. Dereference the global to get the singleton pointer — these are the
addresses **of the pointers**, not of the objects.

| global | subsystem | | global | subsystem |
|---|---|---|---|---|
| `0x00DE337C` | `TheSubsystemLegend` | | `0x00DE4AB8` | `TheRadar` |
| `0x00DE3604` | `TheArmorStore` | | `0x00DE4ACC` | `TheTerrainRoads` |
| `0x00DE3638` | `TheMetaMap` | | `0x00DE4AD4` | `TheGameState` |
| `0x00DE3670` | `TheEva` | | `0x00DE4AE4` | `TheLivingWorldBuildingTemplateStore` |
| `0x00DE367C` | `TheFXListStore` | | `0x00DE4AF8` | `TheLivingWorldPlayerTemplateStore` |
| `0x00DE369C` | `TheLocomotorStore` | | `0x00DE4B04` | `TheGameText` |
| `0x00DE36C4` | `TheGlobalLanguageData` | | **`0x00DE6398`** | **`TheMessageStream`** |
| `0x00DE36CC` | `TheLinearCampaignManager` | | `0x00DE63A4` | `TheSplineService` |
| `0x00DE370C` | `TheObjectCreationListStore` | | `0x00DE7724` | `TheTerrainTypes` |
| `0x00DE3744` | `TheFXParticleSystemManager` | | `0x00DE772C` | `TheGlobalWeatherSystem` |
| `0x00DE3B10` | `ThePlayerTemplateStore` | | `0x00DE77A0` | `TheSidesList` |
| **`0x00DE3B20`** | **`TheScienceStore`** | | `0x00DE7804` | `TheLuaScriptEngine` |
| `0x00DE3B2C` | `TheRankInfoStore` | | `0x00DE7860` | `TheAiOrdersManager` |
| `0x00DE3BAC` | `TheScriptEngine` | | `0x00DE78A0` | `TheCrateSystem` |
| `0x00DE3C08` | `TheLivingWorldManager` | | `0x00DE78A4` | `TheDamageFXStore` |
| `0x00DE3C14` | `TheAttributeModifierStore` | | `0x00DE7924` | `TheMineshaftPortalNetworkManager` |
| `0x00DE3D5C` | `ThePlayerAITypeSet` | | `0x00DE7958` | `TheAerialPathfinder` |
| `0x00DE3D84` | `TheCreateAHeroManager` | | `0x00DE7CD8` | `TheRecorder` |
| `0x00DE3F0C` | `TheAptPlayer` | | `0x00DE7D3C` | `TheMultiplayerSettings` |
| **`0x00DE412C`** | **`TheGameLogic`** | | `0x00DE8200` | `TheBuildAssistant` |
| `0x00DE42FC` | `TheAudio` | | `0x00DE8304` | `TheTeamFactory` |
| `0x00DE435C` | `TheTaintManager` | | **`0x00DE878C`** | **`TheSpecialPowerStore`** |
| `0x00DE4364` | `TheWritableGlobalData` | | `0x00DE87AC` | `TheLivingWorldCampaignManager` |
| `0x00DE4388` | `TheGameClient` | | `0x00DE8888` | `TheThreatFinderManager` |
| `0x00DE439C` | `TheModuleFactory` | | `0x00DE88A0` | `TheLivingWorldRegionEffectsManagerStore` |
| **`0x00DE45A0`** | **`TheUpgradeCenter`** | | `0x00DE897C` | `TheVictorySystem` |
| `0x00DE46A8` | `TheFireLogicSystem` | | `0x00DE89AC` | `TheVictoryConditions` |
| `0x00DE4704` | `TheExperienceLevelSystem` | | `0x00DE89B8` | `TheAwardSystemManager` |
| **`0x00DE4928`** | **`ThePlayerList`** | | `0x00DE8AC0` | `TheDelayedExperienceLevelGrantSystem` |
| `0x00DE4938` | `TheSkirmishAIManager` | | `0x00DE8AD0` | `TheCaveSystem` |
| `0x00DE4950` | `TheLivingWorldLogic` | | `0x00DE8B34` | `TheScoredKillEvaAnnouncerController` |
| `0x00DE4A1C` | `TheWeaponStore` | | `0x00DE8B3C` | `TheCrowdResponseStore` |
| **`0x00DE4A40`** | **`TheThingFactory`** | | `0x00DE8B60` | `TheHouseColorSystem` |
| `0x00DE4A64` | `TheFunctionLexicon` | | `0x00DE8B94` | `TheGameResultsQueue` |
| | | | `0x00DE8B98` | `TheGameStateMap` |
| | | | `0x00DE8BA8` | `TheActionManager` |

Plus the `LivingWorldAutoResolve*` stores (`0x00DE8B00`–`0x00DE8B80`) and
`TheArmyDefinitionManager` / `TheBaseTemplateLibrary` / `TheAITargetHeuristicLibrary`
(`0x00DE8BDC`–`0x00DE8BEC`), which are Living-World (campaign) only.

## `PlayerList` layout

From `PlayerList::getNthPlayer` at `0x6A844E`, which is a thiscall on the list:

```asm
006a844e  mov  eax, [esp+4]              ; index
006a8452  test eax, eax
006a8454  jl   <null>
006a8456  cmp  eax, 0x14                 ; MAX_PLAYER_COUNT = 20
006a8459  jge  <null>
006a845b  mov  eax, [ecx + eax*4 + 0x18] ; array base +0x18
```

| offset | meaning |
|---|---|
| `+0x10` | local / current player (already in [`runtime-re-workflow.md`](runtime-re-workflow.md)) |
| `+0x14` | player count |
| `+0x18` | `Player*` array, 20 entries |
| `0x68` | `sizeof(PlayerList)` — allocated once at `0x63C0CE` |

So the live local-player chain is **`[[0x00DE4928] + 0x10]`**, and every `Player` stat offset in
[`runtime-re-workflow.md`](runtime-re-workflow.md) hangs off that.

## What this unblocks

- **Unknown 1** (GameLogic object-list head) now starts from a known `TheGameLogic` pointer
  rather than a pointer scan. The object list is a member of that struct.
- **Unknown 3** (player resources) is a bounded diff over the `Player` struct reached through
  `ThePlayerList`, not a blind whole-process scan.
- `TheThingFactory`, `TheUpgradeCenter`, `TheSpecialPowerStore` and `TheScienceStore` are
  precisely the four id spaces [`retarget.py`](../../sage_replay/retarget.py) rebuilds from ini.
  A live backend can read the engine's **own** tables instead of reconstructing them — which is
  also the most direct way to settle the unexplained `+3` in OPEN 4 of
  [`order_space_map.md`](../../sage_replay/order_space_map.md).
- `TheRecorder` is the replay writer, i.e. the other end of the M2 acceptance test.

## Runtime verification (2026-07-29)

Confirmed live against a **solo** RotWK skirmish (one human, no AI opponents), `game.dat` pid
2876, via `OpenProcess(PROCESS_VM_READ|PROCESS_QUERY_INFORMATION)` + `ReadProcessMemory` —
read-only, no injection. All nine globals probed (`ThePlayerList`, `TheGameLogic`,
`TheMessageStream`, `TheThingFactory`, `TheUpgradeCenter`, `TheSpecialPowerStore`,
`TheScienceStore`, `TheRecorder`, `TheGameState`) dereference to valid heap pointers, and the
`PlayerList` layout reads exactly as `getNthPlayer` describes: count `5` at `+0x14`, a 20-slot
array at `+0x18`, and `+0x10` equal to array slot 3.

**A solo game still carries five `Player` slots** — the count is not the number of participants:

| slot | internal name | Side | note |
|---|---|---|---|
| 0 | *(empty)* | — | the neutral placeholder `PlayerList::newGame` skips (see [`max-player-count.md`](max-player-count.md)) |
| 1 | `PlyrCivilian` | `Civilian` | engine-managed |
| 2 | `PlyrCreeps` | `Civilian` | engine-managed; owns the map's wild spawns (94 objects created here) |
| 3 | `Player_1` | `Men` | the human — matches `+0x10` |
| 4 | `ReplayObserver` | `Observer` | engine-managed |

Anything walking the player array must therefore filter by Side or by slot identity, not assume
every populated slot is a participant.

### `Player` identity fields

Found by scanning the struct for pointers whose `+8` is printable (the `AsciiString` layout from
[`runtime-re-workflow.md`](runtime-re-workflow.md) §5). The real fields are the ones that appear
at the **same offset in every slot**; isolated hits at other offsets are pointers that happen to
land mid-string and are noise.

| offset | field | encoding | values observed |
|---|---|---|---|
| `+0x38` | display name | UTF-16 | `Ben`, `PlyrCivilian`, `Observer` |
| `+0x4C` | internal player name | ASCII | `Player_1`, `PlyrCivilian`, `PlyrCreeps`, `ReplayObserver` |
| `+0x58` | **Side / faction** | ASCII | `Men`, `Civilian`, `Observer` |

`+0x58` is the `PlayerState.faction` field of the [`live-api.md`](../../docs/live-api.md) §5
observation model, and it is the Side token `sage_ini` already keys factions on.

**Reading requires an elevated handle** — `game.dat` runs as administrator, so an unelevated
process gets `ERROR_ACCESS_DENIED` (5) on `VM_READ` while still being allowed
`PROCESS_QUERY_LIMITED_INFORMATION`. That asymmetry is a useful smoke test for the wrong
privilege level.

## `Player` economy — unknown 3, solved

| offset | meaning | how it was pinned |
|---|---|---|
| **`+0x0094`** | **current spendable resources** | falls by exactly the amount spent; reads `1000` (the standard skirmish start) for every player who has not spent; `0` for the neutral side |
| `+0x03E0` | cumulative resources collected | rises in lockstep with income, **never falls** |
| `+0x04F0` | mirror of `+0x03E0` | identical value in every sample |

The decisive measurement, across two sampling runs with a deliberate 1500 spend in between:

```
                 +0x94   +0x3E0
run 1, end        3810     4460
run 2, start      2510     4660     income during the gap = +200
                 -1300     +200

3810 + 200 - 1500 = 2510   exact
```

Note `+0x3E0` sits inside the stats block (`Player+0x3DC`, see
[`runtime-re-workflow.md`](runtime-re-workflow.md)) at `stats+0x04`, whereas the spendable pool at
`+0x94` is a main-struct field well outside it. **The economy is not in the stats block** — which
is exactly the trap [`live-api.md`](../../docs/live-api.md) §9 warned about when it noted
`+0x3DC` is the *stats* block, not the economy.

Method note: a monotonic-increase ranking over the whole struct surfaces the candidates in
seconds, but the confirming signal is a **decrease**. Large values in the 170–190 million range
(`+0x6FC`, `+0x760`) are heap pointers, not counters — they drift as objects are allocated and
should be filtered by magnitude before ranking.

## Caveat

These are addresses of globals in a specific build (RotWK 2.01, `game.dat` 11,346,944 bytes).
Verify against your own copy before building on them.
