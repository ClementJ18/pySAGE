# HeroHordeDeathPatch: register death before empty-horde destruction

`HeroHordeDeathPatch` (`hero-horde-death`) calls native death preparation on an eligible empty
hero horde immediately before the engine's existing destroy request. Its implementation is in
`sage_patch/patches/experimental/hero_horde_death.py`. The user reports that the death behavior
works as intended; the patch remains experimental because the wider recruitment and revival
workflow depends on the horde configuration and other engine behavior.

## Scope and configuration

The target horde object has `KindOf = HERO HORDE`, an explicit `ImmortalBody`, an XP/rank
tracker, and a `RespawnUpdate` with a matching `RespawnRules` entry using `AutoSpawn:No`.
A horde containing three different heroes additionally needs three corresponding
`InitialPayload` entries. These INI properties are prerequisites, not changes made by this patch.

After the engine removes the last member and decides that the horde is empty, the hook calls:

```cpp
void __thiscall RespawnUpdate::DeathPreparation(RespawnUpdate* this);
```

The call runs on the **horde object's** module. The native function handles death effects,
HeroDeath notification, the effectively-dead state, and creation of the player's HeroRecord.
The hook then restores the original instruction and continues the existing destroy request.
It does not use `RespawnBody`, `OBJECT_KILL`, artificial damage, altered horde HP, a fabricated
DamageInfo, or an additional `Object::OnDie` call.

**This patch concerns death registration only. It does not automatically fix recruitment,
revival placement, or the ability to leave a production building.** Current game tests show
that some hero hordes remain inside the producing building and are visible only in the hero
bar. A configuration workaround is to recruit/revive an **interface object** that transforms
into the intended hero battalion afterwards. That transformation belongs to the mod's object
configuration; it is not implemented by this death hook.

The existing empty-horde decision is the trigger. The hook does not recount member deaths or
check why the container became empty. Emptying an eligible horde through another mechanism can
therefore also register a death. The independent [`HordeHerobarPatch`](horde-herobar.md) changes
the health display, and `combo-horde-recruitment` handles mixed initial payload creation.
Neither changes the scope of this death hook.

## Reference binary and address interpretation

Use the identified RotWK reference executable below and preserve it unchanged.

| Property | Verified value |
|---|---|
| Size | 11,346,944 bytes |
| SHA-256 | `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26` |
| Format | PE32, i386 |
| Preferred ImageBase | `0x00400000` |
| COFF timestamp | `0x460DA09E`, 2007-03-30 23:43:26 UTC |
| Version resources | `2.1.2614.37001` and `1.00.65535.65535` |

The timestamp is not proof of a release date. Older repository notes spell the first version
`2.01.2614.37001`. Additional sections such as `stxt774`, `stxt371`, `.mackt…`, and `.danetta`
are already present in the reference, so this is an identified reference file rather than a
claim that it is an untouched publisher binary.

A **VA** is an address in the preferred image; **RVA = VA - ImageBase**. The file offset is
`Section.PointerToRawData + VA - SectionVA`. Raw offsets happen to equal RVAs in the original
sections below; newly appended sections need not have that property.

| Section | RVA | Raw offset | Virtual size |
|---|---:|---:|---:|
| `.text` | `0x1000` | `0x1000` | `0x7CF000` |
| `.rdata` | `0x7D0000` | `0x7D0000` | `0x1B9000` |
| `.data` | `0x989000` | `0x989000` | `0x81000` |

Exact bytes verify addresses and instruction boundaries; semantic function names come
from static reverse engineering and are not themselves runtime proof.

## Reverse-engineering path and hook layout

1. `0x0087370B` is the virtual member-removal routine. ECX on entry is the HordeInterface at
   Runtime+`0x11C`; after the prologue ESI retains it and EDI holds the removed member object.
   `[ESI-0x118]` is ModuleData and `[ESI-0x114]` is the owning horde object.
   `[EBP+8]` is overwritten at `0x00873784` and is not a reliable later member pointer.
