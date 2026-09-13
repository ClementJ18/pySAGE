# Why a summoned unit never comes home — `Object+0x47C` and the chain of custody

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-09-12 against
`game.dat`. **Not runtime-verified** — every claim below is a reading of the machine code.

## The question

`KindOf = ARMY_SUMMARY` is what marks an object as "goes home with the player" when a War of the
Ring battle ends. A recruited unit carrying it arrives on the strategic map. A **summoned** or
**spawned** unit carrying the same flag does not. The flag is not the whole rule.

## The harvest has four filters, and the flag is only one of them

`LIVING_WORLD_BATTLE_HARVEST` (`0x00811E1F`) walks the object list by `obj->[0x8C]` and keeps an
object only if all four hold:

```asm
00811e79  call 0x68b678                 ; Object::getControllingPlayer
00811e86  cmp  dword [eax + 0x3cc], -1  ; 1. the owner is a living-world player
00811e8d  je   skip
00811e93  mov  eax, [edi + 4]           ;    the ThingTemplate
00811e96  test byte [eax + 0x118], bl   ; 2. KindOf = ARMY_SUMMARY   (bl = 1)
00811e9c  je   skip
00811ea2  test byte [edi + 0x458], bl   ; 3. an object flag, never set (see below)
00811ea8  jne  skip
00811eaa  mov  eax, [edi + 0x47c]       ; 4. the living-world ARMY ID
00811eb0  test eax, eax
00811eb5  je   skip                     ;    zero -> not carried, flag or no flag
```

**Filter 4 is the answer.** The kept object is not merely recorded, it is *filed*: the new `0xD8`
roster record is appended to `findArmyById(obj->[0x47C])->[0x78]` (`0x0080FAD4` → `0x006B5351` →
`0x00811951`). The harvest has no notion of "the player's army" — only "the army named by this
object". An object that names no army has nowhere to go, so it is dropped.

`Object+0x47C` is zeroed by the `Object` constructor at `0x00699CD8`, alongside `+0x478`, `+0x480`
and `+0x484`. Zero is the default, and nothing on the summon path ever changes it.

### Filter 3 is dead

`Object+0x458` is a bitfield byte. Bits `0x02` (`0x0068B30A`), `0x04` (`0x0068B8F4`), `0x08`
(`0x0068BD24`, `0x006936B2`) and `0x10` (`0x005EA625`, `0x005EBEFA`, `0x005EBFBE`, `0x0078150B`)
each have a setter. **Bit `0x01` has none** — across the whole image the only writes that can
reach it are the two zeroing stores in constructors (`0x00699C76`, `0x00679E79`). The ~20
`test byte [reg + 0x458], 1` sites elsewhere read other classes that happen to share the
displacement. On an `Object` this filter never rejects anything.

This supersedes the "still unidentified, mirrored anyway" note on `OBJECT_ARMY_EXCLUDED` in
[`../map-transition.md`](../map-transition.md): the live census that found it set on
`FarmTemplate`, `GondorSpellBook` and `EdainTroopSpawnPoint` is not reproduced by any write site
in the binary, so that reading needs re-measuring before anything depends on it.

## Who writes the army id

Two functions write `Object+0x47C`:

| site | what |
|---|---|
| `0x0069A6F8` | a bare setter, reached only through a vtable slot on the interfaces at `Object+0x6C` and `Object+0x70` |
| `0x0068C17D` | **`Object::setArmyId`** — writes `+0x47C`, then broadcasts the id to every behavior module through virtual slot `+0xB8` of the module's `+0xC` interface (`0x0068C154`) |

`0x0080FD9C` wraps the setter as **`assignObjectToArmy(obj, armyId)`**: it resolves the army,
looks up its team, calls `Object::setTeam` (`0x0068B6CB`) and then `Object::setArmyId`. It is
reached almost everywhere through the `TheGameLogic` thunk at `0x00625E0A`
(`add ecx, 0x184; jmp 0x0080FD9C`).

Every call site of the two, exhaustively:

