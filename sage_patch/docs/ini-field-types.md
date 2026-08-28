# Typing an INI field from the engine

`sage_ini`'s schema marks a field it has not yet given a real type with `Untyped`. Guessing those
from corpus values is unreliable - a field the corpus only ever writes one way looks like anything.
The engine settles it: every INI keyword is a row in a field-parse table, and the parse function in
that row *is* the field's type.

This is the write-up of the pass that used that to type 262 of `sage_ini`'s 331 `Untyped` fields.
It records the method, the tables it recovered, and the traps that cost time.

## Finding the table when the block is not in `ini-types.json`

`docs/ini-types.json` covers 144 blocks and 200 modules, which is not all of them - `InGameUI`,
`CastleBehavior`, `RiderChangeContain`, `Color` and dozens more are absent, and a block that *is*
listed can still be missing a keyword, because a block's keywords are spread over one table per
class in its inheritance chain.

Go from the keyword instead. A row is `{const char *name, ParseFn parse, void *userData,
UnsignedInt offset}`, so **a data slot holding the keyword string's pointer is a row start**:

```sh
python .claude/skills/sage-engine-re/explore.py keyword Rider1
```

```
  table 0x00daee78 (Rider1 is row 0)
  [ 0] 'Rider1'         parse=0x00881681 userData=0x00000000 offset=0x1b8 (440)
  ...
  [ 7] 'Rider8'         parse=0x00881681 userData=0x00000000 offset=0x260 (608)
  [ 8] 'ScuttleDelay'   parse=0x0073a429 userData=0x00000000 offset=0x278 (632)
  [ 9] 'ScuttleStatus'  parse=0x0042e956 userData=0x00000000 offset=0x0 (0)
  [10] (terminator)
```

The command walks back to the table's first row and forward to its terminator, so one keyword
hands over the whole block. (`RiderChangeContain` takes eight riders, not the seven the schema
had.) A keyword that is in no table at all is a keyword this build does not have - `EjectPilotDie`
`VeterancyLevels`, `Weapon` `AntiMask`, `Object` `ExperienceRequired` and `OverrideableByLikeKind`
have no string in the image, so they are dead schema entries rather than untyped ones.

Two ways to name a table when several claim the same keyword (`Weather`, `Priority`, `Shader`,
`Type` are each in half a dozen): score candidate tables by how many of the block's *other* fields
they carry, and check the winner covers at least half its own rows. A low score means the table is
somebody else's - that is how `System.Priority` in `particles.py` first came back as the audio
priority list, when the FXParticleSystem `System` block has no field table at all.

## Reading the type off the parse function

`scripts/module_defaults.py` already names 75 parse functions (`PARSE_TYPES`). For one it does not,
disassemble it and look at what it touches - the name arrays it resolves tokens against and the
format strings it complains with are the whole answer:

| parse fn | field it types | what the body shows |
|---|---|---|
| `0x006c7fe6` | `WeaponSet.AutoChooseSources` | slot array + `FROM_PLAYER FROM_SCRIPT FROM_AI` |
| `0x006c9992` | `WeaponSet.OnlyAgainst` | slot array, then the `KindOf` bit parser |
| `0x006c9589` | `WeaponSet.OnlyInCondition` | slot array, then the ModelCondition bit parser |
| `0x006cb5ab` | `Weapon.WeaponBonus` | condition array `0x00da1740` + field array `0x00da179c` |
| `0x005d86f1` | `Armor.Armor` | literal `Default`, then the `DamageType` array |
| `0x0076246e`/`0x00762311`/`0x0076238a` | `DamageFX.*` | literal `Default`, then the DamageFX array `0x00da5110` |
| `0x0073a396` | `ParticleSystem.InitialDelay` | `CONSTANT UNIFORM GAUSSIAN TRIANGULAR LOW_BIAS HIGH_BIAS` - a random variable |
| `0x0042f334` / `0x0042f382` | `AudioEvent.PitchShift` / `Delay` | two `%f` / two `%d` - a float / int range |
| `0x00778c93` | `InGameUI.*Font` | a `%d` and a `yes` - `"Family" <points> <bold>` |
| `0x0073d3e0` | `Object.DisplayNameStrategic` | `"Label '%s' not found in game text"` - a string-table label |
| `0x008ed575`/`0x008ed5c4` | `ThreatBreakdown.AIKindOf`, `CombatChainDefinition.TargetTypes` | the AI unit-class array + `invalid AI_KINDOF` |
| `0x00972338` | `Sound.Duck` | `AudioMap:`/`Sound:`/`Multiplier:` - a colon-keyed record |
| `0x0073e716` | `Object.RemoveModule` | `RemoveModule %s was not found for %s.` - a module tag |

