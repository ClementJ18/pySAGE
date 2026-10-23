# `AI_SPECIAL_POWER_ALLY_OBJECT` and `AI_SPECIAL_POWER_ALLY_STRUCTURE`: AI hooks that cast at own objects

The reverse engineering behind [`patches/ai_ally_targets.py`](../patches/ai_ally_targets.py).
ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, and the RotWK `Worldbuilder.exe`.
Read statically on 2026-10-21 (the unit type) and 2026-10-22 (the structure type).

## TL;DR

- No stock `SpecialPowerAIType` aims at an allied object. The one at-object family
  (`ENEMY_TYPE_KILLER` and its variants) searches for enemies with relationship mask `4`, which is
  hard-coded in the shared picker (`0x009EC0EC`). Its first test is "is the caster attacking"
  (`0x009930A3`), which reads the caster's AI module without a NULL check, so it can't even run
  on a building.
- The stock building types don't help an object power either. `AI_SPELLBOOK_BUFFECONOMYBUILDING`
  walks the player's economy buildings but checks and casts at each one's **position**, and an
  object-target power (`NEED_TARGET_ALLY_OBJECT`) fails that point check every time (§5).
- The patch adds two names after the 53 stock ones. Each behaviour is an enemy-killer behaviour
  with a new picker in vtable slot 7:

  | | `AI_SPECIAL_POWER_ALLY_OBJECT` (53) | `AI_SPECIAL_POWER_ALLY_STRUCTURE` (54) |
  |---|---|---|
  | **who** | the AI player's own units, from `TheSkirmishAIManager`'s per-player unit list | the player's own buildings: the record's structure list, then its economy list |
  | **when** | the unit is fighting (its AI has a current victim) | always; no fight needed |
  | **whether** | `CommandButton::isValidToUseOn(caster, unit)`: relationship, `ObjectFilter`, `MaxCastRange` | the same |
  | **which** | a `HERO` first, then the lowest health ratio | the first one accepted, in list order |

- `SpecialPowerRange` and `SpecialPowerRadius` are not read.
- Three edits: the parser's table read and loop bound, and the factory's out-of-range branch. None
  touches bytes another patch writes or anchors.
- `ai-ally-targets-wb` adds both names to Worldbuilder, which otherwise stops on an assert box.
- The patch was called `ai-ally-object` until 2026-10-22, when the structure type joined it.

## 1. The names and the parser

The `SpecialPowerAIType` parser (`0x00992693`) compares the token against `0x00DB84F8[i]` for
`i < 0x35`. The table has no other live reader: `0x00992654` reads it too, but that is a
name-to-index helper with no callers.

```asm
009926ca  push dword [esi*4 + 0xdb84f8]   ; <- disp32 repointed to the cave's copy
...
009926f6  inc  esi
009926f7  cmp  esi, 0x35                  ; <- imm8 raised to 0x37
009926fa  jl   0x9926ca
...
00992702  mov  eax, [ebp+0x10]            ; the field
00992705  mov  ecx, [ebp-0x14]            ; the index, -1 when nothing matched
0099270c  mov  [eax], ecx
```

The copy keeps every stock pointer in place, so stock names keep their indices. The stock table
itself is left alone: `ai-rebuild-gate` anchors its slot 31.

An unpatched `game.dat` stores -1 for either name. The factory's `ja` (unsigned) sends that to
"no behaviour", and the bind leaves the hook inert, so data written for the patch is harmless
without it.

## 2. The factory

`0x00992724`, `cdecl(index)`, builds the type's behaviour. It is called from the bind
(`0x008B72C6`) with the module data's `+0xC`:

```asm
0099272e  mov  eax, [ebp+8]
00992731  push esi
00992732  push 0x34
00992734  pop  esi
00992735  cmp  eax, esi
00992737  ja   0x992eef                   ; <- rel32 sent to the cave's case
0099273d  jmp  dword [eax*4 + 0x992efe]
...
00992eef  xor  eax, eax                   ; no behaviour
00992ef1  mov  ecx, [ebp-0xc]             ; every case lands here with eax = its behaviour
00992ef4  pop  esi
00992ef5  mov  fs:[0], ecx
00992efc  leave
00992efd  ret
```

