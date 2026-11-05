# UpgradeModule conflicts after activation

`upgrade-module-conflicts` makes an active, standard `UpgradeModule` react when a later
upgrade satisfies its `ConflictsWith` mask. The class is `UpgradeModuleConflictsPatch`
in `patches/upgrades/upgrade_module_conflicts.py`.

No INI surface is added. Existing fields retain their native meanings:

```ini
Behavior = CostModifierUpgrade ModuleTag_Discount
  TriggeredBy = Upgrade_EnableDiscount
  ConflictsWith = Upgrade_DisableDiscountA Upgrade_DisableDiscountB
  RequiresAllConflictingTriggers = No
  Permanent = No
  Percentage = -10%
End
```

With `RequiresAllConflictingTriggers = No`, either conflicting upgrade disables the active
module. With `Yes`, the complete conflict mask must be held. An empty mask never disables it.
Player, Object and related-Object upgrade masks participate because the stock Object dispatcher
still constructs the combined held mask.

## Lifecycle contract

A conflict is deliberately expressed as if the module had lost its complete `TriggeredBy` mask:

1. invoke virtual slot `+0x0C`, the module's native removed-upgrade handler;
2. continue only if that handler reports a real active-to-inactive transition;
3. restore the active byte temporarily so the common removal helper can see the old state;
4. invoke `0x008D2688`, which applies native `Permanent`, slot `+0x20` cleanup and slot `+0x24`
   flag-setting semantics;
5. leave the executed flag zero.

Persistent modules such as `CostModifierUpgrade` must remove their Player-side records;
otherwise the price remains discounted and a later reactivation duplicates the record.

`Permanent = Yes` behaves exactly as it does for a lost trigger: the module becomes inactive but
the common helper skips its reversible cleanup. Removing the conflicting upgrade does not add a
new reactivation rule. Any later activation remains governed by the stock callbacks and events.
A module with no `TriggeredBy` mask does not claim a trigger-loss transition and is not forcibly
removed by this patch.

## Safe generic scope

The detour does not call arbitrary objects that merely expose something at the same interface
offset. An active interface is admitted only when its vtable has all of these contracts:

- slot `+0x00`: stock executed-flag getter `0x004986C4`;
- slot `+0x04`: stock added-upgrade entry `0x008D26BF`;
- slot `+0x0C`: generic removal `0x008D278A` or the ModelCondition variant `0x008D2901`;
- slot `+0x24`: stock flag setter `0x005B462D`;
- non-null mask builder at `+0x2C` and conflict-mode getter at `+0x38`.

Interfaces outside this contract keep the stock active skip. The mask builder remains virtual,
so standard modules and modules such as the aura with a specialised ModuleData layout both build
their masks through their own implementation.

## Binary implementation

Target: RotWK `game.dat` build `2.01.2614.37001`.

The patch allocates a `.upconf` section and installs two dispatcher detours in
`Object::updateUpgradeModules` (`0x006936FE`):

- `0x0069375B`, the ten-byte active gate, goes to the vtable-contract check;
- `0x0069379D`, the fourteen-byte virtual slot `+0x04` call, goes to a callback trampoline.

Inactive modules receive the displaced call byte-for-byte. Qualified active modules initialize
two 0x90-byte masks through `0x005EA666`, build them through virtual slot `+0x2C`, test empty/all/
any with `0x00444DCE`, `0x006AACB3` and `0x008097D6`, and run the lifecycle above. The dispatcher
continues at `0x006937AB`; the native slot `+0x18` notification remains unchanged.

A third call hook at `0x008B8300` teaches ObjectCreationUpgrade its all/any conflict mode;
see the per-module section below. Its active interfaces go directly to the native post-check,
preventing an extra cleanup call from the general dispatcher extension.

All engine addresses and stock fingerprints live in `sage_patch/addresses/objects.py`. Applying
validates the whole stock dispatcher and every called contract before allocating the cave.
Verification checks both dispatcher detours, the ObjectCreation evaluator call, the complete
cave and the unchanged anchors.

## Composition and verification status

The patch composes with `upgrade-module-removal` in either order. It calls that patch's public
entry contract at `0x008D2688`; when the companion is present, its transient removal state and
recursive-callback guard remain authoritative. Automated tests apply and verify both orders.

