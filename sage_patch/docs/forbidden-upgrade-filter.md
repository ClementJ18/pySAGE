# `SpecialPower ForbiddenUpgrades` - the `forbidden-upgrades` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`). The engine reading
below is static; the patch's cave has been **executed under Unicorn** against stubbed engine
routines (`tests/sage_patch/test_forbidden_upgrades.py`) and applied and verified against a real
`game.dat`. **Runtime-verified in game**, 2026-09-22.

**What a mod writes.** One key on `SpecialPower`, inert when absent:

```ini
SpecialPower SpecialAbilityWordOfPower
    ...
    ForbiddenObjectRange = 150
    ForbiddenUpgrades    = Upgrade_AntiMagicWard Upgrade_Consecrated
End
```

A targeted cast is refused when **any** object within `ForbiddenObjectRange` of the cast point
carries one of the listed upgrades as an object upgrade. An object-targeted cast is also refused
when the target itself carries one.

**Why it was cheap.** The engine already has almost this exact check, the `NO_FORBIDDEN_OBJECTS`
radius scan: one call site, a stack `PartitionFilter` chain, one `ThePartitionManager` query. The
patch runs that same query with a filter of its own. The one expensive part is that
`SpecialPowerTemplate` has no room for a 144-byte mask, so the struct grows. That collides with
`hero-mana` and `special-power-charges`, which grow it too (§4).

## 1. What the engine does today

### The two cast predicates

Both are `__thiscall` on `TheActionManager`. Each is a chain of sub-validators, and any `false`
jumps to the shared refuse arm.

| VA | reading | args | ret |
|---|---|---|---|
| `0x0082DFB7` | `canDoSpecialPowerAtLocation` | `(Object* caster, Coord3D* where, cmdSource, SpecialPowerTemplate*, ?, cmdOptions, bool checkSource)` | `ret 0x1c` |
| `0x0082D925` | `canDoSpecialPowerAtObject` | `(Object* caster, Object* target, cmdSource, SpecialPowerTemplate*, cmdOptions, bool checkSource)` | `ret 0x18` (by frame layout) |

Callers: 5 for the location predicate and 9 for the object predicate. They span command-button
code (near `COMMAND_BUTTON_GET_TEXT_LABEL`), the AI group routines (`0x0076F774`, `0x0077097E`),
`0x006A4260` and two module routines (`0x00898C17`, `0x00899F9D`). **Gating inside the predicates
reaches the UI cursor, the AI and any module re-validation at once.** No caller needs its own
hook.

### The location chain, `0x0082E0BE`..`0x0082E12F`

```
0082e0be  call 0x82d56a            ; ?
0082e0d7  call 0x82d3a3            ; LIMIT_DISTANCE  - MaxCastRange (+0x74)
0082e0ec  call 0x82d2c9            ; bit 6 of Flags  - PATHABLE_ONLY
0082e0fe  call 0x82d415            ; RadiusCursorRadius (+0x54) sampling
0082e113  call 0x82dea6            ; ?
0082e128  call 0x82d2fd            ; NO_FORBIDDEN_OBJECTS  <- the one this patch mirrors
0082e12d  test al, al
0082e12f  je   0x82e23f            ; refuse
```

### The forbidden-object scan, `0x0082D2FD`

`(Object* caster, Coord3D* where, SpecialPowerTemplate* t)`, `ret 0xc`, returns `al = 1` when
the cast is allowed:

```
0082d30d  call getFinalOverride(t); test [eax+0x18] bit 4    ; Flags & NO_FORBIDDEN_OBJECTS
0082d31a  jne  .scan                                         ; else: allowed
0082d324  esi = caster->getControllingPlayer()
0082d333  eax = &final(t)->ForbiddenObjectFilter  (+0x78)    ; getter also at 0x0082CBC3
          ; stack PartitionFilter, vtable 0x00BE4CC8:
0082d33b  [ebp-0x28] = 0x00be4cc8   ; +0  vtable
0082d338  [ebp-0x24] = 0            ; +4  next (intrusive list link)
0082d342  [ebp-0x20] = &filter      ; +8  ObjectFilter*
0082d345  [ebp-0x1c] = player       ; +C  source player for relationship tokens
0082d348  [ebp-0x18] = 1            ; +10 accept when test() == this byte
          ; list head, vtable 0x00C10E20, next at +4:
0082d352  [ebp-0x14] = 0x00c10e20
0082d365  range = final(t)->ForbiddenObjectRange  (+0x7c)    ; getter also at 0x0082CBCC
0082d372  call 0xa394c0            ; head.append(&filter) -> eax = &head
0082d38a  call 0xa39090            ; ThePartitionManager(0xde4354)->find(where, range, 1, &head), ret 0x10
0082d38f  neg/sbb/inc              ; al = (found == NULL)
```

