# Hero "permadeath" across the battle boundary — and why it is not permadeath

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis against RotWK's `game.dat`
and `C:\BFME1\lotrbfme.exe`, measured on both games' saves on 2026-08-28.

> **Summary.** Both BFME1 and RotWK harvest a battle back into the living-world army. They differ
> in one rule — BFME1 keeps a hero with no surviving object **in his army**; RotWK moves him **out
> of it**, into the faction's fortress hero-spawn queue, with his upgrades, re-buyable as a one-hero
> army. [`hero-army-carryover`](../../patches/experimental/hero_army_carryover.py) adds BFME1's rule
> as an opt-in `Persistent` keyword on `ArmyEntry` ([*The patch*](#the-patch)).

## The question

In BFME1 a non-vital hero that dies in a campaign mission is still in his army afterwards. In
RotWK — Edain's `wotrscenarioangmar.inc`, where each hero is its own `SpawnArmy` with a
`HeroTemplateName` — a hero that dies in the mission is gone from the army he was in.

## What the engine does at the end of a War of the Ring battle

`0x00626662` runs on `TheGameLogic` when the battle finishes. Its first act is the harvest:

```asm
0062666d  push dword ptr [edi + 0xac]     ; the object list head
00626673  lea  ecx, [edi + 0x184]         ; TheGameLogic's living-world battle bridge
0062667c  call 0x00811e1f                 ; harvest survivors into the living-world armies
```

`0x00811E1F` walks the object list by `obj->[0x8c]` and, for every object still alive, keeps it
only if **all four** hold:

| test | site | meaning |
|---|---|---|
| `player = obj->0x0068b678()`, `player->[0x3cc] != -1` | `0x00811e86` | the owner is a living-world player |
| `[obj->[4] + 0x118] & 1` | `0x00811e96` | the template has `KindOf = ARMY_SUMMARY` |
| `[obj + 0x458] & 1` clear | `0x00811ea2` | unidentified skip flag |
| `[obj + 0x47c] != 0` | `0x00811eaa` | the object carries a living-world army id |

`tmpl+0x118` is KindOf byte `+0x10`, bit `0x01` — index 128, `ARMY_SUMMARY` (`explore.py enum
KindOf`). Each keeper gets a fresh `0xD8`-byte roster record (`0x0080ECA7`), `record->[0xa0] = 1`,
and is appended to `findArmyById(obj->[0x47c])->[0x78]` by `0x00811951`.

Then, per RTS player with a living-world id, the player's money, sciences and upgrades are written
back (`0x00811F35`–`0x00811FAD`).

**A unit that died is not written back into its army.** There is no death record, no flag, no
notification — the army afterwards is the list of things that walked off the field. A hero is one
of those things: `0x0071B310` matches roster records against the army's `HeroTemplateName`
(`army+0x18`) by name, so a hero with no surviving object has no record and the army has no hero.

**The roster is replaced, not appended to.** Records are consumed **at deployment**, one at a time,
by `0x0071AE2D`, and the harvest puts the survivors back. The only roster clear, `0x00810AA9`, is
reachable only from the template assign `0x0081176F`, and the harvest's single pre-loop call
`0x0080FF5B` walks the region rather than any army's records — so the replace is not visible as a
clear; it is the deploy-then-harvest round trip. Measured: four roster entries went into a mission,
the three survivors came out, each carrying the upgrades it had earned (*Where a dead hero goes*).

**An army's roster is seeded from its `LivingWorldPlayerArmy` exactly once.** `0x0071AD41` has a
single caller, `0x0071BDDA`, in the army constructor, so nothing re-reads the template after a
battle.

## The roster record is an `ArmyEntry`, and it has a third keyword

`ArmyEntry` parses into exactly the same `0xD8`-byte record (`0x00811CF9` allocates it, `0x0080EF6D`
parses it, `0x00811951` appends it), through two field tables:

| table | keyword | offset | parse |
|---|---|---|---|
| `0x00C2F470` | `ThingTemplate` | `+0x04` | AsciiString |
| `0x00C2F470` | `Quantity` | `+0xA0` | Int |
| `0x00C4FA94` | **`Default`** | `+0xD5` | Bool |

`Default` is undocumented and set **nowhere** — 724 `ArmyEntry` blocks in Edain, 0 uses; 0 in
BFME1's shipped INI.

And the enclosing `LivingWorldPlayerArmy` block (table `0x00C4FB58`) carries the other half:

| keyword | offset |
|---|---|
| `Name` | `+0x18` |
| `DisplayNameTag` | `+0x64` |
| `Color`, `NightColor` | `+0x24`, `+0x28` |
| `ArmyEntry` | the record list at `+0x40` |
| **`SurvivalThreshhold`** | `+0x60`, Int |

`SurvivalThreshhold` is likewise set nowhere in either game.

## What the two knobs do — the summon-into-battle function

`0x00812119` is reached only from an army's own state machine (`0x00812585`, a virtual, two call
sites), whose state-0 message is `Auto-Summoning army %d into battle` — so it governs **an army
arriving in a battle**, not what the army holds on the strategic map. It summons an army's roster into a battle. `ecx` is the army's force container
(`army+0x78`: `+0x1c` army id, `+0x2c` phase, `+0x40` records, `+0x60` `SurvivalThreshhold`):

```asm
00812146  esi = [ebx + 0x60]              ; SurvivalThreshhold
00812149  if (esi <= 0) goto deploy
00812157  eax = 0x0080fa21(this)          ; sum of Quantity over records with Default == No
0081215c  if (esi > eax) [ebp-0xd] = 1    ; the army is below its threshold
...
0081224e  if ([record + 0xd5] != 0        ; a Default record
00812257   && [ebp-0xd] == 0) skip        ;   deploys only when below the threshold
0081226b  THING_FACTORY_FIND_TEMPLATE(record + 4)
```

So the semantics are:

- **`Default = Yes` marks a record as a fallback line.** It is not counted as strength
  (`0x0080FA21` skips it) and is not deployed while the army has enough real units.
- **`SurvivalThreshhold` is the unit count below which the fallback deploys anyway.**

An army whose entries are all `Default = Yes` therefore has strength 0 and is always below any
positive threshold.

**Neither restores a hero the army has lost.** `Default` is a property of the record, and the
template's records are consumed by their first deployment; the harvest's replacements are built by
`0x0080ECA7`, which zeroes `+0xD5`. So after one battle the army has no `Default` records left, and
`SurvivalThreshhold` — which does persist, on the container at `+0x60` — has nothing to fall back
to. Measured in game on 2026-08-28: `WitchKingKampaArmy` with `SurvivalThreshhold = 1` and
`Default = Yes` on all four of its `ArmyEntry` rows lost Durmarth in a won mission exactly as it
does without them.

## The strategic-layer rules found alongside

These are separate from the harvest and worth not confusing with it.

| site | what it is |
|---|---|
| `0x006B921E` | queue a hero army onto `TheLivingWorldLogic+0x10C` — the retreat list |
| `0x006B9679` | destroy an army: set `army+0x75 = 1`, queue onto `TheLivingWorldLogic+0x118` |
| `0x006BABA8` | drain `+0x10C`: for each hero army, count adjacent regions its owner holds. One → move it there. **None → `LW:HeroKilledTitle` / `LW:HeroKilledText` and destroy.** |
| `0x006BCD1E`, `0x007F8014` | when a region changes hands: `isEmpty(army+0x18)` decides the fate — a plain army is destroyed outright, a hero army is queued for retreat |

`army+0x18` (`HeroTemplateName`, copied from the `SpawnArmy` record's `+0x50`) is the engine's
"is this a hero army" discriminator, tested at 17 sites across the living-world modules.

## Where a dead hero goes

**Measured 2026-08-28** from two `.BfME2WotR` saves on the world map, one taken before the mission
and one after, decoded with `sage_save` (`python -m sage_save json <save> --out <json>`;
`living_world.object_templates` is the `02 01`-marked roster subset of `CHUNK_LivingWorldLogic`).

`WitchKingKampaArmy`'s roster:

| | before | after |
|---|---|---|
| roster entries | `AngmarWitchking_mod`, **`AngmarDurmarth`**, `AngmarRogash_New`, `AngmarDrauglin` | `AngmarWitchking_mod`, `AngmarRogash_New`, `AngmarDrauglin` |
| entries carry | nothing | `Upgrade_Level_1` / `Upgrade_Level_2` per hero |

**The dead hero is moved into a second Angmar hero list.** After `WitchKingKampaArmy`'s roster the
Angmar player region holds a second list of heroes — before the mission `AngmarHwaldar_mod`,
`AngmarHelegwen`, `AngmarKarsh_mod`, `AngmarMorgramir_mod`, `AngmarGulzar_Alone`,
`AngmarZaphragor`, each written `00 0a <len><name> 00 00 80 3f …` (the float is `1.0f`), on a
~`0x55`-byte stride. Those six are `MorgomirArmy`'s `ArmyEntry` rows, six for six — including
`AngmarZaphragor`, which distinguishes them from `LWB_AngmarFortress`'s purchasable-hero list.

After the mission the same six are there — in reverse order — **plus `AngmarDurmarth`** at the same
stride, written `00 0a 0e "AngmarDurmarth" c2 23 38 43 …`: a different float (`184.14f`), four
upgrades attached (`Upgrade_MiniHordeLvl2`, `Upgrade_MiniHordeLvl1`, `Upgrade_Level_2`,
`Upgrade_Level_1`), and immediately after it a **`HIDurmarth`** reference — the
`ConstructButtonImage` on `LWB_AngmarFortress`'s `ArmyToSpawn` entry for `DurmarthArmy`.

The static side: `0x0071AE2D`, which removes a record from a roster, calls `0x006E4853` when the
template is `KindOf HERO` (`tmpl+0x113` bit `0x04`), filing it on the owning `LivingWorldPlayer` at
`+0x1D4` — a vector of **`0xE8`-byte** records, each carrying an `AsciiString` name at `+0xE4` and a
flag at `+0xB0`; `0x006E2D16` looks one up by name and returns its `+0xBC`. At battle end
`0x0078100E` takes the player's hero ledger (`Player+0x758`) entries that are `KindOf HERO` +
`KindOf ARMY_SUMMARY` and files them on the living-world player the same way.

> Neither save contains the strings `Morgomir_Army` or `MorgomirArmy`, though it contains
> `WitchKing_Army` / `WitchKingKampaArmy`. So either an army's name strings are not always written,
> or the six-name list is written for an army that is not yet spawned — `Morgomir_Army`'s
> `SpawnArmy` is in a later act than the one played here. Unresolved.

## The hero is not dead: he is back in the fortress queue

**Confirmed in game, 2026-08-28.** After the mission Durmarth is offered from the Angmar
fortress's hero build-up like any other hero — and, unlike the heroes that are still in an army, he
is offered *without* the marker saying he already belongs to one. That is the engine correctly
recording that he left `WitchKingKampaArmy`.

So the RotWK behaviour is not permadeath:

```
LivingWorldBuilding LWB_AngmarFortress
    BuildingNugget SpawnArmy NuggetTag_Spawner
        QueueSize = 10
        ArmyToSpawn
            PlayerArmy           = DurmarthArmy      ; a one-hero LivingWorldPlayerArmy
            HeroTemplateName     = AngmarDurmarth
            BuildTime            = 2
            ConstructButtonImage = HIDurmarth        ; the name that appeared in the save
        End
    End
End
```

**A hero killed in a mission is returned to his faction's hero-spawn queue**, keeping the upgrades
he had earned — the save carries `Upgrade_Level_2`, `Upgrade_Level_1`, `Upgrade_MiniHordeLvl2` and
`Upgrade_MiniHordeLvl1` on his record — and is re-buyable in `BuildTime` turns as **his own
one-hero army**. `HIDurmarth` appearing in the save at the moment he died is that entry's
`ConstructButtonImage`.

### What is actually different from BFME1

Two things, both smaller than "he dies":

1. **You spend turns getting him back** — `BuildTime = 2` on his `ArmyToSpawn`, in a queue of 10.
2. **He comes back as `DurmarthArmy`, not back inside `WitchKingKampaArmy`.** The army he was in
   has permanently lost a member.

### And `MergePlayerArmy` cannot fix (2) as things stand

The obvious move — re-buy him, then fold `DurmarthArmy` into the Witch-king's army with
[`campaign-army-verbs`](../../patches/campaign_army_verbs.py) — **does not work**,
and the reason is worth writing down rather than discovering later. `MergePlayerArmy` resolves
`SourceArmy` through `findArmyByScriptingName` (`0x006B53A4`), which matches `army+0x1C`, copied
from a `SpawnArmy` block's `ScriptingName`. **`ArmyToSpawn` has no `ScriptingName` field** — the
keyword appears zero times in `livingworldbuildings.ini` and the block's schema does not carry it —
so a fortress-bought army has no name for a script to address it by. Merging one back in would need
either a way to name it or a `MergePlayerArmy` that can select an army some other way.

### The options

| | what | cost |
|---|---|---|
| **Accept and tune** | the hero *is* recoverable, with his upgrades. `BuildTime` on his `ArmyToSpawn` is the dial | one INI number |
| **Prevent the death** | `UNIT_AFFECT_OBJECT_PANEL_FLAGS(<hero>, 'Indestructible', …)` in the mission — already used on Rogash in `map kampa angmar 01` | per-mission scripting |
| **Patch for true parity** | at battle end, re-add to the army any marked hero that was in it at battle start and has no survivor | [`hero-army-carryover`](#the-patch) |

The patch cannot sit at `0x0071AE2D`: that site fires during ordinary deployment too — every hero
leaves the roster to become a map object — so re-adding there would break the normal path. It
belongs at the harvest (`0x00811E1F`), the only place that knows a battle has ended, with the
army's pre-battle hero list captured at battle start to compare against.

## The control experiment: BFME1, measured

**2026-08-28.** Four BFME1 saves from the evil campaign, mission 1, around Saruman's death.
BFME1 writes `CHUNK_LivingWorldLogic` at **version 3** (RotWK writes 6); `sage_save info` dies on
its `CHUNK_GameState`, but the container and the chunk parse, and the name scan runs on it
unchanged.

`Evil_SarumanPlayerArmy`, read the same way as the RotWK army:

**Before** the mission
```
Evil_SarumanPlayerArmy, Saruman, BannerIsengard, LWA:Isengard_City,
    IsengardSaruman
```

**After** it, with Saruman killed in the battle
```
Evil_SarumanPlayerArmy, Saruman, BannerIsengard, LWA:Isengard_City,
    IsengardUrukCrossbowHorde, Isengard,
    IsengardFighterHorde,      Isengard,
    IsengardUrukCrossbowHorde, Isengard,
    IsengardFighterHorde,      Isengard,
    IsengardUrukCrossbowHorde, Isengard,
    IsengardSaruman, Upgrade_SarumanFireBall, Isengard        <-- still in the army
```

Two things fall out.

### The actual difference between the games

| | BFME1 | RotWK |
|---|---|---|
| roster after a battle | survivors **plus the dead hero**, all with their upgrades | survivors only |
| where the dead hero goes | **stays in his army** | out of the army, into the faction's fortress hero-spawn queue |

RotWK does not destroy the hero and does not lose his upgrades — it *relocates* him, and the army
permanently loses a member.

### BFME1 writes battle results back too

`Evil_SarumanPlayerArmy` went into mission 1 holding **one** entry and came out holding **six**:
five surviving Isengard hordes it did not have before, each tagged `Isengard`, plus Saruman
carrying an `Upgrade_SarumanFireBall` he did not have before either. BFME1 harvests a battle into
its living-world armies just as RotWK does — even though its binary has no `HeroTemplateName`, no
`LW:HeroKilledTitle`, no `Carryover` string, no `CREATE_UNIT_REVIVAL_ENTRY` and no
`ArmyCarryoverPoints`. **The two games differ only in what they do with a hero record that has no
surviving object.**

## The patch

`hero-army-carryover` gives `ArmyEntry` a **`Persistent`** keyword; a hero written
`Persistent = Yes` stays in his army when he dies. Absent or `No` is the stock behaviour exactly.

**Where a dead hero's state is, and is not.** Not on his object. BFME1's in-battle saves settle it:
`IsengardSaruman` is a live object in the save taken before he dies and **absent** from the one
taken after, so by the time a battle ends there is nothing left to harvest and no amount of
loosening the harvest's filters would find him. What survives is his entry in the player's hero
ledger at `Player+0x758` - the same ledger the ControlBar offers as revivable during the mission -
and the engine **already** walks it when a battle ends: `0x0078100E` takes its `KindOf HERO` +
`KindOf ARMY_SUMMARY` entries and files them on the living-world player. That is why Durmarth
reached the world map carrying `Upgrade_Level_2`. The patch reads the same ledger and puts the
hero back in his **army** as well.

**The record is built by the engine.** `0x00780FEF(entry, record)` is the exact mirror of
`0x0069192F` (`Object -> record`), down to the same `record+0xD0` tail: it writes the name, sets
`Quantity = 1`, copies the `0x90`-byte state block and assigns the upgrade list. So a hero rejoins
at the level and with the upgrades **he died with** - that battle's progress included - rather than
at some remembered earlier state.

| site | stock | becomes |
|---|---|---|
| `0x0080EF87` | the immediate naming the `ArmyEntry` sub-table (`0x00C4FA94`, one row: `Default`) | a two-row copy in the cave, `Persistent` beside it |
| `0x00811D41` | `call 0x0080EF6D` - the `ArmyEntry` field parse | the same call, then: a set flag becomes a remembered `ThingTemplate` name |
| `0x0062565A` | `call 0x008125FC` - the battle-start restore | the same call, then note which army each marked hero is in |
| `0x0062667C` | `call 0x00811E1F` - the harvest | the same call, then the ledger walk that puts them back |

**The keyword needs no record field of its own.** `Persistent` parses through the engine's own
`Bool` parser into `record+0xD7` - a byte the record constructor does not initialise, the
copy-constructor does not carry (it stops at `+0xD6`) and nothing else reads. The parse hook zeroes
it going in and consumes it coming out, before the record leaves the parser, so it never has to
survive the template-to-army copy that would have lost it.

Nothing is held by reference across a battle: the cave's two tables carry names and army ids only.
Forty-two tests. **Runtime-verified 2026-08-28** - see the last section.

## Runtime result: the patch works, and it keeps the mission's progress

**Played 2026-08-28** with `hero-army-carryover` applied and `Persistent = Yes` on
`WitchKingKampaArmy`'s entries. `WitchKingKampaArmy`'s roster, read the same way as every save
above:

| | roster after the mission |
|---|---|
| before the mission | `AngmarWitchking_mod`, `AngmarDurmarth`, `AngmarRogash_New`, `AngmarDrauglin` — **no upgrades on any of them** |
| after, unpatched | Witchking (`Upgrade_Level_2`, `Upgrade_Level_1`), Rogash (same), Drauglin (`Upgrade_Level_1`) — **Durmarth gone** |
| after, patched | Witchking, Rogash, Drauglin as above, **plus `AngmarDurmarth` carrying `Upgrade_MiniHordeLvl2`, `Upgrade_MiniHordeLvl1`, `Upgrade_Level_2`, `Upgrade_Level_1`** |

He is back in the army under the roster's own `02 01` marker, in the position the restore appends
him to — after the three survivors the harvest wrote first.

**And the levels and upgrades are the ones he earned in the mission he died in.** He went into it
with no upgrades at all and came out of it with four. That is the whole point of rebuilding him
from the hero ledger rather than from a remembered pre-battle record: the ledger entry is the hero
as he died, and `0x00780FEF` converts it faithfully.

### Expected: he is in the army *and* still offered at the fortress

The engine's own ledger copy (`0x0078100E`) still runs, so a persistent hero ends up in **both**
places:

```
@0x003a8  pre=00000201  AngmarDurmarth   <- the army roster (this patch)
@0x00949  pre=0000000a  AngmarDurmarth   <- the LivingWorldPlayer hero list (stock behaviour)
@0x009dd                HIDurmarth       <- and his fortress build button, with it
```

**Confirmed in play on 2026-08-28: the Angmar fortress does still offer him.** This is **intended
behaviour and is not being changed.** The patch adds the army half of BFME1's rule; it does not
take away ROTWK's own, and a hero who died is therefore both back with his army and available to
recruit again. A scenario that wants only one of those has the `Persistent` keyword to decide which
heroes get the army half at all.

Three tests pin it as a choice rather than an oversight: the cave never reaches
`LIVING_WORLD_LEDGER_TO_PLAYER` (`0x0078100E`), no site the patch edits belongs to it, and the
patch's own description says the hero stays buyable.

Suppressing the engine's filing, if a scenario ever wants it, would be the way to do it - `0x0078100E`'s inner loop already asks
`0x006E301F(lwPlayer, entry)` before choosing between two paths, so there is a decision point to
hook. **Removing the entry afterwards would not be**: `LivingWorldPlayer+0x1D4` is a vector of
`0xE8`-byte entries **by value** (`0x006E3B88` constructs it, `0x006E3EF0` destroys it through
`0x006B1688`), each owning `AsciiString`s and an upgrade list, so erasing one means destructing and
shifting rather than a `memmove` - the kind of hand-written surgery that corrupts a heap.