## Name arrays recovered here

Each of these was a field the schema could not type; the array behind it is now an enum in
`sage_ini/model/enums.py`.

| array | members | field |
|---|---|---|
| `0x00d99ef8` | `MANUAL LOOP ONCE LOOP_PINGPONG PLAY_TO_FRAME LOOP_BACKWARDS ONCE_BACKWARDS` | any `AnimationMode`, `Object.AnimMode` |
| `0x00d99f18` | `RANDOMSTART START_FRAME_FIRST ... MAINTAIN_FRAME_ACROSS_STATES4` | `ModelConditionState`/`AnimationState` `Flags` |
| `0x00da12fc` | `PREFER_MOST_DAMAGE ... USE_WEAPONSET_DEFAULT_CRITERIA` | `WeaponSet.DefaultWeaponChoiceCritera` |
| `0x00da1740` | `GARRISONED ... SOLO_AI_HARD` (22) | `WeaponBonus` condition |
| `0x00da179c` | `DAMAGE RADIUS RANGE RATE_OF_FIRE PRE_ATTACK FIRING` | `WeaponBonus` field |
| `0x00da748c` | `AWAY_FROM_TREES MOVING FIRING_* TAKING_DAMAGE USING_ABILITY` | `InvisibilityNugget.ForbiddenConditions` |
| `0x00d9e3a8` | 19 debris dispositions | `CreateDebris.Disposition` |
| `0x00da37f8` | 17 shadow styles | `DecalTemplate.Style`, `RadiusCursorTemplate.Style`, any `Shadow` |
| `0x00dad904` | `DEFAULT DISABLED_*` (12) | `ProductionUpdate.DisabledTypesToProcess` |
| `0x00c4e08c` / `0x00c4e0a0` | `NONE IN OUT INOUT STOP` / `Opacity Additive` | `Object.FadeTypeFor*` / `FadeMethod` |
| `0x00d9edd0` | `Men Elves Dwarves Isengard Mordor Wild Angmar Arnor Neutral` | `SubClass.DefaultFaction` |
| `0x00c2d5e0` | `DO_NOT_USE_THIS_TYPE Healing LeaderShip GloriousCharge Dominate Cursed Buff Debuff Poison` | `BuffNugget.BuffType` |

Lookup lists (`{name, value}` pairs, 8 bytes a row, so read them as pairs not as a `char*[]`):

| array | members | field |
|---|---|---|
| `0x00bf0b50` | 86 keys, `KEY_ESC=1` ... `KEY_NONE=0` | `CommandMap.Key` |
| `0x00bf0e08` | `DOWN=0 UP=1 DOUBLEDOWN=2` | `CommandMap.Transition` |
| `0x00bf0e28` | `NONE CTRL ALT SHIFT CTRL_ALT SHIFT_CTRL SHIFT_ALT SHIFT_ALT_CTRL` | `CommandMap.Modifiers` |
| `0x00bf0b08` | `CONTROL INFORMATION INTERFACE SELECTION TAUNT TEAM MISC DEBUG` | `CommandMap.Category` |
| `0x00c8b750` | `TITLE MINORTITLE NORMAL COLUMN` | `Credits.Style` |
| `0x00bf3350` | `SCORCH_1`..`SCORCH_9`, `RANDOM=-1` | `TerrainScorch.Type` |

## Traps

**Adjacent name arrays run into each other.** The LOD arrays at `0x00d9e6bc` are
`Low Medium High UltraHigh` immediately followed by `VeryLow Low Medium High UltraHigh` with **no
NULL between them**, and `INI::scanIndexList` (`0x0042b914`) only stops at a NULL - so
`StaticGameLOD.ModelLOD` really does accept `VeryLow`, and every LOD keyword accepts every LOD
token. Cut such an array where the *next* field's `userData` points, and treat the result as the
intended set rather than the accepted one.

