# Extending PillageModule: findings and implementation plan

Historical research: the subsequent implementation uses `StealAmount`, not
`StealPercentage`. The current specification and confirmed RotWK hooks are in
[pillage-module.md](pillage-module.md).

As of October 14, 2026. Status: research and design; no executable patch,
no newly confirmed RotWK Pillage addresses, and no in-game test.

## Findings

The requested extension can be clearly scoped using the BFME2 implementation:

- `TriggeredBy`, `ConflictsWith`, `RequiresAllTriggers`, and
  `RequiresAllConflictingTriggers` as optional conditions evaluated dynamically.
- `StealPercentage` as a factor between 0 and 1, defaulting to `1.0`.
- The payout and the deduction from the opponent become separate amounts. With
  sufficient funds, `PillageAmount = 2`, `StealPercentage = 0.5` gives the owner +2
  and the victim -1; the floating cash display above the owner shows +2.

The recommendation is to check the conditions directly on each Pillage event,
following the existing pattern in `patches/large_group_bonus.py`. This does not
require extending the class hierarchy with an actual UpgradeMux.

## 1. Sources examined and evidence status

OpenBFME2 checkout: `6d4d83c87ad014774f11a3116c9d228dd0c9c29d`.
pySAGE checkout: `aadbc49726b27100a17d000049b4bb033eb52fea`.

Primary files in `F:/Modding/OpenBfme2/`:

- `Code/GameEngine/Source/GameLogic/Object/Behavior/PillageModuleRva00484FE2.cpp`
  contains the reconstructed event callback.
- `Code/GameEngine/Source/GameLogic/Object/PillageModuleDataCtor.cpp`
  contains the data constructor and INI table.
- `Code/GameEngine/Source/GameLogic/Object/PillageModuleFriendNew.cpp` and
  `Code/GameEngine/Source/GameLogic/Object/Update/UpdateModuleDataFriendNew.cpp`
  contain the two factory functions.
- `Code/GameEngine/Source/GameLogic/Object/Behavior/PillageModuleCtor.cpp` and
  `PillageModuleXfer.cpp` establish instance initialization and serialization.
- `Code/GameEngine/Source/GameLogic/Object/PillageModuleDataDtor.cpp`
  establishes how the ObjectFilter handle is released.
- `Code/GameEngine/Source/Common/RTS/MoneyRva003B0D7C.cpp`
  contains withdrawal and deposit, including statistics and audio side effects.
- `reverse/functions.csv` lists these functions as `matched`.

This is existing byte-match evidence from the repository; the byte verification
gate was not rerun for this research-only task. The callback's original name and
the meaning of its first argument explicitly remain unknown. The money operations,
field accesses, and control-flow order are visible in the reconstructed body
listed as matched.

## 2. What Pillage currently does

The factory registers `PillageModule` with interface mask `0x2000`.
Its own INI table contains only these three fields:

| Data offset | Field | Initialization / parser |
| --- | --- | --- |
| `+0x08` | `PillageAmount` | 0; unsigned integer |
| `+0x0C` | `NumDamageEventsPerPillage` | 0; unsigned integer |
| `+0x10` | `PillageFilter` | 4-byte ObjectFilter handle |

`sizeof(ModuleData)` is `0x14`; `sizeof(Module)` is `0x1C`.
The callback receives `this` pointing to the interface at module `+0x10`:
`[this-0x0C]` is ModuleData, and `[this-8]` is the owner object.
The event counter is at module `+0x18`, or callback-this `+8`.

The sequence is:

1. Return if there is no data or owner object.
2. Check `PillageFilter.accepts(victim, NULL)`; rejected victims do not count.
3. Increment the event counter. Return below the threshold; otherwise reset it to 0.
4. Determine the controlling players of the victim and owner.
5. Calculate `requested = min(PillageAmount, victim.balance)`.
6. Withdraw through the native money function; its return value is the amount
   actually deducted, `cash`. This function caps the amount at the balance again.