The first ten bytes are `SPELLBOOK_AI_TYPE_FACTORY_ENTRY`, which `ai-rebuild-gate` anchors, so
the bound (`push 0x34`) and the jump table stay stock. Only the branch's rel32, the four bytes
past the anchor, changes. The case picks the vtable by index, 53 or 54. Anything else goes to
`0x00992EEF`, the stock path:

```asm
mov  edx, object_vtable
cmp  eax, 53 / je build
mov  edx, structure_vtable
cmp  eax, 54 / jne none
build:
push edx                  ; the vtable, across both calls
push 0x40                 ; the enemy-killer behaviour's size
call OPERATOR_NEW
pop  ecx / pop edx
test eax, eax / je none
push edx
mov  ecx, eax
call 0x009ec042           ; the enemy-killer constructor; returns this
pop  edx
mov  [eax], edx           ; the new vtable
jmp  0x00992ef1
```

The stock cases also write an exception state to `[ebp-4]` around the constructor. The new case
leaves it at the prologue's -1, so an exception inside the constructor would leak the 0x40 bytes
instead of freeing them. The constructor (`0x009EC042`) calls the shared spellbook constructor and
a KindOf clear, and neither throws.

## 3. The behaviour

The enemy-killer constructor stamps `0x00C8E734` and clears a KindOf mask at `+0x24`:

| slot | stock | used by the new types |
|---|---|---|
| 0 | `0x009EC06E` destructor | as is |
| 1 | `0x00993019` housekeeping | as is |
| 2 | `0x009E93C8` | as is |
| 3 | `0x00993024` the wake interval (`5 *` the logic rate) | as is |
| 4, 5 | trivial | as is |
| 6 | `0x00A02806` cast at `[+0x20]`'s object | as is |
| 7 | `0x009EC0A7` the enemy picker | **the type's picker** |
| 8, 9 | the enemy picker's KindOf and per-candidate hooks | unused |

The cave holds two copies of all ten slots, each with its own slot 7. Nothing between the tick and
the cast reads the caster's AI module. The tick (`0x008B73B7`) runs the coin flip and the picker
(`0x00993055`), then a per-player throttle (`0x00993276` / `0x00993307`), then slot 6
(`0x0099302D`). The at-object cast for a `SPECIAL_POWER` button (`0x00697890` →
`0x0069794F` → `0x0068E67A`) doesn't need one either. So both types work on a building, which is
where Edain's Might of the Witch-king lives, and on a unit without a weapon, such as the Dorwinion
Emissary.

## 4. The record's lists

`0x006A9999`, `__thiscall` on `TheSkirmishAIManager` with the `Player *`, looks the player's index
(`[player+0x54]`) up in the manager's map at `+0xA3C` and returns the record, or NULL for a player
the manager does not run. The record holds three lists, each an object whose `+4` / `+8` bound a
`std::vector<ObjectID>` (`0x0072B229`, the accessor the stock walks call, is `lea eax, [ecx+4]`):

| record | list | stock reader | admission test |
|---|---|---|---|
| `+0` | units | `AI_SPELLBOOK_ASSIST_BATTLE_*` (`0x00A02421`) | `0x0099E4C9`, below |
| `+8` | structures | `AI_SPELLBOOK_REBUILD` (`mov ecx, [eax+8]` at `0x009E775F`) | `0x0099E8C8`: `STRUCTURE`, not `ECONOMY_STRUCTURE`, not `LINKED_TO_FLAG`, not `BASE_SITE` ([`ai-rebuild-gate.md`](ai-rebuild-gate.md)) |
| `+0xC` | economy buildings | `AI_SPELLBOOK_BUFFECONOMYBUILDING` (`mov ecx, [eax+0xC]` at `0x009E7691`) | not traced; Edain's `ECONOMY_STRUCTURE` mine shafts are candidates there |

The unit walk, for comparison:

```asm
00a02421  mov  ecx, [0xde4938]            ; TheSkirmishAIManager
00a0242a  push dword [ebp+8]              ; the player
00a0242d  call 0x6a9999
00a02432  mov  ecx, [eax]                 ; the unit list
00a02434  call 0x72b229                   ; lea eax, [ecx+4]
00a02439  mov  ebx, [eax]                 ; begin
00a0243b  mov  eax, [eax+4]               ; end
```

