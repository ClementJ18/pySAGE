# New `DamageSubType` members

How the `damage-subtypes` / `damage-subtypes-wb` patches add subtypes, against ROTWK `game.dat`
`2.01.2614.37001` (ImageBase `0x400000`) and the RotWK `Worldbuilder.exe`. Read statically with
`pefile` + `capstone`; the live observations are from Edain's Brood Nest engine test.

## Why

A damage nugget's `DamageSubType` tags the victim; every object can carry a
`DamageFilteredCreateObjectDie` that runs an OCL when it dies tagged. Edain's Morgul Blade wraiths
are built on it (`BECOME_UNDEAD`, `BECOME_UNDEAD_ONCE`, inherited from `default/object.ini`). The
Brood Nest's Web Dominion wants the same mechanism ("an enemy that dies on webbed ground leaves a
cocoon"), but the engine has only four subtypes and none is free:

| index | name | already means |
|---|---|---|
| 0 | `NORMAL` | every untagged hit |
| 1 | `BECOME_UNDEAD` | Morgul Blade wraith |
| 2 | `SELF` | **set by the engine on self and lifetime kills** - seen live: ten hatching `KankrasBrutSummonEgg`s each left a cocoon when the web module listened for `SELF` |
| 3 | `BECOME_UNDEAD_ONCE` | lesser wraith, with a hard-coded throttle (below) |

## 1. The name table: 12 copies, two read

The names live in a NULL-terminated `const char *[]` resolved by `INI::scanIndexList` through the
index-list parser `0x0042E956`, which walks to the NULL with no length constant (as for the weather
table in [desert-weather.md](desert-weather.md)). The header that declares it is compiled into
twelve units, so the binary has twelve identical copies (`0x00D9DA7C`, `0x00DA161C`, `0x00DA39D4`,
`0x00DA521C`, `0x00DAF5CC`, `0x00DAF6F4`, `0x00DAFA5C`, `0x00DB2604`, `0x00DB26CC`, `0x00DB2844`,
`0x00DB5D9C`, `0x00DB63C4`). Only three field descriptors point at one, and no code references any:

| descriptor (userData slot) | field | table |
|---|---|---|
| `0x00C7B088` | `DamageNugget` `DamageSubType`, nugget `+0x184` | `0x00DB5D9C` |
| `0x00C613F0` | `DamageFilteredCreateObjectDie` `DamageTypeTriggersInstantly`, data `+0x3C` | `0x00DAF5CC` |
| `0x00C61400` | `DamageFilteredCreateObjectDie` `DamageTypeTriggersForDuration`, data `+0x40` | `0x00DAF5CC` |

The tables cannot grow in place (`0x00DAF5DC` is the next table's `NONE`).

**Worldbuilder** has the same arrangement, twelve copies of its own (strings at `0x01E6765C`,
`0x01E6AAF0`, `0x01E6AAE8`, `0x01E6AAD4`), read through three slots:

| userData slot | field | table |
|---|---|---|
| `0x01F1D768` | `DamageNugget` `DamageSubType` (`+0x184`) | `0x02236B8C` |
| `0x01F3B500` | `DamageTypeTriggersInstantly` (`+0x3C`) | `0x02239784` |
| `0x01F3B510` | `DamageTypeTriggersForDuration` (`+0x40`) | `0x02239784` |

The editor loads the same objects and weapons, so an unknown token there ends its load too.

## 2. Runtime: `DamageFilteredCreateObjectDie`

Vtables `0x00C6134C` (module), `0x00C61290`, `0x00C61288` (die), `0x00C6127C` (damage). The value is
`DamageInfo+0x18`, copied from the nugget's `+0x184` at `0x0090E638` (layout in
[healing-damage-nuggets.md](healing-damage-nuggets.md)).

| what | where | subtype use |
|---|---|---|
| data constructor | `0x008891DD` | **both trigger fields default to `4`** (`push 4; pop eax; mov [esi+0x3C],eax; mov [esi+0x40],eax`): one past the last name, i.e. "no trigger" |
| `onDamage` | `0x0088939A` | `DamageInfo.subtype == data+0x40` → stamp the frame and remember the source's controlling player |
| `onDie` | `0x008892B0` | `== data+0x3C` → OCL `data+0x38` with the killer as primary object, at the dying object's position; else a stamp younger than `data+0x44` → the same OCL with the remembered player |
| source check | `0x00889141` | **`subtype == 3`** (`BECOME_UNDEAD_ONCE`) refuses when the source fired one within 5 frames (`source+0x450`) |

So:

- **The sentinel `4` would collide with a fifth name.** A name at index 4 would make every module
  that leaves a trigger unset fire on that subtype. The patch keeps slot 4 occupied by
  `"(no trigger)"` - a string with a space in it, which no whitespace-split INI token can equal -
  and starts the new names at 5. Nothing else in the module moves.
- `3` keeps its throttle; new indices get none, which is what a cocoon wants.
- The OCL's owner comes from the tagger, not the victim (seen live: the cocoon belonged to the
  web's player), so a mod effect can pay its own side.

## 3. Other readers of the subtype

Only the module above is known to branch on it. A byte-pattern sweep of `.text` for any
`[reg+0x18]` compared against `1`..`5` and followed by a range jump (`jl`/`jge`/`ja`/...) - the
shape an array bound or a "known subtype" test would have - found nine sites, none of them on a
`DamageInfo`: four are edge-scroll screen bounds (`0x008390AD`, `0x0083AF85`), one takes module data
from `0x008A7160` / `0x008C65FD` (`0x0081C259`), and the rest compare stack arguments or CRT state.
Equality tests elsewhere against `1`/`2`/`3` would treat a new value as "not that subtype", which
is `NORMAL`'s behaviour. This is static and pattern-based: a reader that copies the field into a
register first and indexes later would not match it.

The subtype travels inside `DamageInfo` as an `int`, so save/load and network layout are
unchanged; every peer still needs the same binary, as with any logic-side `.sagepatch` change.

Not traced: where the engine writes `SELF` (2). It decides which deaths a `SELF` listener catches,
and is not needed for the patch.

## 4. The patch

`damage-subtypes` (`sage_patch/patches/damage_subtypes.py`) builds one table in a `.dmgsub` cave -
the four stock string pointers copied through by pointer, the reserved slot, the new names, NULL,
then the strings - and repoints the three `userData` slots at it. Option `names` (CLI `--names`,
comma-separated; default `CUSTOM_1`..`CUSTOM_8`) picks the names, indices 5 upward in order.
`damage-subtypes-wb` does the same to `Worldbuilder.exe` in `.wbdmgsb`; both must get the same list
in the same order, since parsed data stores the resolved index.

The patch declares each name as an `EnumDelta` on `DamageSubType` at its fixed index, so lint
accepts them only on a binary that carries it.

Engine test to write: tag a unit with a new subtype, kill it, check the OCL object appears - and
that a lifetime death (a hatching egg) does **not** trigger it.

## Related

[desert-weather.md](desert-weather.md) (relocating a name table),
[healing-damage-nuggets.md](healing-damage-nuggets.md) (`DamageInfo` layout),
pySAGE-edain `docs/` (the Brood Nest's Web Dominion).