7. Return if `cash == 0`; otherwise deposit exactly `cash` through the native function.
8. Format `GUI:AddCash` with `cash` and display it above the owner.

Because the counter is incremented before comparison, a threshold of 0 effectively
triggers on every accepted event, as does a threshold of 1. The counter is reset
before the money operation even when the opponent's account is empty.

The callback itself does not check the enemy relationship or verify that the two
players are different. The existing filter and calling context determine this.
New relationship checks would be an additional change. The visible native path
does not guard against null players; the validity guarantees provided by the
RotWK caller must be investigated.

Note: `PillageFilter` is an ObjectFilter handle here. The generated pySAGE module
reference labels some such fields as `KindOfFilter`; that label alone is not a
reliable basis for the ABI.

## 3. Upgrade semantics and a suitable reference implementation

`large_group_bonus.py`, particularly `_emit_held` and `build_gate`, already adds
exactly the four required upgrade keywords without installing an UpgradeMux
interface. Its evaluation logic is the appropriate reference:

- Empty `TriggeredBy`: no activation requirement; active by default.
- Non-empty `TriggeredBy`: at least one upgrade is required; with
  `RequiresAllTriggers = Yes`, all upgrades are required.
- Empty `ConflictsWith`: no blocking condition.
- Non-empty `ConflictsWith`: one held upgrade blocks activation; with
  `RequiresAllConflictingTriggers = Yes`, all must be held together to block it.
- Both Boolean switches default to `No`.
- Conflicts take precedence over a satisfied activation condition.
- Object upgrades and completed upgrades of the controlling player are considered.
  After an ownership change, the current player is used.

The reference tests the object and player masks separately and combines the results
with OR. For ALL, a combination split between object and player is therefore
insufficient; a single mask must satisfy the entire list. This deliberately follows
the native UpgradeMux semantics documented there, rather than merging the two masks.
Explicitly document and test this in the new patch.

The gate should run before incrementing the counter. While disabled, there is
neither counter progress nor any money operation. Recommendation: preserve existing
partial progress. After reactivation, the next permitted event continues counting.
Resetting on deactivation would be an additional behavioral decision not currently
requested, and the transition would not be detected without an event during the
disabled period.

Evaluation takes place on each Pillage event; polling every frame is unnecessary.
Upgrade loss and conflict changes take effect by the next event, without a state
latch or dependency on `upgrade-module-removal`.

These four fields do not automatically support `Permanent`, `UpgradeTexture`,
`CustomAnimAndDuration`, or upgrade side effects. An actual UpgradeMux with those
features would be a larger, separate project. The four listed keywords are
sufficient for the reversible activation requested here.

## 4. StealPercentage: recommended precise definition

INI input uses a Real factor: `0.5` means 50%, and `1` means 100%.
Do not use a percentage parser without checking whether it divides by 100.
Values outside `[0, 1]`, as well as NaN/infinity, should produce an INI error.

Recommended first version, staying as close as possible to existing behavior:

```text
gain = min(PillageAmount, victim.balance)
loss = floor(gain * StealPercentage)
nativeWithdraw(victim, loss)
nativeDeposit(owner, gain)
showAddCash(owner, gain)
```

If `gain == 0`, do not deposit or display anything. If `loss == 0`, the deposit must
still be allowed: the existing early return on a withdrawal result of 0 must not
suppress it. The native withdrawal function can process 0 without side effects.

| PillageAmount | Factor | Victim balance before | Owner receives | Victim loses |
| --- | --- | --- | --- | --- |
| 2 | 1.0 | 10 | 2 | 2 |
| 2 | 0.5 | 10 | 2 | 1 |
| 2 | 0.0 | 10 | 2 | 0 |
| 3 | 0.5 | 10 | 3 | 1 |
| 2 | 0.5 | 1 | 1 | 0 |
| 2 | 0.5 | 0 | 0 | 0 |