**What joins the unit list.** `Object::setTeam` tells the manager twice: before the change
(`0x00697CA3` → `0x006A99CB`, removal from the old player's record) and after it (`0x00697CBC` →
`0x006A9D9C`, `0x008E4591`, admission to the new player's). Map placements are given their team at
load, so they join as recruits do. The unit list's admission test is `0x0099E4C9`:

| test | KindOf | effect |
|---|---|---|
| `test byte [tmpl+0x10E], 0x40` | `UNATTACKABLE` | rejected |
| `test dl, 0x84` on `[tmpl+0x108]` | `STRUCTURE`, `IMMOBILE` | rejected |
| `test byte [tmpl+0x11F], 0x80` | index 191 | rejected |
| `test dl, 8` | `CAN_ATTACK` | **admitted** |
| `test [tmpl+0x110], 0x4000000` | `HERO` | **admitted** |
| `test [tmpl+0x120], 0x4000000` | index 218 | admitted |
| `test dh, 0x40` + `0x0088B897` | index 14 | admitted unless the call says no |

So every mobile `CAN_ATTACK` unit and every hero, owned by that player. Not its allies': neither
type ever targets another player's object, even one whose `ObjectFilter` would accept it.

## 5. Why `AI_SPELLBOOK_BUFFECONOMYBUILDING` can't cast an object power

Its picker (`0x009E7671`, slot 7 of vtable `0x00C8DEC4`, built by factory case 32 at
`0x00992D76`):

```asm
009e7691  mov  ecx, [eax+0xc]             ; the record's economy list
009e7694  call 0x72b229
009e769f  push dword [esi]                ; each id
009e76a7  call 0x449681                   ; findObjectByID
009e76b2  mov  eax, [ebx+0x74]            ; its ObjectID
009e76c2  call 0x6b4e57                   ; look it up in the set at behaviour +0x2C
009e76cd  cmp  eax, [ecx] / jne next      ; already cast on: skip
009e76d4  add  ebx, 0x38                  ; &Object::m_position
009e76dd  call 0xa0229f                   ; the point check, then store the point
009e76e2  test al, al / jne take
...
009e7702  call 0x472958                   ; take: add its id to the set
```

So it casts at each economy building **once** (the set at `+0x2C`), and at its position, through
the point check `0x00A0229F` (`isValidToUseOn` with a position and no object). A button whose
power needs a target object fails that check, so the hook never fires. Seen live on 2026-10-22
with Edain's Establish Vineyard (`NEED_TARGET_ALLY_OBJECT`): a Brutal AI's Emissary, power ready
from frame ~460 and own mine shafts on the map, never cast.

## 6. The pickers

Both are `__thiscall(Object *caster)` on the behaviour, `ret 4`, `al` = cast now, target id at
`+0x20`.

### `AI_SPECIAL_POWER_ALLY_OBJECT`

1. Clear the target (`0x00A027D5` with NULL).
2. Caster's player → the record → the unit list. Any NULL on the way means no cast.
3. For each id: `findObjectByID`. Skip a missing object and the caster itself.
4. Skip a unit with no AI module, or whose current victim (`0x00668303`) is NULL.
5. Rank 2 for `HERO`, 1 otherwise. A rank below the best so far is skipped before anything else
   is asked of it.
6. Read the health ratio (body vtable `+0x14`). At equal rank, keep it only if it is lower.
7. Ask `CommandButton::isValidToUseOn(caster, unit, NULL, 0)` (`0x0075CF21`, `ret 0x10`). For a
   button needing a target object this is `canDoSpecialPowerAtObject` (`0x0082D925`): the
   relationship, the `ObjectFilter`, `MaxCastRange`.
8. If it passes, the unit becomes the best.
9. At the end, set the target to the best (`0x00A027D5`) and answer 1, or answer 0.

`esi`, `edi`, `ebx` and `ebp` hold the behaviour, the iterator, the best unit and the list end
across the engine calls, which preserve them. The x87 stack is empty at every call: the ratio is
stored to a local before `isValidToUseOn` runs, and popped on a reject.

### `AI_SPECIAL_POWER_ALLY_STRUCTURE`

1. Clear the target.
2. Caster's player → the record. Any NULL on the way means no cast.
3. For the structure list (`+8`), then the economy list (`+0xC`), skipping a NULL list: for each
   id, `findObjectByID`; skip a missing object and the caster itself.
4. Ask `isValidToUseOn(caster, building, NULL, 0)`. The first that passes becomes the target, and
   the answer is 1.
5. If none passes, answer 0.

`esi` holds the behaviour, `ebx` the record and `edi` the iterator; the list's end, the record
offset being walked and the candidate sit in three locals. Nothing is remembered between ticks.
Unlike the economy type, the same building can be picked again on the next cast, so the power's
`ObjectFilter` has to exclude a building it has already changed. Establish Vineyard's does this
naturally, since the building it converts is replaced by a vineyard the filter doesn't list.

The coin flip in front of either picker draws from the logic RNG and the walks are in list order,
so the choice is the same on every peer.

## 7. Worldbuilder

The editor's copy of the table (`0x02247A20`) holds **51** names, two fewer than the game's, ending
at `AI_SPECIAL_POWER_RANGED_AOE_ATTACK_UNITS`. It is read by a name-to-index helper (`0x014A6090`,
called from the field parser at `0x014A6057`):

```asm
014a60ce  cmp  dword [ebp-0x14], 0x33     ; <- imm8 raised to 0x35
014a60d2  jge  0x14a6158
014a60db  mov  edx, [ecx*4 + 0x2247a20]   ; <- disp32 repointed
...
014a6158  cmp  dword [ebp-0x10], -1       ; not found -> DEBUG_CRASH box
```

`ai-ally-targets-wb` appends both names to a copy. The editor runs no AI, so the indices the names
get there (51 and 52) don't matter.

## 8. Using them

```ini
Behavior = AISpecialPowerUpdate ModuleTag_MachtAI
    CommandButtonName  = Command_SpecialAbilityMachtdesHexenkonigsSanctum
    SpecialPowerAIType = AI_SPECIAL_POWER_ALLY_OBJECT
End

Behavior = AISpecialPowerUpdate ModuleTag_EstablishVineyardAI
    CommandButtonName  = Command_DorwinionEmissaryEstablishVineyard_Disabled
    SpecialPowerAIType = AI_SPECIAL_POWER_ALLY_STRUCTURE
End
```

The usual hook rules still apply ([`ai-power-model-condition.md`](ai-power-model-condition.md) and
the `ai-special-powers` doc in pySAGE-edain):

- the button must be in the object's **starting** command set, since the bind looks once;
- the AI ignores `NEED_UPGRADE`, so gate an upgrade-locked power with `StartsPaused = Yes` and an
  `UnpauseSpecialPowerUpgrade`;
- the power's `ObjectFilter` is the whole targeting rule. With `ALLIES` and a list of heroes, as
  on Might of the Witch-king, only those heroes are ever picked; with a list of building
  templates and `SAME_PLAYER`, as on Establish Vineyard, only those buildings.

## 9. Status

The unit tests apply both patches to stand-ins carrying the stock bytes, and run the factory case
and both pickers under Unicorn against stubbed engine calls
(`tests/sage_patch/test_ai_ally_targets.py`).

- `AI_SPECIAL_POWER_ALLY_OBJECT`: **runtime verified.** Edain's engine test
  (`tests/test_ai_might_of_the_witch_king.py` in the mod repo) gives a Brutal Angmar AI a keep
  with the Sanctum and two heroes, sends a Dwarven wave at the heroes whenever the power is ready,
  and counts the casts off the keep's power clock. On 2026-10-21 the AI cast twice, at frames 1536
  and 2837, each restarting the full 240 s reload.
- `AI_SPECIAL_POWER_ALLY_STRUCTURE`: **runtime verified** on 2026-10-22. Edain's
  `tests/test_ai_dorwinion_emissary.py` gives a Brutal Dwarves AI a Dorwinion outpost with the
  Vinedresser's Union, one lumbermill (structure list) and one `DwarvenMineShaft_Extern`
  (economy list). Its Emissary's Establish Vineyard hook cast at frame ~476, nine frames after the
  power came ready, and converted the lumbermill; it cast again at frame ~879, after the influence
  reset, and converted the mine shaft. The stock `AI_SPELLBOOK_BUFFECONOMYBUILDING` never cast in
  the same scenario (§5).

## 10. Open questions

- Only the player's own objects are candidates. Reaching an allied player's heroes or buildings
  would need a walk over each allied record, if a mod wants it.
- What admits a building to the economy list (`+0xC`) has not been traced.
- The structure type takes the first building accepted, in list order. A power that should spread
  over several buildings would need a rotation or a memory like the economy type's set.