The filter's `allow` (vtable slot 1, `0x0066122D`) is `ObjectFilter::test(obj, player) == [this+0x10]`
(`0x0066123A` calls `OBJECT_FILTER_ALLOW`). Slots 0 (`0x00893738`) and 2 (`0x0048DACD`) are
copied as they are.

`Flags` names come from `0x00DA5F34`: `NEEDS_TARGET`, `WATER_OK`, `NEEDS_OBJECT_FILTER`,
`LIMIT_DISTANCE`, `NO_FORBIDDEN_OBJECTS` (bit 4), `RESPECT_RECHARGE_TIME_DISCOUNT`,
`PATHABLE_ONLY`.

### The object predicate has no forbidden check at all

`0x0082D2FD` has **one** caller (`0x0082E128`). `canDoSpecialPowerAtObject` applies the template's
`ObjectFilter` (`+0x60`) to the target (`0x0082D9A3`..`0x0082D9D1`) and never scans. So stock
`NO_FORBIDDEN_OBJECTS` does nothing for object-targeted casts, and "the targeted thing" is new
behaviour rather than an extension.

### Upgrade primitives, already named in `sage_patch.addresses`

| name | VA / offset | use |
|---|---|---|
| `INI_PARSE_UPGRADE_MASK` | `0x0066F603` | the row's parse function; `memset`s the mask on entry |
| `OBJECT_UPGRADE_MASK` | `Object+0x28C` | the object-scoped completed mask |
| `PLAYER_COMPLETED_UPGRADE_MASK` | `Player+0x14C` | the player-scoped one |
| `UPGRADE_MASK_TEST_ANY` | `0x008097D6` | `__thiscall(ecx = mask, [esp+4] = other) -> al`, `ret 4` |
| `UPGRADE_MASK_ANY` | `0x00444DCE` | `__thiscall(ecx = mask) -> al`, the "is the list empty" test |

`lifetime_fields.py` already parses an upgrade-mask keyword and tests an object against it with
exactly these.

## 2. Semantics

- **`ForbiddenUpgrades = <Upgrade> ...`** is parsed by `INI_PARSE_UPGRADE_MASK`, which clears the
  mask first, so an override line replaces the list. An empty mask turns the check off, and that
  is stock behaviour.
- **Radius** is the existing `ForbiddenObjectRange`. There is no new range keyword.
- **Every object in the area counts:** the caster, allies, enemies, neutrals. `ForbiddenObjectFilter`
  and `Flags = NO_FORBIDDEN_OBJECTS` are neither needed nor consulted. The stock check they drive
  still runs, first and unchanged.
- **Only object upgrades count** (`Object+0x28C`). The player's completed upgrades do not.
- **Location cast:** refused if an object within range of `where` carries a listed upgrade. With
  no range there is no area, so this key never refuses it.
- **Object cast:** refused if the target carries a listed upgrade, whatever the range. With a
  range, it is also refused when an object within range of the target's position carries one.
- The scan's head filter drops `DESTROYED` objects, exactly as the stock scan does.

## 3. The edits

All of them are in `sage_patch/patches/forbidden_upgrades.py`, in one cave section
named `.spforbu`.

1. **The keyword row.** The 24-row table at `SPECIAL_POWER_FIELD_TABLE` is rebuilt in the cave
   with one more row, `{ "ForbiddenUpgrades", INI_PARSE_UPGRADE_MASK, 0, 0x88 }`, and its two
   imm32 references are repointed. The live rows are read out of the image (`resolve_table`), so
   this composes with `special-power-music`.