**Product decisions still to be made:** The user's example defines neither
rounding nor behavior with insufficient funds. Rounding down and retaining the
existing payout cap are recommendations here, not requirements established by
the request. An alternative definition would always use `gain = PillageAmount`
and cap only the withdrawal at the available balance. This would still generate
income from an empty victim account; at factor 1, it would also change existing
behavior.

For a factor of exactly `1.0`, execute the existing money path as unchanged as
possible: deposit based on the actual withdrawal, with the same side effects.
This makes the default setting particularly easy to compare with the original.

The new path must continue using the native money functions. Direct writes to
balances would bypass statistics, audio, and other side effects. Victim statistics
receive `loss`; owner statistics receive `gain`.

Implement rounding down explicitly rather than depending accidentally on the
current x87 rounding mode. Check the unsigned input range, float precision, signed
deposit parameter, and extreme amounts separately. No fractional remainder latch
is planned for the first version; therefore, 1 * 0.5 produces a loss of 0 every time.

## 5. Proposed data layout

Under the assumption, still to be confirmed, that RotWK uses the same original
data layout and the 36-dword upgrade masks documented in pySAGE:

| Offset | New contents | Default |
| --- | --- | --- |
| `+0x14` | float `StealPercentage` | `1.0f` |
| `+0x18` | `TriggeredBy`, `0x90` bytes | empty |
| `+0xA8` | `ConflictsWith`, `0x90` bytes | empty |
| `+0x138` | `RequiresAllTriggers`, byte | 0 |
| `+0x139` | `RequiresAllConflictingTriggers`, byte | 0 |
| `+0x13A..13B` | Alignment | 0 |

Proposed data size: `0x13C` instead of `0x14` (+296 bytes per ModuleData).
Existing offsets remain unchanged. The module instance should stay at `0x1C`;
its vtables, event counter, and serialization are not extended.

Enlarge the factory allocation and initialize the new tail before INI parsing:
zero the masks/flags and set the factor to IEEE-754 `0x3F800000`. Investigate
constructor, copy, override, and all other allocation paths for completeness.
A simple factory extension is sufficient only once those paths are confirmed.
The masks and float require no additional destruction; preserve filter release.

## 6. BFME2 search anchors for subsequent RotWK research

**BFME2 addresses only.** `reverse/functions.csv` uses `target_rva`.
With ImageBase `0x00400000`, VA = RVA + ImageBase. Some source comments incorrectly
call an RVA a retail address; the table below normalizes those entries.
None of these Pillage addresses is confirmed as a RotWK patch address.

| Function / data | BFME2 RVA | BFME2 VA |
| --- | --- | --- |
| ModuleData constructor | `0x00253830` | `0x00653830` |
| buildFieldParse | `0x00253869` | `0x00653869` |
| ModuleData factory | `0x0025388A` | `0x0065388A` |
| Instance factory | `0x0024C77B` | `0x0064C77B` |
| Instance constructor | `0x00484F0D` | `0x00884F0D` |
| xfer | `0x00484FBB` | `0x00884FBB` |
| Event callback, 323 bytes | `0x00484FE2` | `0x00884FE2` |
| ModuleData destructor | `0x0025501B` | `0x0065501B` |
| INI field table | `0x007F0620` | `0x00BF0620` |
| Pillage interface vtable | `0x0084A514` | `0x00C4A514` |
| Primary module vtable | `0x0084A51C` | `0x00C4A51C` |
| Native money withdrawal function | `0x003B0CB3` | `0x007B0CB3` |
| Native money deposit function | `0x003B0D7C` | `0x007B0D7C` |

The data vtables are also recorded in `reverse/data_ledger.csv`.
The module's own field table is documented as a VA in `PillageModuleDataCtor.cpp`.

RotWK search and confirmation sequence:

1. Record the target build and hash of the unmodified `game.dat`.
2. Find the strings `PillageModule`, `PillageAmount`, `NumDamageEventsPerPillage`,
   and `PillageFilter`. Follow xrefs to the factory registration and field table.
3. Identify both factories; confirm actual allocation sizes and all constructor
   callers. Check field types/offsets directly against parsers and accesses.