| site | module / function | what it does |
|---|---|---|
| `0x0062A0DE` | battle-start deployment (`0x00629F34`, the `Player_%d_Start` walk) | seeds the army's own units |
| `0x0080EE0F` | `ArmyRecord::spawnInto` — `createObject` (`0x00780172`) then assign | deploys a roster record |
| `0x007814D9` | `CarryoverUnit` → object | restores a hero from the ledger |
| `0x007978CB` | `CastleMemberBehavior` | fortress → each castle member |
| `0x00799C92`, `0x00799CCC`, `0x0079ADD3` | `CastleBehavior` | fortress → plots and their buildings |
| `0x0088D41C` | `DozerAIUpdate` | builder → the foundation it lays |
| `0x00858B55`, `0x00858BC3` | `FoundationAIUpdate` | foundation → the finished structure |
| `0x008A2536`, `0x008A2789`, `0x008A04D2` | `ProductionUpdate` | **structure → the unit it recruits** |
| `0x008A401A` | `QueueProductionExitUpdate` | the same, for queued exits |
| `0x0087691F`, `0x00873B73` | `HordeContain` | horde → each member joining it |
| `0x00870391` | `OpenContain` | transport → its passengers |
| `0x008B3AF9` | `RespawnUpdate` | survives respawn |
| `0x007C40F4` | a script action | assigns by script |

`ProductionUpdate` is the one that answers "why does a recruited unit work":

```asm
008a250a  call 0x78142f                 ; the produced object
008a2519  mov  eax, [edi + 0x47c]
008a251f  test eax, eax
008a2527  je   0x8a252c
008a2529  push eax                      ; keep its own id if it has one
008a252a  jmp  0x8a2535
008a252c  mov  eax, [ebp - 0x14]        ; else the PRODUCER's
008a252f  push dword [eax + 0x47c]
008a2536  call 0x625e0a                 ; assignObjectToArmy
```

So the id descends a **chain of custody**: army → deployed units → the fortress and its castle
members → the structures a builder erects → the units those structures recruit → the hordes and
transports they join. Everything that comes home is downstream of something the army deployed.

## Why summons are not on the list

The table above is the complete set. Absent from it — checked by exhaustion over every access to
`+0x47C` in the image — is **every object-creation path that is not production**:

`OCLUpdate`, `CreateObjectDie`, `CreateObjectDieIfEldestKindof`,
`DamageFilteredCreateObjectDie`, `SpawnBehavior`, `SpawnUnitBehavior`,
`SummonReplacementSpecialAbilityUpdate`, `ObjectCreationUpgrade`, `ReplaceObjectUpdate`,
`ReplaceSelfUpgrade`, `SlavedUpdate`, `CivilianSpawnUpdate`, `BannerCarrierUpdate`,
`SpawnPointProductionExitUpdate`.

None of them touches `+0x47C`. They reach `THING_FACTORY_NEW_OBJECT` (`0x006D165E`), which takes a
template and a **team** and no creator, so the new object is born with `+0x47C = 0` and stays
there. A spellbook summon, a `SpawnBehavior` escort, a unit created by a death module or by an
upgrade — all of them fail filter 4 no matter what `KindOf` they carry.

Two predictions fall out of the same table, both worth testing before trusting:

- An object produced by a structure that itself has no army id inherits zero —
  `assignObjectToArmy(obj, 0)` resolves no army and returns without writing. Pre-placed map
  structures in a battle map are the case to watch.
- `ReplaceObjectUpdate` and the mount/dismount toggles are not on the list, so a unit that
  transforms mid-battle should lose its army id. `RespawnUpdate` is on the list; they are not.

## "Carry any `ARMY_SUMMARY` regardless of id" — why it is not the cheaper patch

The obvious simplification is to drop filter 4 and keep everything that carries the flag. It does
not save any work, because **the army id is a destination, not a gate**. Twelve instructions after
the test, the record that was just built is filed:

```asm
00811eb2  mov  [ebp + 8], eax       ; the army id, saved
...
00811ef2  push dword [ebp + 8]
00811f04  call 0x80fad4             ; findArmyRoster(id)
00811f0b  je   0x811f18             ; NULL -> the record is dropped on the floor
00811f13  call 0x811951             ; else append
```

