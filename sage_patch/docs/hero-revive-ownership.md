# Who owns a dead hero: the revive ledger and dominated heroes

Why a hero converted with `DominateEnemySpecialPower` can end up permanently recruitable by the
player who converted him. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`.
Everything below is **statically recovered**; none of it has been confirmed against a running game.

## TL;DR

- A player's revivable heroes live in one vector at `Player+0x758` (the hero ledger). Entries are
  `0xE8` bytes, the hero's template name at `+0xE4`. An entry records **no owner** - being in the
  vector *is* the ownership claim.
- On a lethal hit, `RespawnUpdate` files the dead hero into
  **`object->getControllingPlayer()`'s** ledger (`0x008B385F`). A hero who dies while temporarily
  defected is controlled by the converter, so the entry lands in the converter's ledger.
- That is not cosmetic. The ControlBar's revive populate makes a **second pass** that hands every
  ledger entry with no roster slot its own spare `REVIVE` button (`0x0094428F`). A foreign hero in
  your ledger becomes a buyable button in your fortress, and the rightful owner never gets the
  entry at all.
- The engine's only defence is one call: the same death path first runs
  `Object::restoreOriginalTeam` (`0x008C563E`) when the object carries `ObjectStatus`
  `TEMPORARILY_DEFECTED`. That defence is narrow - see
  [Where the guard does not run](#where-the-guard-does-not-run).

## 1. The ledger

`Player+0x758` is a vector of `0xE8`-byte entries; `REVIVE_MGR_OFFSET` and
`PLAYER_HERO_LEDGER_OFFSET` in `addresses.py` are the same field. `Player::getHeroLedger` is
`0x005EA653`.

| address | what it is |
|---|---|
| `0x0078131E` | `findEntry(ThingTemplate *what, Int id, Int ordinal) -> index`, `-1` if absent. Matches `tmpl+0x64` (the name) against `entry+0xE4`; with `id == -1` it takes the *ordinal*-th entry of that name, otherwise it matches `entry+0xB4`. |
| `0x00781298` | `getEntry(index) -> entry *` |
| `0x00780C2F` | `getTemplate(index) -> ThingTemplate *` |
| `0x00780C46` | `canRevive(index) -> Bool` |
| `0x00780DD4` | entry constructor **from an Object** - snapshots level, experience, upgrades, the `0x90`-byte state block, and the name |
| `0x00780713` | entry constructor **from a ThingTemplate** |

Three sites put entries in, and only three:

| address | signature | when |
|---|---|---|
| `0x00781792` | `addEntry(Object *hero, Bool isAutoSpawn)` | a hero dies - **the only caller is `0x008B3879`** |
| `0x00781801` | `insertEntry(ThingTemplate *, Player *)` | seeding a player's roster from `PlayerTemplate+0x198`, looped at `0x008BC4E3` |
| `0x00781861` | `insertEntry(entry, player)` | the WorldBuilder "is allowed to revive" script action (`0x007C6D8E`), and save-game load (`0x006B17EA`) |

Nothing in an entry says who it belongs to. Whichever `Player` the vector hangs off owns the hero.

## 2. A ledger entry becomes a buyable button

The ControlBar's revive populate walks the producer's `CommandSet` in two passes.

**Pass 1** (`0x00943F97`) is roster-driven. For revive slot ordinal *n* it asks
`Player::getBuildableHeroName(n)` (`0x006AB249`, reading `PlayerTemplate+0x198` then `+0x18C`),
resolves the template, and looks the template up in the ledger. The ledger index goes on the button
(`button+0xC0`), or `-1` when the hero has no entry. It also marks that ledger index in a local
used-flag array at `[ebp-0x84]`.

**Pass 2** (`0x0094428F`) is ledger-driven. It walks `min(ledgerSize, slotCount)` ledger indices,
skips any index pass 1 already claimed (`0x009442BB`), and gives each remaining entry the next free
`REVIVE` slot in the `CommandSet`.

Pass 2 is what the script action needs: it is how a hero the faction roster never mentions can be
offered at all. It is also what turns a stolen ledger entry into a working recruit button - a
fortress carries far more `REVIVE` slots than its roster uses (see
[`ai-revive-gate.md`](ai-revive-gate.md)), so there is nearly always a free one.

The revive index in `QUEUE_UNIT_CREATE` is this ledger index, not a roster position, which is what
[`hero-recruitment.md`](hero-recruitment.md) observed from the order stream as "a killed hero
rejoining at the tail".

## 3. The filing site

Heroes carry `Body = RespawnBody`, or its `DelayedDeathBody` / `FreeLifeBody` subclasses.
`RespawnBody::internalChangeHealth` is `0x008C553F`, vtable `0x00C72490` slot 9. Its death arm runs
when the delta is at least the current health:

```
008c5588  cmp  byte [edi+0x68], 0        ; CanRespawn
008c558c  mov  byte [ebp-0xe], 1         ; lethal
008c5590  jne  0x8c5598
008c5592  mov  byte [ebp-0xd], 1         ; CanRespawn = No -> permanent death
008c5598  ...  killer := findObject(damageInfo->sourceID)
008c55be  call OBJECT_FILTER_ALLOW       ; PermanentlyKilledByFilter, judged against the
008c55ca  mov  byte [ebp-0xd], 1         ;   victim's *current* controlling player
008c55db  call ActiveBody::internalChangeHealth
008c5618  call Object::findModule("RespawnUpdate")   -> esi
008c5623  jne  0x8c566e                  ; permanent death -> 0x8b3349, no filing
008c562d  je   0x8c5679                  ; no RespawnUpdate -> nothing at all
008c563e  call 0x0069aba7                ; restoreOriginalTeam, if TEMPORARILY_DEFECTED
008c5647  call OBJECT_TEST_STATUS        ; INHERITED_FROM_ALLY_TEAM
008c5652  call 0x008b3349                ;   set   -> no filing
008c565d  call 0x008b3744                ;   clear -> file the ledger entry
008c5662  call Object::kill
```

`0x008B3744` reads the hero's level, picks the matching `RespawnRules` row for cost and time, and
then decides the owner in one instruction:

```
008b385f  call 0x0068b678                ; Object::getControllingPlayer  <-- the whole decision
008b3868  cmp  byte [esi+0x40], 0
008b386c  lea  edi, [eax+0x758]
008b3879  call 0x00781792                ; addEntry(hero, isAutoSpawn)
```

`getControllingPlayer` is `[obj+0x31C] -> Team::getControllingPlayer`, so it is live: whoever holds
the team at that instant gets the hero.

## 4. How domination moves the team

`DominateEnemySpecialPower`'s per-target routine is `0x008D0F6C`. It reads `PermanentlyConvert` from
module data `+0xDC` (`0x008D0FF2`) and calls `Object::defect(Object *newOwner, Bool permanent)`
(`0x00699368`) on the victim.

- **Permanent** - a plain `setTeam`. No status bit and no restore: the hero really is yours, and the
  ledger entry landing in your list is the intended outcome.
- **Temporary** - finds the victim's `TemporarilyDefectUpdate` by module-class name key
  (`0x00699438`) and calls `TemporarilyDefectUpdate::defect` (`0x008D0BF3`), which calls
  `Object::setTemporaryTeam` (`0x00699513`): set `ObjectStatus` 62 `TEMPORARILY_DEFECTED`, then
  `setTeam` **without** recording a new original-team name. The restore frame goes in `module+0x20`.

  If the *caster's* template is `KindOf SPELL_BOOK` (`0x008D0C36`, template byte `+0x117` bit
  `0x08`), the module's wake frame is set to never and `+0x20` is left at zero, so a spellbook
  domination never expires - though the status bit is still set.

Every object inherits `TemporarilyDefectUpdate` from `default/object.ini`, so the module is always
present.

## 5. The guard, and where it does not run

`Object::restoreOriginalTeam` (`0x0069ABA7`) requires `TEMPORARILY_DEFECTED`, clears it, and calls
`0x0069AB22`, which:

1. returns if the object has no team;
2. returns if **`Object+0x320`**, the recorded original-team name, is empty (`0x00401E64` is
   `AsciiString::isEmpty`);
3. resolves it with `TheTeamFactory::findTeam` (`0x007A7483`) and returns if that misses;
4. otherwise calls `setTeamAndRecordName` (`0x0069954A`).

`Object+0x320` is written by `setTeamAndRecordName` and nothing else. The `Object` constructor calls
it for the team the object is built with (`0x00699EC4`), storing `prototypeName + '/' + team name`.

### Where the guard does not run

- **The permanent-kill arm.** `CanRespawn = No`, or a killer matching `PermanentlyKilledByFilter`,
  takes `0x008C5623`'s branch, which restores nothing. That arm files nothing either, so it costs
  the rightful owner his hero rather than handing him over. Note that the filter is judged against
  the *converter's* player, so an `ALLIES` or `ENEMIES` filter reads backwards for the duration of
  a conversion.
- **A body that is not `RespawnBody`-derived**, since the restore lives in that class.
- **A clobbered `Object+0x320`.** `setTeamAndRecordName` has **51 call sites**; any of them reaching
  a dominated hero overwrites the recorded original team with the converter's team, after which the
  restore returns him to his captor. This is the failure mode to test first, because it produces the
  reported symptom with the guard apparently intact.

## 6. Patch scope

**The single choke point is `0x008B385F`** - one `call rel32` (`e8 14 7e dd ff`), the sole entry to
`addEntry`, with no branch landing in its five bytes. Everything the fix needs is live there: `ebx`
is the dying hero and `eax` becomes the player the entry is filed under.

Recommended shape, in the style of
[`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md)'s cave-owned ledger:

