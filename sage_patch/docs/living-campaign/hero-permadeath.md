# Hero "permadeath" across the battle boundary — and why it is not permadeath

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-08-27, against
`C:\BFME1\lotrbfme.exe` for the BFME1 half.

> **Read the end first.** Measured on both games, 2026-08-28: **both** BFME1 and RotWK harvest a
> battle back into the living-world army. They differ in one rule — BFME1 keeps a hero with no
> surviving object **in his army**; RotWK moves him **out of it**, into the faction's fortress
> hero-spawn queue, with his upgrades, re-buyable as a one-hero army. That is the whole difference,
> and it is a much smaller one than this document assumed on the way to finding it. The route
> here included a fix that was tried in play and failed and three wrong readings, all left in place
> with their corrections — see [*Tested, and refuted*](#tested-and-refuted),
> [*What the saves say*](#what-the-saves-say),
> [*Resolved*](#resolved-the-hero-is-not-dead-he-is-back-in-the-fortress-queue) and
> [*The control experiment*](#the-control-experiment-bfme1-measured).

## The question

In BFME1 a non-vital hero that dies in a campaign mission is still on the strategic map
afterwards. In RotWK — Edain's `wotrscenarioangmar.inc`, where each hero is its own `SpawnArmy`
with a `HeroTemplateName` — a hero that dies in the mission is gone from the living world.

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

**A unit that died is simply never written down.** There is no death record, no flag, no
notification — the army afterwards is the list of things that walked off the field. A hero is one
of those things: `0x0071B310` matches roster records against the army's `HeroTemplateName`
(`army+0x18`) by name, so a hero with no surviving object has no record and the army has no hero.

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

> **Corrected 2026-08-28.** This section originally read `0x00812119` as *the* deployment and drew
> a world-map conclusion from it. It is reached only from an army's own state machine
> (`0x00812585`, a virtual, two call sites), whose state-0 message is
> `Auto-Summoning army %d into battle` — so it governs **an army arriving in a battle**, not what
> the army holds on the strategic map.

`0x00812119` summons an army's roster into a battle. `ecx` is the army's force container
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
positive threshold. That much still reads correctly; what does **not** follow — and what the
2026-08-28 test disproves — is that it restores a hero the world map has already lost.

## Why BFME1 does not have the problem

String counts in `lotrbfme.exe`:

| string | RotWK | BFME1 |
|---|---|---|
| `ARMY_SUMMARY` | 1 | **1** |
| `SurvivalThreshhold` | 1 | **1** |
| `ScriptingName` | 1 | 1 |
| `HeroTemplateName` | 1 | **0** |
| `LW:HeroKilledTitle` | 1 | **0** |

BFME1 has the roster and the threshold; it has neither the hero-army concept nor the hero-killed
rule. Armies there are instantiated from `ArmyEntry` rows and nothing harvests the battlefield, so
a dead hero is still on the roster next time. This refines the earlier framing in
[`living-world-parity.md`](living-world-parity.md) §3: the RotWK addition is not "persistence" in
general, it is **the harvest at `0x00811E1F`**.

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

## What to do about it, in confidence order

> Item 1 was **tried and did not work** (2026-08-28). It is left here as written, with the result
> and the reason recorded below, rather than quietly rewritten.

1. ~~**`Default = Yes` on the hero's `ArmyEntry`, plus `SurvivalThreshhold` on the
   `LivingWorldPlayerArmy`.**~~ INI only, two lines, aimed exactly at this. For a one-hero army:

   ```
   LivingWorldPlayerArmy
       Name               = WitchKingKampaArmy
       DisplayNameTag     = LWA:AngmarHeroArmy
       SurvivalThreshhold = 1
       ArmyEntry
           ThingTemplate = AngmarWitchking_mod
           Quantity      = 1
           Default       = Yes
       End
   End
   ```

   Static reading only. What is proven is that both keywords parse to `+0xD5`/`+0x60` and that
   `0x00812119` reads both; what the redeployed hero's level and health are is not.
2. **Prevent the death in the mission.** `UNIT_AFFECT_OBJECT_PANEL_FLAGS(<hero>, 'Indestructible', …)`
   — already used on Rogash in `map kampa angmar 01`. Blunt, reliable, and per-mission.
3. **Patch the harvest.** `0x00811E1F` is a clean hook site: widening the keep test to re-record a
   hero from the army's `HeroTemplateName` when no surviving object matched it would give RotWK
   BFME1's behaviour for heroes only. Not built.

## What is still unknown

- ~~Whether the harvest **replaces** the army's record list or **appends** to it.~~ **Settled
  2026-08-28: it appends** — the only roster clear is `0x00810AA9`, reachable only from the
  template assign `0x0081176F`.
- Whether `LivingWorldPlayer+0x1D4` is where a dead hero is recorded, and what `+0xB0` on those
  records means. The lead, and the measurement that would settle it, are at the bottom.
- `obj+0x458` bit 0, the fourth harvest filter.
- Whether a redeployed `Default` record carries level and upgrades, or spawns fresh.

## Tested, and refuted

**Measured in game, 2026-08-28.** `WitchKingKampaArmy` was written with `SurvivalThreshhold = 1`
and `Default = Yes` on all four of its `ArmyEntry` rows (Witchking, Durmarth, Rogash, Drauglin).
Durmarth died in the mission; the mission was **won**; back on the world map he was still dead.

So the recommendation was wrong. Four things came out of re-reading the sites afterwards, and the
first two are why.

**`SurvivalThreshhold` and `Default` are about summoning an army into a battle, not about what an
army contains.** `0x00812119` is the only function that reads either of them, and it has exactly
**two** callers — `0x00812575` and `0x00812839` — both inside the army-force object's own state
machine at `0x00812585`, which has no direct callers at all (it is a virtual, an update tick). Its
state-0 message is `Auto-Summoning army %d into battle`. The document above put these two keywords
in the same sentence as the world-map roster; they are one layer below it.

**An army's roster is seeded from its `LivingWorldPlayerArmy` exactly once.**
`0x0071AD41` has a single caller, `0x0071BDDA`, in the army constructor. So editing the template
changes armies spawned *after* the edit — which a fresh scenario satisfies — but nothing re-reads
the template later, and in particular nothing restores a `Default` entry after a battle.

~~**The harvest appends; it does not clear.**~~ **Wrong, and measured wrong the next day** - see
[*What the saves say*](#what-the-saves-say). The static argument was that the only roster clear is
`0x00810AA9` (pop-and-release until `+0x40 == +0x44`), reachable only from the template assign
`0x0081176F`, and that the harvest's single pre-loop call `0x0080FF5B` walks the region rather than
any army's records. All of that is true and the conclusion still did not follow: the records are
consumed **at deployment**, one at a time, by `0x0071AE2D` - which is also the site that files a
`KindOf HERO` record into the player's hero pool. Net effect on the roster is a replace.

**There is a second store the army roster knows nothing about.** `LivingWorldPlayer + 0x1D4..0x1D8`
is a vector of **`0xE8`-byte** records, each carrying an `AsciiString` name at `+0xE4` and a flag at
`+0xB0`; `0x006E2D16` looks one up by name and returns its `+0xBC`. It is appended to by
`0x006E4853`, and the only caller of *that* is `0x0071AE2D` — the function that removes a record
from an army's roster — **guarded on `KindOf HERO`** (`tmpl+0x113`, bit `0x04`, KindOf index 90). So
when a hero leaves an army, the engine files a per-player hero record, and no `ArmyEntry` keyword
reaches it.

**Stated as the lead it is, not as an answer.** The chain "hero leaves roster → per-player hero
record → hero shows as dead" is inference from three call sites, which is exactly the kind of chain
that produced the refuted recommendation. What would settle it is one measurement, below.

### The measurement that settles it

Two saves — one on the world map **before** the mission, one **after** — decoded with the tool that
already reads this chunk:

```sh
python -m sage_save json before.sav --out before.json
python -m sage_save json  after.sav --out  after.json
```

`living_world.object_templates` in each is the set of ini `Object` templates the saved army rosters
field (the `02 01`-marked subset of `CHUNK_LivingWorldLogic`). Then:

| `AngmarDurmarth` in *before* | in *after* | what it means |
|---|---|---|
| yes | **yes** | the roster still holds him, so "dead" is being read from somewhere else — the per-player store above is the first place to look |
| yes | **no** | the roster lost him despite `Default = Yes`, so the harvest does replace after all and the reading above is wrong again |
| **no** | no | `Default = Yes` kept him out of the roster from the start, which would make the keyword actively harmful here |

The third row is worth taking seriously: `0x0080FA21` counts only records with `+0xD5 == 0`, so an
army whose every entry is `Default = Yes` has a computed strength of **zero**, and anything else
that counts an army the same way would read it as empty.

## What the saves say

**Measured 2026-08-28** from two `.BfME2WotR` saves on the world map, one taken before the mission
and one after, decoded with `sage_save`. This is the first *measurement* in this document;
everything above it is disassembly.

`WitchKingKampaArmy`'s roster, read as the `02 01`-marked names in `CHUNK_LivingWorldLogic`:

| | before | after |
|---|---|---|
| roster entries | `AngmarWitchking_mod`, **`AngmarDurmarth`**, `AngmarRogash_New`, `AngmarDrauglin` | `AngmarWitchking_mod`, `AngmarRogash_New`, `AngmarDrauglin` |
| entries carry | nothing | `Upgrade_Level_1` / `Upgrade_Level_2` per hero |

Three things follow, and none of them is an inference:

**The roster is replaced, not appended to.** Four entries went in, three came out — the three
survivors — and each came out carrying the upgrades it had earned by the end of the battle. Had the
harvest appended, the army would hold seven. So the correction above corrects itself: the records
are consumed as they deploy and the harvest puts survivors back.

**`Default = Yes` cannot survive that, because it is a property of the record.** The four
`Default = Yes` records came from the template (`0x0071AD41`, which runs once, in the army
constructor). Deployment consumed them. The harvest's replacements are built by `0x0080ECA7`,
which zeroes `+0xD5`. So after one battle the army has **no** `Default` records left and
`SurvivalThreshhold` — which does persist, on the container at `+0x60` — has nothing to fall back
to. The keyword pair can only ever have applied to the first deployment, and it was spent there.

**The dead hero is not destroyed; he is moved into the second Angmar hero list.** After
`WitchKingKampaArmy`'s roster the Angmar player region holds a second list of heroes — before the
mission `AngmarHwaldar_mod`, `AngmarHelegwen`, `AngmarKarsh_mod`, `AngmarMorgramir_mod`,
`AngmarGulzar_Alone`, `AngmarZaphragor`, each written `00 0a <len><name> 00 00 80 3f …` (the float
is `1.0f`), on a ~`0x55`-byte stride. **Those six are `MorgomirArmy`'s `ArmyEntry` rows, six for
six** — including `AngmarZaphragor`, which distinguishes them from `LWB_AngmarFortress`'s
purchasable-hero list, whose members are Drauglin/Androl/WitchKing/CreateAHero instead.

After the mission the same six are there — in reverse order — **plus a seventh element,
`AngmarDurmarth`** at the same stride, written `00 0a 0e "AngmarDurmarth" c2 23 38 43 …`: a
different float (`184.14f` against the six's `1.0f`), four upgrades attached
(`Upgrade_MiniHordeLvl2`, `Upgrade_MiniHordeLvl1`, `Upgrade_Level_2`, `Upgrade_Level_1`) that none
of the six carry, and immediately after it a **`HIDurmarth`** reference — which in Edain is a
`ConstructButtonImage`, on `LWB_AngmarFortress`'s `ArmyToSpawn` entry for `DurmarthArmy`. He also
appears twice under a `01 01 00` marker beside `WOTRKeepAlive`, `AngmarDarkDunedain`,
`AngmarDarkRanger` and `GondorGandalf_mod`.

This is consistent with the static lead — `0x0071AE2D` removes a record from a roster and, when the
template is `KindOf HERO` (`tmpl+0x113` bit `0x04`), calls `0x006E4853` to file it on the owning
`LivingWorldPlayer` at `+0x1D4` — but the save alone does not prove that the list in the file *is*
that vector, and the strides do not match (a save is xfer-serialised, so they need not). What the
save does establish is the movement: **out of one hero list, into another, with his upgrades and a
build-button reference attached.**

> Neither save contains the strings `Morgomir_Army` or `MorgomirArmy`, though it contains
> `WitchKing_Army` / `WitchKingKampaArmy`. So either an army's name strings are not always written,
> or the six-name list is written for an army that is not yet spawned — `Morgomir_Army`'s
> `SpawnArmy` is in a later act than the one played here. Unresolved, and it decides whether a hero
> filed into that list is *in another army* or *nowhere visible*.

### What this makes the real question

Not "how do I stop the hero dying" but **"where did he go, and is he offered there"**. The
`HIDurmarth` reference is the tell: it is the build button `LWB_AngmarFortress` uses to spawn
`DurmarthArmy`, and it did not exist in the save before he died.

The cheapest discriminator costs nothing and needs no tooling: **look at the Angmar fortress's
hero-build menu on the world map after the mission.** If Durmarth's button is there, "dead" means
"returned to the fortress as re-buyable", the engine is behaving, and the fix is authoring — how
that building is presented — not a patch. If it is not there, he is filed into a list nothing
surfaces, and the question becomes which list.

After that, in order of cost:

1. **Check whether `Morgomir_Army` has spawned yet.** Its `SpawnArmy` is in a later act. If the
   six-name list is that army's roster and the army is not on the map, a hero filed into it is
   invisible by construction — and simply advancing to that act would make him reappear.
2. **Patch `0x0071AE2D`.** It is the single site where a hero leaves a roster, it already knows the
   record is a hero, and it holds the owning player. Re-adding the record instead of only filing it
   would give BFME1's behaviour at one call site. Not built, and not worth building until the two
   checks above are done — the destination list exists for a reason, and overriding it blindly is
   how the last two recommendations went wrong.

## Resolved: the hero is not dead, he is back in the fortress queue

**Confirmed in game, 2026-08-28.** After the mission Durmarth is offered from the Angmar
fortress's hero build-up like any other hero — and, unlike the heroes that are still in an army, he
is offered *without* the marker saying he already belongs to one. That is the engine correctly
recording that he left `WitchKingKampaArmy`.

So the premise this whole document opened with is wrong, and the RotWK behaviour is not permadeath:

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
[`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py) — **does not work**,
and the reason is worth writing down rather than discovering later. `MergePlayerArmy` resolves
`SourceArmy` through `findArmyByScriptingName` (`0x006B53A4`), which matches `army+0x1C`, copied
from a `SpawnArmy` block's `ScriptingName`. **`ArmyToSpawn` has no `ScriptingName` field** — the
keyword appears zero times in `livingworldbuildings.ini` and the block's schema does not carry it —
so a fortress-bought army has no name for a script to address it by. Merging one back in would need
either a way to name it or a `MergePlayerArmy` that can select an army some other way.

### The options, now that the behaviour is known

| | what | cost |
|---|---|---|
| **Accept and tune** | the hero *is* recoverable, with his upgrades. `BuildTime` on his `ArmyToSpawn` is the dial | one INI number |
| **Prevent the death** | `UNIT_AFFECT_OBJECT_PANEL_FLAGS(<hero>, 'Indestructible', …)` in the mission — already used on Rogash in `map kampa angmar 01` | per-mission scripting |
| **Patch for true parity** | at battle end, re-add to the army any hero record that was in it at battle start and has no survivor | a real patch, see below |

The patch is **not** the `0x0071AE2D` change suggested in the previous revision of this document.
That site fires during ordinary deployment too — every hero leaves the roster to become a map
object — so re-adding there would break the normal path. The change belongs at the harvest
(`0x00811E1F`), which is the only place that knows a battle has ended, and it needs the army's
pre-battle hero list to compare against. Nothing records that today.

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

Two things fall out, and the second one is load-bearing for this whole investigation.

### The actual difference between the games

| | BFME1 | RotWK |
|---|---|---|
| roster after a battle | survivors **plus the dead hero**, all with their upgrades | survivors only |
| where the dead hero goes | **stays in his army** | out of the army, into the faction's fortress hero-spawn queue |

That is the complaint, exactly as it was originally stated, and it is now measured on both sides
rather than argued from string counts. RotWK does not destroy the hero and does not lose his
upgrades — it *relocates* him, and the army permanently loses a member.

### BFME1 does write battle results back — the parity document is wrong about this

[`living-world-parity.md`](living-world-parity.md) §3 says of BFME1: *"each battle instantiates
from that roster afresh, and **nothing ever writes back** — so a hero killed in a battle is still on
the roster afterwards and is instantiated again next time."* The conclusion is right and the reason
is wrong. `Evil_SarumanPlayerArmy` went into mission 1 holding **one** entry and came out holding
**six**: five surviving Isengard hordes it did not have before, each tagged `Isengard`, plus Saruman
carrying an `Upgrade_SarumanFireBall` he did not have before either. BFME1 harvests a battle into
its living-world armies just as RotWK does.

So the framing "BFME1 has no carryover machinery, heroes came back because death was never
recorded" is wrong. The string counts behind it are accurate — BFME1's binary contains no
`Carryover` string, no `CREATE_UNIT_REVIVAL_ENTRY`, no `ArmyCarryoverPoints` — and the inference
from them to *behaviour* was not. Both games write back. **They differ only in what they do with a
hero record that has no surviving object**, which is a far narrower difference than "RotWK added
persistence and persistence of death is the problem", and a far better patch target.

### What that makes the patch — built

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

## What the saves say

**Measured 2026-08-28** from two `.BfME2WotR` saves on the world map, one taken before the mission
and one after, decoded with `sage_save`. This is the first *measurement* in this document;
everything above it is disassembly.

`WitchKingKampaArmy`'s roster, read as the `02 01`-marked names in `CHUNK_LivingWorldLogic`:

| | before | after |
|---|---|---|
| roster entries | `AngmarWitchking_mod`, **`AngmarDurmarth`**, `AngmarRogash_New`, `AngmarDrauglin` | `AngmarWitchking_mod`, `AngmarRogash_New`, `AngmarDrauglin` |
| entries carry | nothing | `Upgrade_Level_1` / `Upgrade_Level_2` per hero |

Three things follow, and none of them is an inference:

**The roster is replaced, not appended to.** Four entries went in, three came out — the three
survivors — and each came out carrying the upgrades it had earned by the end of the battle. Had the
harvest appended, the army would hold seven. So the correction above corrects itself: the records
are consumed as they deploy and the harvest puts survivors back.

**`Default = Yes` cannot survive that, because it is a property of the record.** The four
`Default = Yes` records came from the template (`0x0071AD41`, which runs once, in the army
constructor). Deployment consumed them. The harvest's replacements are built by `0x0080ECA7`,
which zeroes `+0xD5`. So after one battle the army has **no** `Default` records left and
`SurvivalThreshhold` — which does persist, on the container at `+0x60` — has nothing to fall back
to. The keyword pair can only ever have applied to the first deployment, and it was spent there.

**The dead hero is not destroyed; he is moved into the second Angmar hero list.** After
`WitchKingKampaArmy`'s roster the Angmar player region holds a second list of heroes — before the
mission `AngmarHwaldar_mod`, `AngmarHelegwen`, `AngmarKarsh_mod`, `AngmarMorgramir_mod`,
`AngmarGulzar_Alone`, `AngmarZaphragor`, each written `00 0a <len><name> 00 00 80 3f …` (the float
is `1.0f`), on a ~`0x55`-byte stride. **Those six are `MorgomirArmy`'s `ArmyEntry` rows, six for
six** — including `AngmarZaphragor`, which distinguishes them from `LWB_AngmarFortress`'s
purchasable-hero list, whose members are Drauglin/Androl/WitchKing/CreateAHero instead.

After the mission the same six are there — in reverse order — **plus a seventh element,
`AngmarDurmarth`** at the same stride, written `00 0a 0e "AngmarDurmarth" c2 23 38 43 …`: a
different float (`184.14f` against the six's `1.0f`), four upgrades attached
(`Upgrade_MiniHordeLvl2`, `Upgrade_MiniHordeLvl1`, `Upgrade_Level_2`, `Upgrade_Level_1`) that none
of the six carry, and immediately after it a **`HIDurmarth`** reference — which in Edain is a
`ConstructButtonImage`, on `LWB_AngmarFortress`'s `ArmyToSpawn` entry for `DurmarthArmy`. He also
appears twice under a `01 01 00` marker beside `WOTRKeepAlive`, `AngmarDarkDunedain`,
`AngmarDarkRanger` and `GondorGandalf_mod`.

This is consistent with the static lead — `0x0071AE2D` removes a record from a roster and, when the
template is `KindOf HERO` (`tmpl+0x113` bit `0x04`), calls `0x006E4853` to file it on the owning
`LivingWorldPlayer` at `+0x1D4` — but the save alone does not prove that the list in the file *is*
that vector, and the strides do not match (a save is xfer-serialised, so they need not). What the
save does establish is the movement: **out of one hero list, into another, with his upgrades and a
build-button reference attached.**

> Neither save contains the strings `Morgomir_Army` or `MorgomirArmy`, though it contains
> `WitchKing_Army` / `WitchKingKampaArmy`. So either an army's name strings are not always written,
> or the six-name list is written for an army that is not yet spawned — `Morgomir_Army`'s
> `SpawnArmy` is in a later act than the one played here. Unresolved, and it decides whether a hero
> filed into that list is *in another army* or *nowhere visible*.

### What this makes the real question

Not "how do I stop the hero dying" but **"where did he go, and is he offered there"**. The
`HIDurmarth` reference is the tell: it is the build button `LWB_AngmarFortress` uses to spawn
`DurmarthArmy`, and it did not exist in the save before he died.

The cheapest discriminator costs nothing and needs no tooling: **look at the Angmar fortress's
hero-build menu on the world map after the mission.** If Durmarth's button is there, "dead" means
"returned to the fortress as re-buyable", the engine is behaving, and the fix is authoring — how
that building is presented — not a patch. If it is not there, he is filed into a list nothing
surfaces, and the question becomes which list.

After that, in order of cost:

1. **Check whether `Morgomir_Army` has spawned yet.** Its `SpawnArmy` is in a later act. If the
   six-name list is that army's roster and the army is not on the map, a hero filed into it is
   invisible by construction — and simply advancing to that act would make him reappear.
2. **Patch `0x0071AE2D`.** It is the single site where a hero leaves a roster, it already knows the
   record is a hero, and it holds the owning player. Re-adding the record instead of only filing it
   would give BFME1's behaviour at one call site. Not built, and not worth building until the two
   checks above are done — the destination list exists for a reason, and overriding it blindly is
   how the last two recommendations went wrong.

## Resolved: the hero is not dead, he is back in the fortress queue

**Confirmed in game, 2026-08-28.** After the mission Durmarth is offered from the Angmar
fortress's hero build-up like any other hero — and, unlike the heroes that are still in an army, he
is offered *without* the marker saying he already belongs to one. That is the engine correctly
recording that he left `WitchKingKampaArmy`.

So the premise this whole document opened with is wrong, and the RotWK behaviour is not permadeath:

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
[`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py) — **does not work**,
and the reason is worth writing down rather than discovering later. `MergePlayerArmy` resolves
`SourceArmy` through `findArmyByScriptingName` (`0x006B53A4`), which matches `army+0x1C`, copied
from a `SpawnArmy` block's `ScriptingName`. **`ArmyToSpawn` has no `ScriptingName` field** — the
keyword appears zero times in `livingworldbuildings.ini` and the block's schema does not carry it —
so a fortress-bought army has no name for a script to address it by. Merging one back in would need
either a way to name it or a `MergePlayerArmy` that can select an army some other way.

### The options, now that the behaviour is known

| | what | cost |
|---|---|---|
| **Accept and tune** | the hero *is* recoverable, with his upgrades. `BuildTime` on his `ArmyToSpawn` is the dial | one INI number |
| **Prevent the death** | `UNIT_AFFECT_OBJECT_PANEL_FLAGS(<hero>, 'Indestructible', …)` in the mission — already used on Rogash in `map kampa angmar 01` | per-mission scripting |
| **Patch for true parity** | at battle end, re-add to the army any hero record that was in it at battle start and has no survivor | a real patch, see below |

The patch is **not** the `0x0071AE2D` change suggested in the previous revision of this document.
That site fires during ordinary deployment too — every hero leaves the roster to become a map
object — so re-adding there would break the normal path. The change belongs at the harvest
(`0x00811E1F`), which is the only place that knows a battle has ended, and it needs the army's
pre-battle hero list to compare against. Nothing records that today.

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

Two things fall out, and the second one is load-bearing for this whole investigation.

### The actual difference between the games

| | BFME1 | RotWK |
|---|---|---|
| roster after a battle | survivors **plus the dead hero**, all with their upgrades | survivors only |
| where the dead hero goes | **stays in his army** | out of the army, into the faction's fortress hero-spawn queue |

That is the complaint, exactly as it was originally stated, and it is now measured on both sides
rather than argued from string counts. RotWK does not destroy the hero and does not lose his
upgrades — it *relocates* him, and the army permanently loses a member.

### BFME1 does write battle results back — the parity document is wrong about this

[`living-world-parity.md`](living-world-parity.md) §3 says of BFME1: *"each battle instantiates
from that roster afresh, and **nothing ever writes back** — so a hero killed in a battle is still on
the roster afterwards and is instantiated again next time."* The conclusion is right and the reason
is wrong. `Evil_SarumanPlayerArmy` went into mission 1 holding **one** entry and came out holding
**six**: five surviving Isengard hordes it did not have before, each tagged `Isengard`, plus Saruman
carrying an `Upgrade_SarumanFireBall` he did not have before either. BFME1 harvests a battle into
its living-world armies just as RotWK does.

So the framing "BFME1 has no carryover machinery, heroes came back because death was never
recorded" is wrong. The string counts behind it are accurate — BFME1's binary contains no
`Carryover` string, no `CREATE_UNIT_REVIVAL_ENTRY`, no `ArmyCarryoverPoints` — and the inference
from them to *behaviour* was not. Both games write back. **They differ only in what they do with a
hero record that has no surviving object**, which is a far narrower difference than "RotWK added
persistence and persistence of death is the problem", and a far better patch target.

### What that makes the patch — built

One rule, at one place: **at the end of a battle, a hero record that was in an army and has no
surviving object should be written back to that army rather than filed on the player.** That is
BFME1's behaviour stated in RotWK's terms, and it is
[`hero-army-carryover`](../../patches/experimental/hero_army_carryover.py).

Two hooks, one on each side of the battle, because the harvest alone cannot know what the army held
before it:

| site | stock | becomes |
|---|---|---|
| `0x0062565A` | `call 0x008125FC` — the battle-start restore of each living-world player's money, sciences and upgrades | the same call, then **capture** |
| `0x0062667C` | `call 0x00811E1F` — the harvest | the same call, then **restore** |

**Capture** walks `TheLivingWorldLogic+0x8C..0x90` (the players) and each player's
`+0x1E4..+0x1E8` (its armies), and for every roster record whose template is `KindOf HERO`
(`0x007800DC` resolves the template, `tmpl+0x113` bit `0x04`) takes a **reference** — `record+0xC0`
incremented — storing it beside the army's id from `container+0x1C`. `0x008125FC` runs before any
army deploys, which is the only moment the roster still holds what the army is about to take in.

**Restore** looks each army up again by id (`0x006B5351`), and if no record in its roster now
compares equal by name (`0x004065AA` on `record+0x04`) to the held one, appends the held record
back (`0x00811951`) — then releases the reference either way. A survivor is already there under his
own name and is skipped.

What returns is the **pre-battle record itself**, not a copy: level, upgrades and quantity are what
the hero took into the battle. Progress made during the battle he died in is not kept, because the
engine only ever writes that onto a harvested survivor record and there is none. BFME1 appears to
keep the final state — Saruman came back with an `Upgrade_SarumanFireBall` the earlier save does
not show — so that is the one deliberate divergence.

The battle-start hook's caller already gates on `TheLivingWorldManager`, so a skirmish or a linear
mission reaches neither hook. Twenty-eight tests, static, hence `experimental`.

## Runtime result: the patch works, and it keeps the mission's progress

**Played 2026-08-28** with `hero-army-carryover` applied and `Persistent = Yes` on
`WitchKingKampaArmy`'s entries. `WitchKingKampaArmy`'s roster, read the same way as every save
above:

| | roster after the mission |
|---|---|
| before the mission (unpatched run) | `AngmarWitchking_mod`, `AngmarDurmarth`, `AngmarRogash_New`, `AngmarDrauglin` — **no upgrades on any of them** |
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
patch's own description says the hero stays buyable. Anyone who later reads the duplicate as a bug
has to argue with those first.

The reasoning is kept for whoever revisits it anyway. Suppressing the
engine's filing would be the way to do it - `0x0078100E`'s inner loop already asks
`0x006E301F(lwPlayer, entry)` before choosing between two paths, so there is a decision point to
hook. **Removing the entry afterwards would not be**: `LivingWorldPlayer+0x1D4` is a vector of
`0xE8`-byte entries **by value** (`0x006E3B88` constructs it, `0x006E3EF0` destroys it through
`0x006B1688`), each owning `AsciiString`s and an upgrade list, so erasing one means destructing and
shifting rather than a `memmove` - the kind of hand-written surgery that corrupts a heap.