4. Reconstruct instance vtables from constructor stores. Connect the interface
   to the event counter, filter, withdrawal, deposit, and `GUI:AddCash`.
5. Inspect callback callers: event type, object passed, first argument,
   this adjustment, enemy selection, null players, actual damage, and horde/contain
   behavior. The name `NumDamageEventsPerPillage` alone does not establish the event type.
6. Confirm withdrawal/deposit ABI, return values, statistics arguments, and audio flag.
7. Fingerprint already known RotWK mask parsers/tests and object/player offsets
   against the target build; they are prior knowledge, not a substitute for
   confirming Pillage itself.
8. Record exact hook windows, original bytes, resume addresses, register/flag
   liveness, and exception-handling boundaries. Do not blindly replace the
   callback based on similar-looking bytes.

## 7. Implementation in sage-patch

Proposed patch name: `pillage-module-extension`; class: `PillageModuleExtensionPatch`;
implementation: `sage_patch/patches/pillage_module_extension.py`.

1. Add confirmed RotWK facts centrally to `sage_patch/addresses/objects.py` or
   `runtime.py` and export them from `addresses/__init__.py`: table/xrefs,
   factory windows, callback hooks, layout, Money ABI, and fingerprints.
2. Allocate a private PE section, e.g. `.pillage`, for strings, the extended table,
   and stubs. Read the currently referenced table using `utils.field_tables`,
   preserve the three original fields, and append five new rows. Redirect all
   references; check each original offset and parser as a fingerprint.
3. Extend ModuleData allocation and defaults. This will likely require a factory
   detour and changes to table references; the exact number of write sites
   explicitly remains unknown until the RotWK analysis.
4. Add the gate to the callback before counting. Adapt `_emit_held` from
   LargeGroupBonus as an ABI/semantics reference; do not copy its assumptions
   about module-specific register assignments.
5. Redirect the money transfer at a confirmed window into a stub that keeps `gain`
   and `loss` separate. Factor 1 takes the original path. At factor <1, a loss of 0
   must not prevent the deposit. Continue using the original display with `gain`.
6. Stay within the existing callback where possible rather than rebuilding its
   entire C++ body: preserve UnicodeString, the stack frame, and exception cleanup.
7. Add `detect`, `apply`, `verify`, registry integration, and INI `FieldDelta`
   metadata following existing patch conventions. Reject unknown bytes, foreign
   hooks, or an incomplete installation of this patch before any mutation.
8. Add CLI/patch documentation. If a Worldbuilder version must read the same new
   INI fields, investigate and patch its parser/factory separately. Game addresses
   cannot be transferred to it.

## 8. Acceptance criteria and tests

- Compare defaults without new fields against the original: filter, thresholds
  0/1/N, counter reset, low/empty balance, amount 0, statistics, and display.
- All four upgrade fields: ANY/ALL, empty lists, conflict precedence, object and
  player upgrades, the split ALL case, grant/remove/regrant, and ownership changes.
- Check that blocking occurs before counting, including a partially filled counter
  on reactivation.
- Factors 0/0.5/1, odd amounts, losses below one resource, insufficient funds, and
  invalid or extreme values. Explicitly verify owner +2 / victim -1.
- Patch application and verification with synthetic fixtures: tail defaults,
  field parsers, table references, wrong build, tampered hooks, and repeated application.
- Check hook code in an emulator: stack, callee-saved registers, flags, this bias,
  x87/SSE state, and the original path. Test the real target binary as a corpus/full test.
- Save/load with a partial counter, plus replay/multiplayer with identically patched
  peers. Since no new instance state is planned, no additional Xfer state is proposed;
  nevertheless, check save compatibility against the actual RotWK Xfer implementation.
- Use an in-game test map with controlled balances and upgrade changes. Test
  horde/contain and damage events specifically once the calling path is confirmed.

The next step is to confirm RotWK addresses and ABI. Only then can the concrete
hook bytes be implemented and verified as a safely applicable patch.