1. **Record the truth at conversion time.** Hook `TemporarilyDefectUpdate::defect` (`0x008D0BF3`)
   and store `{ObjectID -> original Team *}` in a cave-owned table before `setTemporaryTeam` runs.
   Deliberately not `Object+0x320`, so the fix does not inherit the clobber risk of §5.
2. **Consult it at the filing site.** Replace the `call getControllingPlayer` at `0x008B385F` with a
   call into the cave: look the hero's `ObjectID` up in the table, return that team's player on a
   hit, tail into the stock `0x0068B678` on a miss. A missing entry always degrades to stock
   behaviour.
3. **Drop the entry** when the conversion ends - on the module's own restore (`0x008D0DB7`) and on
   `Object` destruction - and clear the table on `GameLogic` reset, the way the wall ledger does.

Cost: two `rel32` edits, a cave of a few hundred bytes plus the table. No engine call the site does
not already reach.

**Cheaper alternative**, if §5's third bullet turns out not to be the cause: a single hook at
`0x008B385F` that calls `Object::restoreOriginalTeam` (`0x0069ABA7`) before falling through to the
stock owner query. It is idempotent, since the function no-ops unless `TEMPORARILY_DEFECTED` is set,
and it closes the permanent-kill arm and any non-`RespawnBody` body for free. It cannot help against
a clobbered `Object+0x320`.

**Deliberately out of scope.** Pass 2 of the ControlBar populate (§2) is what makes a stolen entry
visible, and gating it on the roster would hide the symptom rather than fix it. It would also break
the "is allowed to revive" script action, which exists precisely to put an off-roster hero in a
player's list. Fix the ownership, not the display.

### What to measure before writing a byte

All of §5 is a reading of the machine code, and the reported behaviour says something in it is
wrong. Two live checks settle which:

- With `sage_live`, read the converted hero's `Object+0x320` while he is dominated. If it names the
  converter's team, the clobber is the cause and step 1 above is required.
- Read the length of `Player+0x758` for both players immediately after the dominated hero dies. The
  side that grows by one is the side the engine believes owns him.

## 7. The INI side

`SpecialAbilityWormtongueCorrodeAllegiance` already targets heroes only
(`ObjectFilter = NONE +HERO ...`) and its `ReloadTime` of 240000 clears the
`DefectDuration` rule that `default/object.ini` shouts about, including the 15000 that
`object/GrimaHeldenbekehrung.inc` substitutes. Every other `DominateEnemySpecialPower` in the tree
excludes heroes with `-HERO`, which is why nothing before this ability met the ownership defect.
