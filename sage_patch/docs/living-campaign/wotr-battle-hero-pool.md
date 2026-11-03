# Keeping the world-map hero pool out of a battle

Engine build `2.01.2614.37001`, ImageBase `0x400000`. **Read from the disassembly, 2026-10-29.** The
symptom is seen in game. The patch,
[`wotr-battle-hero-pool`](../../patches/campaign/wotr_battle_hero_pool.py), is static only.

## TL;DR

- A War of the Ring player keeps a **hero pool** on its world-map player, at `+0x1D4`: a vector of
  `0xE8`-byte entries, the same shape as the battle's revive ledger at `Player+0x758`.
- When a battle starts, the RTS player's hero seeding **moves the whole pool into the ledger**. Every
  positional `REVIVE` slot then offers pool heroes, and a bound `REVIVE` button
  ([`revive-object-binding.md`](../revive-object-binding.md)) can find a pool entry before the
  entry of the hero who just died.
- `Scenario` gains `NoBattleHeroPool`. With `Yes` the seeding takes its own "no world-map player"
  exit. The pool stays on the world map and the battle's ledger holds only that battle's dead.

## 1. What the pool holds

Three writers, all through the entry vector's push (`0x006E40A6`, `ecx` = `worldPlayer+0x1D4`):

| writer | when | what |
|---|---|---|
| `0x006E48C2`, via `0x006E47EC` | scenario start | every `KindOf HERO` `ArmyEntry` in the `SpawnArmy` lists of the faction's world-map buildings, at level 1: the heroes a fortress offers on the world map |
| `0x0071AE2D`, via `0x006E4853` | a record leaves a world-map army (`LIVING_WORLD_ARMY_ERASE_RECORD`) | that hero, when the record is `KindOf HERO` |
| `0x0078100E` (`LIVING_WORLD_LEDGER_TO_PLAYER`), via `0x006E42CF` | a battle ends | each ledger entry that is `KindOf HERO` and `ARMY_SUMMARY`, unless `0x006E301F` hands it back to its army (`0x00811D91`) instead |

So the pool is the world map's own "recruitable heroes" list. Seen in Edain's good campaign, map 01:
the House of Elrond offered level-1 Elrond and Arwen (both world-map hero armies) while the map's own
Elrond stood beside it. On evil 07 the ledger held 11 Mordor heroes at the start of the battle.

## 2. The battle-start move

The RTS player's hero seeding is `0x006B16EC` (one caller, `0x006B1971`). `ebx` is the `Player`;
`ebx`, `esi` and `edi` are pushed.

```
006b1702  cmp  dword [ecx+0x114], 3        ; [0xDE412C]: the game mode
006b170b  je   0x6b179f                    ;   3: seed from BuildableHeroesMP instead
006b1711  mov  eax, [ebx+0x3cc]            ; <- hook: the world-map player id
006b1717  cmp  eax, -1
006b171a  je   0x6b17f7                    ;   none: SKIP
006b172a  call 0x6b5de0                    ; LIVING_WORLD_FIND_PLAYER_BY_ID
006b174e  call 0x6e42da                    ; collect the pool into a local vector
006b1777  call 0x781861                    ; ledger.insertEntry(entry, player), per entry
006b1798  call 0x6b1688                    ; free the local vector
006b17f7  mov  ecx, [ebp-0xc] / pop edi / pop esi / pop ebx ...   ; SKIP: the epilogue
```

`0x006E42DA` walks the pool from the back. For each entry that `0x006E24C0` does not keep, it fills
in the battle's region army (`LIVING_WORLD_MERGE_INTO_REGION_ARMY`), copies the entry out and
**erases it from the pool** (`0x006E33C5`). So stock, the pool is empty for the length of the battle,
and `LIVING_WORLD_LEDGER_TO_PLAYER` refills it when the battle ends with whatever was not recruited.

## 3. The patch

- `Scenario` gains `NoBattleHeroPool`, a `Bool` at `+0xC3`, the last padding byte. It is the byte
  after `hide-selection-details`' `+0xC2`, in a field table rebuilt from the live one, so the two
  compose.
- The constructor's `HistoricalScenario` store becomes the dword store that zeroes `+0xC0..+0xC3`,
  `hide-selection-details`' own rewrite. Whichever patch comes first writes it, and this one accepts
  it already widened. Applied after this one, `hide-selection-details` expects the stock store and
  refuses, so in a manifest it must come first. It does, alphabetically.
- `0x006B1711` jumps to `seed`. It reads the current scenario's flag the way
  `hide-selection-details` does. Clear: it replays the load and resumes at `0x006B1717`. Set: it
  jumps to `0x006B17F7`. The stack there is the hook's own, the same as on the stock `je` from
  `0x006B171A`.

With the flag set, nothing is taken out of the pool, so the world map keeps it unchanged. A hero who
dies in the battle and is not revived reaches the pool through the battle-end copy, as stock.

```
LivingWorldCampaign WOTRScenarioTest
    Scenario
        NoBattleHeroPool = Yes
    End
End
```

## 4. What is not known

- **Nothing here has run.** In particular, whether the campaign manager's current campaign
  (`manager->[0x14][manager->[0x10]]`) is still set while an RTS battle is being set up. If it is
  not, the flag reads `No` and the patch does nothing.
- **AI players.** The skip applies to every seat whose world-map player is found, the AI ones
  included. Their AI then no longer revives pool heroes in battle.
- **`0x006E24C0`**, the per-entry test that keeps some entries in the pool, was not read.