2. After `0x00873821`, EBX is Runtime. Argument preparation starts at `0x00873835`; the actual
   call to `0x00865598` is at `0x0087383B`. The sentinel comparison at `0x00873845` and branches
   at `0x00873847` and `0x0087384D` retain the native empty-container decision. The existing
   side-effect call to `0x005DD9EE` at `0x00873867` also remains unchanged.
3. At **`0x0087386C`**, the six-byte instruction **`FF B6 EC FE FF FF`** is
   `push dword ptr [esi-0x114]`. The patch replaces exactly those bytes with `E9 rel32` plus
   `90`. The trampoline performs death preparation, replays the original PUSH, and jumps to
   **`0x00873872`**.
4. At the resume address the engine executes `mov ecx,[0x00DE412C]`, followed at
   **`0x00873878`** by `call 0x0062BBAB`, the original destroy request. The engine continues
   using the contain module afterwards, so the hook must not free the horde early.
5. The native call at `0x008C565D` passes only ECX to `0x008B3744`. DeathPreparation ends at
   `0x008B38A1` with `RET`, not `RET 4`: it takes no DamageInfo or other stack argument.
6. RespawnUpdate lookup follows the engine's NameKey/module APIs. With `[0x00DD90E4]` in ECX,
   push the string at `0x00C0B098` and call `0x005487EC` (`ret 4`). Then push the returned key,
   set ECX to the horde, and call `0x0068BDA5` (`ret 4`). No unverified numeric NameKey is used.
7. Native rule lookup calls `0x00603AF6` on ModuleData+`0x10C` with a pointer to the current
   rank from `[Object+0x26C]+0x24`, then tries rank 1 if necessary. A returned tree sentinel
   means no rule. Without a rule, native DeathPreparation only schedules an update and creates
   neither HeroDeath notification nor HeroRecord; the hook skips that path.

## Verified addresses and signatures

The confidence column distinguishes verified bytes/call sites from interpretations of the
native flow. RVAs and file offsets are in the machine-readable address reference.

| VA | Function or field | Evidence / confidence |
|---|---|---|
| `0x00C5B1F8`, slot `+0x34` at `0x00C5B22C` | HordeInterface member removal | Pointer bytes verified; semantic name from static RE |
| `0x00C5BECC`, `0x00C5CFDC` | Additional vtable references to `0x0087370B` | Pointer bytes verified |
| `0x008B3744` | DeathPreparation, thiscall, no stack arguments | Prologue, native call, and RET verified |
| `0x00C6C360` | RespawnUpdate primary runtime vtable | Constructor stores and repository analysis |
| `0x006A1CE2` | HeroDeath notification | Call inside DeathPreparation verified |
| `0x0068D950` | setEffectivelyDead, Object+`0x458` bit 0 | Read/write instructions and native call verified |
| `0x00781792` | PlayerHeroManager::addEntry(Object*, AutoSpawn) | Native call and static repository analysis |
| `0x0068B678`, Player+`0x758` | Controlling player and HeroManager | Native flow verified |
| `0x00780DD4` | HeroRecord constructor; record size `0xE8` | Existing static repository analysis |
| `0x007812F7` | Writer of HeroRecord+`0xB4` | `MOV [eax+B4],esi` verified against backup |
| `0x008A250A`, `0x0078142F` | ProductionUpdate calls reviveRecord(key, spawnInfo) | Call and `entry+0x10` key argument verified |
| `0x007814C2`, `0x006D165E` | Revive factory call and object creation | Call verified |
| `0x00781722`, `0x007813FF` | Remove revived HeroRecord | Existing static RE |
| `0x008A2C07`, `0x008B38A2` | ProductionUpdate activates new RespawnUpdate | Call verified; state 4 from static RE |
| `0x00871B9B`, `0x00871BAB`, `0x00871BB3` | onObjectCreated, separate payload hook, existing JNE | Independently verified by payload patch |
| `0x0065B165`, `0x00651186`, `0x00651212` | ImmortalBody registry, data factory, runtime factory | Static RE and reference bytes |
| `0x008C4A0A`, `0x008C3841` | ImmortalBody and base constructors | Disassembly checked against backup |
| `0x00C72090`, `0x00C71FE0` | ImmortalBody runtime and BodyInterface vtables | Constructor stores verified |
| `0x008C47DE`, `0x008C4AB4`, `0x008C31A5` | Rule-health setter, immortal clamp, base HP change | Vtable slots verified; semantics from static RE |
| `0x00850C32` | Update scheduler | Native no-rule path verified |
| `0x0044A573` | Independent native HERO-bit test | Frozen bytes; avoids HeroBar classifier hook |