**Index lists are case-insensitive.** `scanIndexList` compares each row through the CRT function
pointer at `[0xbd051c]` rather than inline - and the shipped data proves what that comparison is:
`LivingWorldBuilding Type = Barracks` loads against an array whose member is `BARRACKS`.
Where the corpus spells a token differently from the engine (`ViewsToFade = TACTICAL` vs the
engine's `Tactical`), the schema enum has to be case-insensitive or every valid line warns.

**`S:<name>` is a real object-filter member.** The engine builds it by prefixing a template name
with the literal `"S:"` at `0x00762a83`; `FXList` `Sound.SourceObjectFilter` uses it 32 times in
the base corpus. A filter parser that only accepts `KindOf` and object names rejects valid data.

**A keyword can be typed and still be a record.** `AsciiStringList` on `Animation.AnimationName`
means the line is a *list*: 916 corpus lines put more than one clip on it, which a scalar type
silently joins into one bogus name.

## What is left

42 fields still carry `Untyped` with an engine row behind them. They are all records with no
converter yet in `sage_ini`: nested sub-blocks (`Envelope` -> `OpacityEnvelope`, `Object`
`Prerequisites`, `UnitSpecificFX`, `FXList.CullingInfo`, `TransitionDamageFX.RubbleNeighbor`),
colon-keyed events (`FXEvent`, `LuaEvent`, `AutoResolveCombatChain.Target`,
`BuildingNugget.Bonus`), the mixed keyword streams (`Terrain.Class`, `LargeGroupAudio*.Key`), the
particle `Color` keyframes (`R:255 G:255 B:255 <frame>`), the `n : d` probabilities in
`DifficultyTuning`, and the eight-token `RiderChangeContain` rider records. A further 27 have no
engine row at all: either the block has no field table (the FXParticleSystem sub-blocks) or the
keyword is not in this build (see above) - those are schema entries to re-check, not fields to
type.

## The `Opaque` pass (2026-08-28)

`Untyped` was the *unreviewed* backlog; `Opaque` is the other one - "a named scalar kept as its
raw token", used wherever a field denotes an external entity the schema had no dedicated type
for. The same table walk types those too, and it scales: instead of asking `keyword <Name>` once
per field, scan every data section for `{name, parseFn, userData, offset}` runs in one pass, index
them by keyword, and pick a class's table by how many of that class's *other* keywords it carries.
427 `Opaque` fields, 492 tables, 4665 keywords, a few seconds.

What the engine settles, in descending order of how much it tells you:

| engine row | what it decides | example |
|---|---|---|
| `Enum` / `BitFlags` + `userData` | the whole member list, read straight out of the array | `Object.AutoResolveUnitType` -> the 10 `AutoResolveUnit_*` names at `0x00dadbe4` |
| a subsystem lookup (`EvaEvent`, `AudioEventRTS`, `ScienceType`, `ParticleSystem`) | the table the name resolves in | `Rank.SciencesGranted` -> `"Science name %s not known!"` |
| `AsciiStringList` vs `AsciiString` | **arity** - the highest-value bit, because a scalar annotation on a list field silently joins the tokens into one bogus name | `LoadSubsystem.InitFile` really takes several `.ini` paths; `Object.SubObjects = LWSTAFF LWBANNER` is two subobjects, not one |
| a numeric parser | that it is not a name at all | `GoodCommandPoints` calls `INI_PARSE_INT` twice into `offset` and `offset+4`: a `<start> <max>` pair, not a token |
| `AsciiString` | only that it is one token; the engine stores the raw string and resolves it later | the referent still has to come from the corpus |

That last row is most of the bucket (152 of 427), which is the honest limit of this method: for a
plain `AsciiString` the engine has no opinion about *what* the name names. Those were settled from
corpus values instead and then **checked by conversion**: a `Reference` that names the wrong table
reports every value as dangling, so the error census is the test. All 113 came back clean; the only
new diagnostics in the whole pass were four `reference-case` findings on `Region.RegionPortrait`,
which are real - `LWPBlacKGate`, `LWPRedHornPass`, `LWPBarrowDowns` and `LWPBrownlands` are spelled
one way where they are defined and another where they are used, and the engine matches
case-insensitively so the game never minded.

**Two parse functions worth naming.** `0x00641911` is two `INI_PARSE_INT` calls back to back (the
command-point pairs). `0x00642182` and its four siblings scan `MP1:`..`MP8:` - a colon-keyed record
of one multiplier per player count, which is why `MultiPlayMoneyMult` never fit a scalar.

**129 keywords have no row and no string in the image at all**, and no occurrence in either corpus:
57 `InGameUI.*RadiusCursor` fields, 19 `StrategicHUD.*`, 11 `MiscAudio.*`, and the rest scattered.
They are Generals/BFME2-era schema entries this build does not have - entries to re-check, not
fields to type.

**Watch the corpus underneath you.** The Edain root is a live mod tree; three diagnostics appeared
and disappeared mid-pass because its author was editing `evilmenumbarlord.ini` at the time. Diff
the in-repo `data` corpus when a census result needs to be trusted.