2. **The struct grows `0x88` -> `0x118`** at the three `push 0x88` allocation sites.
3. **The constructor tail** (`0x007B200D`, `mov [esi+0x84], ebx`) jumps to a routine that replays
   the store and zeroes the mask with `ebx`, looping on `ecx`, which the next stock instruction
   overwrites.
4. **The copy-constructor tail** (`0x007B1F53`) jumps to a routine that copies the mask from
   `ebp` (the source) to `ebx`, looping on `ecx`/`eax`, then runs the displaced epilogue.
   `edi` has already been restored at that point.
5. **The location gate, `0x0082E128`.** `call 0x82d2fd` becomes a call to a routine with the same
   arguments and the same `ret 0xc`. It runs the stock scan with `ecx` untouched and returns its
   refusal unchanged. Otherwise it returns `!forbidden(NULL, where, t)`.
6. **The object gate, `0x0082DA69`.** `call 0x82c366` (`__thiscall`, 1 argument, `ret 4`; a true
   result refuses the cast) becomes a call to a routine that runs the original first. If the
   original returns true, so does the routine. Otherwise it returns `forbidden(target,
   &target->pos, t)`, reading `target` and `t` from the predicate's frame at `[ebp+0xc]` and
   `[ebp+0x14]`. Every early exit before `0x0082DA69` goes to the refuse arm, so every cast that
   can still succeed passes this call.

`forbidden(target, where, t)` (stdcall, `ret 0xc`) calls `getFinalOverride(t)`. It returns false
when the mask is empty (`UPGRADE_MASK_ANY`). If there is a target, it returns true when the target
carries a listed upgrade (`UPGRADE_MASK_TEST_ANY`). If the range is above 0, it builds
`{not-destroyed head -> cave filter}` on its stack and returns
`PARTITION_GET_CLOSEST_OBJECT(where, range, 1, &head) != NULL`. The cave filter's vtable is
`{0x00893738, allow, 0x0048DACD}`, sharing the stock outer slots, and its `allow(obj)` is
`testForAny(obj+0x28C, mask)`.

## 4. Composition

- **Conflicts with `hero-mana` and `special-power-charges`.** Both grow `SpecialPowerTemplate` from
  the same `0x88`, and `special-power-charges` also hooks the same constructor and copy tails.
  Each refuses the other on the table and the allocation sites before writing a byte. Lifting the
  conflict needs a shared "template tail" helper that appends to whatever `sizeof` the allocation
  sites currently push.
- **Composes with** `special-power-music` (through `resolve_table`), `cooldown-through-death` and
  `trigger-recharge-list`.
- **Determinism:** the check reads logic state only (partition, object masks), so it cannot
  desync. Every peer still has to run the same binary. Like the stock `NO_FORBIDDEN_OBJECTS` scan,
  it sees through the fog.

## 5. Still open

1. **Load order.** `parseUpgradeMask` resolves names when the block is parsed. If `SpecialPower`
   blocks are parsed before the listed upgrades are defined, every name is an unknown upgrade and
   the INI load fails. No stock `SpecialPower` names an upgrade, so there is no precedent. Load
   one block to find out. If it fails, the fallback is storing the names as a string
   (`utils.token_lists.build_list_parser`) and resolving them on first use.
2. **Garrisoned and contained objects.** Whether `getClosestObject` sees an object inside a
   building or a horde depends on whether contained objects stay in the partition. The stock scan
   has the same answer, whatever it is.

## 6. Runtime checklist

- A location spell's cursor turns invalid over a unit that carries a listed object upgrade, and
  valid again once the upgrade is removed.
- The caster carrying a listed upgrade blocks its own location casts within range.
- An object-targeted spell is refused on a carrier; with a range set, it is refused on a neighbour
  of a carrier.
- An override block that does not name the key keeps the base template's list (copy-tail hook).
- The AI does not cast into a forbidden area.
- Check what happens when the target *gains* the upgrade mid-approach. That depends on whether the
  module callers (`0x00898C17`, `0x00899F9D`) re-validate. Stock `NO_FORBIDDEN_OBJECTS` behaves
  the same way.
- `hero-mana` or `special-power-charges` refuse to apply on top of it, and it refuses on top of
  them.