`findArmyById(0)` is NULL, so bypassing the test at `0x00811EB5` buys a `0xD8`-byte allocation that
is discarded a few instructions later. Any version of this patch has to **supply** an id, and
resolving one is the bulk of the work. The hook, the cave and the fallback lookup are identical
whether the rule is gated on a dedicated flag or not.

So the choice is not cost, it is blast radius — and that is measurable. Over Edain's 10 450
templates, counting those an `ObjectCreationList` creates or a spawn-module field names:

| | templates |
|---|---|
| carry `ARMY_SUMMARY` | 1 716 |
| ...and are reachable from a non-production creation path | **383** |
| ...of those, also `SUMMONED` — the intended summons | 156 |
| ...of those, **not** `SUMMONED` | **227** |

The 227 are the problem. They are ordinary recruitable hordes that some OCL happens to also
reference — `DwarvenAxeThrowerHorde`, `AngmarDarkRangerHorde`, `ArnorRangerHorde`, the `_Kampagne`
hero variants, story units like `AngmarEalendrilStory`. An unconditional rule makes every one of
them persist when spawned, and the `ARMY_SUMMARY` already on them is **not evidence that the mod
wants that**, because on the OCL path the flag is a no-op today — nobody has ever been able to
express an opinion about it.

(383 is an upper bound on what could change, not a count of what will: many of those OCLs are
campaign or scripted content that never runs in a War of the Ring battle.)

A dedicated flag engages **only when `armyId == 0`**, which is only ever the summon path. It
therefore gives per-template control over the summoned case while leaving recruited carry-over
exactly as it is today — which is precisely the "same template, two provenances" case that the
227 are.

Both are defensible; they differ in policy, not in engineering. **`summon-carryover`
([`../../patches/summon_carryover.py`](../../patches/summon_carryover.py))
implements the unconditional rule**: `ARMY_SUMMARY` means comes home, the flag a mod already
sets is the whole opt-in, and no slot rename or Worldbuilder twin is needed. Adding the gate
later is a two-instruction change to the same cave, so nothing about that choice is closed off.

## `SUMMONED` cannot carry the meaning

`SUMMONED` is index 179, `template+0x11E` bit `0x08`, and Edain sets it on 530 templates — 220 of
which also carry `ARMY_SUMMARY`, so at a glance it looks like the rule could key on it and need no
new token at all.

It cannot. `SUMMONED` is **load-bearing for targeting**: Edain's own `specialpower.inc` filters on
it repeatedly (`ObjectFilter = ANY +HERO -SUMMONED …`), and the engine exposes every `KindOf` bit
to the generic mask compare that `ObjectFilter` and the script conditions use. A template that must
read as `SUMMONED` for a spell to skip it would be forced to come home as a side effect, and a
summon that should *not* persist could not say so without changing what spells do to it. The flag
is already spoken for; overloading it makes the two meanings inseparable.

So the opt-in has to be a **dedicated** bit. The question is only how to get one cheaply.

## Getting a dedicated flag for two dwords

The expensive part of a new `KindOf` is never the bit — it is growing the name table (§1 below).
That cost disappears if the token **replaces a dead slot instead of extending the array**.

Two tokens in the table are dead on both sides — never written by the mod, never read by the
engine:

| index | token | mask bit | Edain uses | engine tests |
|---|---|---|---|---|
| **13** | `HUGE_VEHICLE` | `template+0x109` bit `0x20` | 0 | none |
| 29 | `WAVE_EFFECT` | `template+0x10B` bit `0x20` | 0 | none |

`HUGE_VEHICLE` is the one to take: a Generals-era vehicle size class with no meaning in a game
whose vehicles are siege engines. The engine-side claim is a census rather than a sample — every
one of the 151 instructions in the image that touches `template+0x109` was decoded and its
immediate read. That byte is busy (`INFANTRY` `0x01`, `CAVALRY` `0x02`, `MONSTER` `0x04`,
`MACHINE` `0x08`, `AIRCRAFT` `0x10`, `DOZER` `0x40`, `SWARM_DOZER` `0x80` are all tested, some
heavily) and **bit `0x20` appears in none of them**, in neither the byte tests nor the dword tests
against `+0x108`.