The aura path was confirmed in game for Beorn's later OBJECT-upgrade conflict. The
removal lifecycle, all/any combinations, both ends of the 36-dword mask, interface
qualification and companion-patch composition are executed under x86 emulation and structurally
verified against the supplied RotWK binary. The broader module set still needs in-game coverage,
so the registry reports this patch as `partly` runtime-verified.

## Checked module effects

The patch invokes native inverse handlers; it is not a transaction log and cannot manufacture
an inverse for every possible action. For reversible standard UpgradeModules use `Permanent = No`.
The following paths were checked in the supplied RotWK backup and executed under Unicorn:

| Module | Later conflict | Limits |
| --- | --- | --- |
| AttributeModifierUpgrade | Remove its named modifier from the object's pool and clear the latch; a later event after conflict removal can apply it again | Permanent=Yes skips native reversible cleanup; shared names retain the engine's native pool semantics |
| CommandSetUpgrade | Clear the matching override and dirty the command bar | Native override priority still applies; this does not save an arbitrary historical override |
| CommandSetUpgrade with commandset-button-upgrade | Rebuild the button union without the conflicting module; keep the other active modules and restore the removed contribution after reactivation | Uses the companion's actual upgrade/unupgrade hooks; test coverage includes both application orders and upgrade-module-removal |
| ObjectCreationUpgrade | Clear executed/armed state and the delay; optionally kill the SlaveWatcher-tracked spawned object | Does not reverse GrantUpgrade/RemoveUpgrade, delete arbitrary spawned objects or cancel already accepted production-queue jobs |
| AttributeModifierAuraUpdate | Stop the aura's active application path | Already distributed timed modifiers expire according to their native durations |

### ObjectCreationUpgrade's own lifecycle

Its UpgradeMux vtable is `0x00C6E250`, with native post-check `0x008B8329` and cleanup
`0x008B87C5`. The post-check already tests current player/object upgrade masks even for an active
module. Running both generic cleanup and this post-check would invoke its unguarded cleanup twice
in the same dispatch. The active gate therefore leaves this exact type to its own post-check.
The standard contract check is retained for other module types.

Its private evaluator at `0x008B82AB` originally always tests conflicts with ANY and ignores
`RequiresAllConflictingTriggers`. Only the call at `0x008B8300` changes: the helper asks virtual
slot +0x38 for its mode and uses the native ALL/ANY mask helpers; an empty conflict mask is false.
The original mask-building, trigger test, queue/spawn scheduling and native cleanup remain in place.
ObjectCreation's post-check merges player and object masks, as native; related-object masks are not
newly added to this specialized post-check. Its native cleanup is also not governed by the standard
UpgradeModule Permanent getter; do not assume the standard Permanent retention rule for this type.

`DestroyWhenSold = Yes` enables a lookup of the owner's `SlaveWatcherBehavior`, then its tracked
object ID. Only a live object found through that lookup is killed, with optional
`DeathAnimAndDuration`. With No or a missing watcher/live target, the spawned object remains.
This cleanup also runs for failed/conflicting upgrade conditions, despite the field's name.
Grant/Remove actions performed earlier are not undone. Without tracking the previous upgrade state
and each source of a grant, inventing an inverse would remove upgrades owned by other sources.

See [object-creation-upgrade.md](object-creation-upgrade.md) for the three requested parameters.

## Validation

The complete native Object dispatcher, native per-type removal handlers and the emitted command
button rebuild code execute against modeled string/UI/pool services. Coverage includes modifier
removal and reactivation, Permanent, preserved other overlay buttons, restored contributions,
ObjectCreation cancellation, no upgrade undo, DestroyWhenSold with/without a watcher, all/any/empty
conflict masks, production queue acceptance/retry, CLI use and manifest reconstruction.
The original aura's historical game confirmation is not a new game test of these broader paths.
New module behavior and real movie/audio/UI playback still need in-game acceptance testing.

On 2026-11-05, the selected patch/CLI/manifest regression suite completed with
3304 passed, 1 skipped and 7 deselected. Ruff and scoped Mypy checks passed.
The supplied backup also accepted and verified all of these together in both orders:
special-power-palantir-movie, upgrade-module-conflicts, commandset-button-upgrade,
upgrade-module-removal, hero-mana, special-power-music and upgrade-grant-lists.
These composition checks used memory copies; the backup's SHA-256 remained unchanged.