Related analyses: [`cooldown-through-death.md`](cooldown-through-death.md),
[`hero-revive-ownership.md`](hero-revive-ownership.md), and
[`combo-horde-recruitment.md`](combo-horde-recruitment.md).

## Trampoline and guards

The patch appends a readable/executable **`.hhrdead`** section. `build_code(base_va)` generates
relative calls and branches for its allocated address; there is no fixed cave VA.

```text
PUSHFD / PUSHAD
save original stack base; reserve space; align ESP to 16 bytes; FXSAVE [ESP]
owner = [original ESI-0x114]
require owner, template, HERO and HORDE
require not effectively-dead, exact ImmortalBody interface, and XP tracker
require NameKeyGenerator and RespawnUpdate
require exact RespawnUpdate vtable and matching owner
require state 0 or 4, ModuleData, and rule-tree head
find current-rank rule, then rank-1 fallback; require AutoSpawn:No
ECX = RespawnUpdate; CALL DeathPreparation
FXRSTOR [ESP]; restore original stack; POPAD / POPFD
PUSH [ESI-0x114]
JMP 0x00873872
```

HERO is `[Template+0x113] & 4`, equivalent to `[Template+0x110] & 0x04000000`.
HORDE is `[Template+0x115] & 0x20`, equivalent to `[Template+0x114] & 0x00002000`.
Frozen native test signatures establish both bit positions. The exact ImmortalBody
BodyInterface vtable deliberately excludes other or derived bodies. The native rule lookup
is thiscall with a `rank*` stack argument and `ret 4`; the hook separately removes its four-byte
rank temporary. All guard failures continue the original destroy flow.

Native DeathPreparation sets the effectively-dead bit, which blocks a later duplicate call for
the same object. This is **not a complete reentrancy lock** during earlier death-animation or
FX callbacks that run before that bit is set. State 0/4 alone is not a once-only guard because
DeathPreparation does not change that state. The handler uses property and module guards,
not a hardcoded INI template name.

## Native revival, payload, and limits

The native production flow uses `PlayerHeroManager::reviveRecord` to create a **new** object,
restore XP/upgrades, and remove its HeroRecord. ProductionUpdate then calls `0x008B38A2` on
the new RespawnUpdate, which sets state 4, emits spawn/revive UI notifications, applies the
rule's health, and schedules the module.

The body health path is compatible with ImmortalBody: BodyInterface slot `+0x58` calls
`0x008C47DE`, converting rule health into a desired health delta. ImmortalBody's slot `+0x84`
then calls `0x008C4AB4`, which clamps negative deltas to leave at least 1 HP before delegating
to `0x008C31A5`. The death hook does not manipulate that process.

`combo-horde-recruitment` is independent. It replaces the producer read at `0x00871BAB` and
allows native `createPayload` for more than one InitialPayload entry. The original `JNE` at
`0x00871BB3` remains; there is no unconditional NOP of that branch. This separate patch affects
all hordes with multiple payload entries and does not guarantee production-building exit.
Verify the complete revived payload for each target configuration, including any interface
object used to transform into the final battalion.