> Watch the immediate parsing if you re-derive this. Capstone prints small immediates in decimal,
> so a filter keyed on `0x`-prefixed operands silently drops every `test byte ptr [eax+0x109], 4`
> and reports `MONSTER` as dead. `MONSTER` and `NO_GARRISON` both fail that way; both are tested.

So the whole flag costs:

| | |
|---|---|
| `game.dat` | repoint **one dword** — name-table slot 13 — at a `FORCE_ARMY_SUMMARY` string in a cave |
| `Worldbuilder.exe` | the same one-dword repoint in its own copy of the table |
| the harvest | the single hook at `0x00811EAA` (§2 below) |

against a 222-entry relocation plus 14 repoints plus a table-sized twin for the append. The bit
tested at the hook is `template+0x109` bit `0x20`.

The rule becomes what was wanted in the first place:

> carry if `ARMY_SUMMARY` **and** (`armyId != 0` **or** `FORCE_ARMY_SUMMARY`)

orthogonal to `SUMMONED`, so a template can be summon-filtered without being kept and kept without
being summon-filtered.

The tooling follows for free: `sage_patch sagepatch` declares the rename as an
`EnumDelta(enum="KindOf", name="FORCE_ARMY_SUMMARY", value=13)`, and `sage_ini --engine` applies it
— so `sage_lint`, the Sublime plugin and the `bfme-ini` skill all know the new token, and flag
`HUGE_VEHICLE` as gone, without another line of work.

**What the rename costs.** A map or INI that already says `HUGE_VEHICLE` stops parsing on a patched
build. Nothing in Edain does, which is the measurement above, but it is a real constraint for any
other mod on the same binary, and it is the reason to prefer `HUGE_VEHICLE` over a token whose name
someone might plausibly have typed. Keeping the old name and simply giving it a second meaning
avoids even that, and avoids the Worldbuilder twin entirely — at the cost of an INI that says one
thing and means another, which is not worth it.

### Resolving the fallback army id

The harvest files a record into a *named* army, so the hook still has to choose one, and this is
where it should come from. The battle bridge (`TheGameLogic+0x184`) holds the **vector of army ids
participating in this battle** at `+0x14 .. +0x18`; `0x0080FF1B` already walks it, returning
`roster->[0x1C]` — the army id — for the first entry whose `roster->[0x14]` is zero.

For each id in that vector, `findArmyRoster(id)` (`0x0080FAD4`) gives the roster and `0x0080F45F`
gives its **team**, which is how `assignObjectToArmy` sets an object's team in the first place. So
the fallback is the army in the battle whose roster's team belongs to the same player as the
object — exact, bounded by the handful of armies in a battle, and entirely engine-derived. That is
better than walking the object list for a sibling that happens to hold an id, which was the earlier
suggestion here.

### The script action is not a way round it

Case **514** of `ScriptActions::executeAction`'s jump table (`0x007CF857`) is live and does assign
army ids: it resolves a team by name through `TheTeamFactory` and calls `assignObjectToArmy` on
every object in it (`0x007C409F`). It is not a substitute for the patch, though — it takes the
battle's army from `0x0080FF1B` rather than matching the owner, it works on named teams rather than
the default team a summon lands on, and it needs someone to author the script into every War of the
Ring battle map. Worth knowing it exists, not worth building on.

The related `*_ASSIMILATE_WITH_ARMY_BY_NAME` trio (ids 540–542) is dead, as
[`dead-script-actions.md`](dead-script-actions.md) records.

## Scoping `FORCE_ARMY_SUMMARY`

Appending a 223rd token rather than renaming a dead one. Kept because it is what the bit costs
if the table has to grow — pieces 2 and 3 apply either way, and pieces 1 and 4 are exactly what
the slot rename above avoids.

### 1. The flag itself is cheap

The `KindOf` name table is `0x00DA0E68`: 222 entries (`ARMY_SUMMARY` at index 128, the last six
`HORDE_MONSTER`, `SIEGEENGINE`, `TROLL`, `SUPPORT`, `AMPHIBIOUS`, `EXPANSION_PAD`), NULL
terminator at `0x00DA11E0`. The parser (`0x0065621C`, reached from the `KindOf` field row at
`0x00DA4148`, offset `0x108`) resolves a token to an index through `0x0042B914` and sets it with

