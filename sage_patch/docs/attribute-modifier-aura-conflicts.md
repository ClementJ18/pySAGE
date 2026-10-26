# AttributeModifierAuraUpdate conflicts

`attribute-modifier-aura-conflicts` fixes an active aura ignoring a newly satisfied
`ConflictsWith`. It uses the existing INI fields; no new tokens or defaults are added.

```ini
Behavior = AttributeModifierAuraUpdate ModuleTag_Aura
  TriggeredBy = Upgrade_A
  ConflictsWith = Upgrade_B Upgrade_C
  RequiresAllTriggers = Yes
  RequiresAllConflictingTriggers = No
  ; Keep the aura's other fields here.
End
```

With `RequiresAllConflictingTriggers = No`, either B or C disables an active aura.
With `Yes`, both must be held. An empty conflict list never disables it. The active
arm does not re-evaluate `TriggeredBy` or `RequiresAllTriggers`. Inactive calls go
unchanged to the stock added callback, preserving activation and its return value.

## Implementation and evidence

For RotWK 2.01.2614.37001, the four-byte UpgradeInterface vtable slot at
`0x00C67554` is replaced, from `0x008D26BF` to the executable, read-only `.aurconf`
section. A second detour at `0x0069375B` replaces ten bytes of the object upgrade
dispatcher. It retains the virtual flag getter and the inactive path. For active
modules it compares the actual interface vtable with `0x00C67550`: only this aura
may continue at `0x00693765` to build the combined held mask and invoke slot +04.
Other active types still skip to `0x006937AB`; the +18 callback remains stock.

`apply` validates the original pointer, entire dispatcher and helper fingerprints
before allocating. `verify` checks both hooks, the full cave and preserved anchors.
The shared evaluator `0x008D26F3` is never rewritten. The dispatcher remains in
charge of combining PLAYER upgrades, OBJECT upgrades and any related object's
upgrades; the patch does not reconstruct this context or change source counting.

### Why a slot-only rewrite is insufficient

`Object` dispatch at `0x006936FE` calls the flag getter at `0x0069375F`, tests AL,
and branches at `0x00693763` over both mask construction and the +04 callback if
already active. Consequently, a wrapper installed only at `0x00C67554` never sees
the relevant active-module event. A successful byte-level verification of that
slot-only version did not establish the required runtime behavior.

This was reproduced for the Beorn `ModuleTag_EinsiedlerPassiv` configuration:
`StartsActive = No`, `TriggeredBy = Upgrade_Level_1`, `ConflictsWith = Upgrade_Level_7`,
`Permanent = No`, `RefreshDelay = 2000`, with OBJECT upgrades granted by experience
levels. The native-dispatch regression tests exercise A grant followed by B grant,
not just direct wrapper calls. Restoring the stock dispatcher reproduces the
failure; enabling the type-specific exception clears the active flag.

Rebuild a binary carrying the slot-only version from its clean backup using the
same patch list. Applying over an existing `.aurconf` section is deliberately
rejected; verification reports the legacy helper explicitly. Do not install a
patch-only stock binary over a mod binary that requires its other engine patches.

The shared evaluator `0x008D26F3` exits at `0x008D2743` when flag04 is already set,
so an active aura never reaches its conflict test. The wrapper initializes two
0x90-byte masks using `0x005EA666`, builds them through vtable +0x2C, tests the
conflict mask for emptiness and selects all/any through +0x38. Both comparisons
receive the current held mask in ECX and the conflict mask as their one argument.
The callback preserves nonvolatile registers and returns with `ret 4`.

A conflict clears flag04 and returns false, matching the stock relevant-trigger
removal state. The aura update `0x0089F42D` then sleeps on the cleared flag. No
modifier cleanup or extra removal/reactivation hook is installed. Existing modifier
expiry remains engine-controlled; this is not a promise of instantaneous cleanup.
The Apply callback `0x008554D6` schedules through `GAME_LOGIC_SCHEDULE_UPDATE` with
**delay 1 frame**, not an enable boolean. Reset `0x008B88A8` calls the flag setter
`0x005B462D` with zero. These addresses and the aura-specific mask/bool callbacks
are recorded in `addresses/objects.py`; mask initialization and comparisons are in
`addresses/player.py`, scheduling in `addresses/logic.py`.

The user confirmed stock A grant/remove/regrant and conflict checks on inactive
modules in-game. This does not independently prove that removing B alone wakes a
sleeping aura; that transition is left stock. On 2026-10-18 the user confirmed the
corrected dispatcher patch in-game for Beorn: the later OBJECT upgrade conflict
disables the active aura. All-of combinations and PLAYER/related-object sources
are covered by emulation; they were not separately confirmed in-game.

Tests execute the native dispatcher and generated x86 against the stock mask-builder, bool callbacks and
comparison bytes, covering empty/partial/full conflicts, both ends of the 36-word
mask, inactive delegation and stack/register preservation. Synthetic PE tests cover
wrong-build rejection, corruption and unchanged neighboring slots/global evaluator.
They cover inactive activation, later conflicts from OBJECT, PLAYER and related-object
masks, all-of partial/full conflicts, unrelated active module types, and modules without
an UpgradeInterface. Ownership lookup, mask copying and activation scheduling are modeled.
An original executable can be used for apply/verify without launching or replacing
the installed game. Registration exposes the patch to the CLI; applying it remains explicit.