HeroRecord+`0xB4` is initially zero; `0x007812F7` is a verified writer. ProductionUpdate reads
the runtime key from its queue `entry+0x10` and passes it to `0x0078142F`. This narrows the
queue/record investigation but does not prove every custom horde's production binding. Do not
replace the initial zero with an invented key.

Native death effects and effectively-dead handling may invoke other modules before the
following destroy request. Signature checks and emulation do not prove every such callback
safe. DeathPreparation uses the current controlling player; ownership changes have no special
handling here. Save, replay, and multiplayer compatibility require separate game tests.

## Patch compatibility

`HeroBarPatch` rewrites classification at `0x0092CD7F`. The death patch verifies HERO's bit
position using an independent native test at **`0x0044A573`**, with signature
**`F6 80 13 01 00 00 04 74 05 FF 45 C0 EB 03`**, so applying HeroBar first does not invalidate
its anchors. No unverified jump into another patch's cave is accepted as a signature.

The death hook (`0x0087386C`), health display hook (`0x0092D5EB`), HeroBar classifier, and
payload hook (`0x00871BAB`) do not overlap. Tests cover the relevant application permutations
with other hero-related patches. Static
coexistence establishes that the patches install and verify together; game behavior still
needs the relevant combined test.

## Safe build, verification, and removal

Run with Python 3.12 or newer, using a separate output:

```sh
python -m sage_patch apply hero-horde-death --in original.dat --out hero-horde.dat
python -m sage_patch verify hero-horde-death hero-horde.dat
```

To combine death registration, mixed payload creation and health display:

```python
from sage_patch import apply_patches
from sage_patch.patches.combo_horde_recruitment import ComboHordeRecruitmentPatch
from sage_patch.patches.experimental.hero_horde_death import HeroHordeDeathPatch
from sage_patch.patches.horde_herobar import HordeHerobarPatch

apply_patches(
    "original.dat",
    [HeroHordeDeathPatch(), ComboHordeRecruitmentPatch(), HordeHerobarPatch()],
    output="hero-horde.dat",
)
```

Keep the source unchanged. To remove a patch from a combination, rebuild from that
original input with the desired selection. The CLI can overwrite its input without
`--out`; always choose a separate output.

`HeroHordeDeathPatch.apply` stages changes on a copy and accepts
an existing installation only when hook and cave bytes exactly match. Modified anchors,
foreign hooks, and damaged caves are rejected. Updating an older cave requires a rebuild from
the reference input.

## Validation and game test plan

Automated tests use synthetic PE data, optional reference-binary checks via
`PYSAGE_ROTWK_GAME_DAT` with `--full`, and Unicorn
x86 emulation. Native calls are **ABI-conforming stubs**, not a running engine. Tests cover
guards, rank-1 fallback, AutoSpawn exclusion, replayed PUSH semantics, stack balance,
register/flag preservation, x87/SSE state, repeated death calls, idempotency, corrupted bytes,
and coexistence with health, payload, and HeroBar patches.

```sh
python -m pytest tests/sage_patch/test_hero_horde_death.py tests/sage_patch/test_horde_herobar.py tests/sage_patch/test_combo_horde_recruitment.py -q
```

For each target INI configuration:

1. Recruit or transform into the three-member hero horde; check different member templates,
   selection, hero-bar entry, and exit from the production building separately.
2. Lose the first and second members: there must be no horde HeroDeath/Record yet.
3. Lose the final member: expect one horde HeroDeath notification and the correct revive
   record, owner, cost, and time, with the original destruction completing safely.
4. Complete native revival and any interface-object transformation; inspect all three
   resulting member types, XP, upgrades, selection, and production-building exit.
5. Repeat a full death/revive cycle and check for duplicate records or members.
6. Compare ordinary hordes, single heroes, missing RespawnUpdate/rules, and AutoSpawn:Yes.
   Also test non-death emptying and custom death effects.
7. Validate the independent health display in the same configuration; success of death
   registration alone does not establish correct recruitment or UI behavior.