```asm
00655b74  shr  ecx, 5
00655b77  lea  edx, [esi + ecx*4]
00655b7e  and  ecx, 0x1f
00655b82  shl  eax, cl
00655b87  or   [edx], eax
```

— a dword array with no width check. Indices 0–221 occupy dwords 0–6 of the mask at
`template+0x108`, so **index 222 lands in dword 6, bit 30 — `template+0x123` bit `0x40` — inside
space the template already allocates.** No struct growth, and no risk to neighbouring fields.

Cost is the table relocation: the terminator is immediately followed by another table
(`0x00DA11E4`), so the 222 entries must be copied to a cave with the new one appended, and the
**14** references repointed (`0x00655B67`, `0x00655BA7`, `0x00655C12`, `0x006AAD0F`, `0x006AAD20`,
`0x006AAD25`, `0x007079FF`, `0x007B3CDB`, `0x007B67E3`, `0x007B67F3`, `0x007B6869`, `0x007B6885`,
`0x007B6899`, `0x007B68DD` — all `.text`, none in data). The `ARMY_ENTRY_DEFAULT_TABLE` relocation
in `hero-army-carryover` is the existing pattern.

### 2. The hook is one clean site

`0x00811EAA` is not a branch target — the function's jumps land on `0x00811E77`, `0x00811ED8`,
`0x00811EDA`, `0x00811EE7`, `0x00811F18`, `0x00811F27`, `0x00811FC1`, `0x00811FC2`. Stock bytes:

```
00811eaa  8b 87 7c 04 00 00    mov eax, [edi + 0x47c]
```

Six bytes, replaced by `call <cave>` plus one `nop`. The cave takes the object in `edi`, returns
the effective army id in `eax`, and the stock `test eax, eax` / `je` two instructions later does
the rest unchanged:

```
    mov  eax, [edi + 0x47c]
    test eax, eax
    jnz  done                  ; it already has one
    mov  eax, [edi + 4]
    test byte [eax + 0x123], 0x40   ; KindOf = FORCE_ARMY_SUMMARY
    jz   done                       ;   (eax reloaded as 0 on this arm)
    <resolve a fallback army id>
done:
    ret
```

### 3. The fallback army id is the real design question

The harvest files each record into a **named** army, so the cave has to choose one. The engine
offers no "the army this player is fighting with" lookup: `0x006B5DE0` resolves a living-world
*player*, not an army, and the player carries only `+0x3CC`, its living-world player id.

The workable answer is to borrow one from the battle. Walk the object list
(head at `TheGameLogic+0xAC`, next at `obj+0x8C`) for an object with the same controlling player
(`0x0068B678`) and a non-zero `+0x47C`, and use that id — cached per player in the cave, since the
harvest runs once per battle. It is correct whenever the player deployed an army at all, which is
every real case; a player whose entire roster died and whose only survivors are summons gets the
present behaviour, which is acceptable.

Doing this at **creation** time instead — propagating the creator's id the way `ProductionUpdate`
does — would be more precise, but `THING_FACTORY_NEW_OBJECT` has no creator argument, so it would
mean hooking each of the fourteen spawn modules separately. The harvest-side hook is one site and
covers all of them.

### 4. Worldbuilder needs the twin

Worldbuilder is an assert-enabled build with its own copies of the name tables, and an unknown
token in a mask parse ends startup with exit code 0 and no dump. A mod writing
`KindOf = ... FORCE_ARMY_SUMMARY` breaks the editor unless the same table relocation is applied to
`Worldbuilder.exe`. That is the established seven-twin pattern in the README, and it is part of the
cost rather than an optional extra.

### What is not in scope

The flag changes only what the harvest keeps. It does not give a summoned unit upgrades or
veterancy it never had — `Object::toArmyRecord` (`0x0069192F`) handles that identically for every
object — and it does not change what happens to a summon whose lifetime expires before the battle
ends, which is dead before the walk ever sees it.
