# UpgradeModule conflicts after activation

`attribute-modifier-aura-conflicts` makes an active, standard `UpgradeModule` react when a later
upgrade satisfies its `ConflictsWith` mask. The old name is retained for CLI and manifest
compatibility; the patch is no longer restricted to `AttributeModifierAuraUpdate`.

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

This is materially different from the first aura-only implementation, which only cleared the
flag. Persistent modules such as `CostModifierUpgrade` must remove their Player-side records;
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

The patch keeps the `.aurconf` section name and installs two detours in
`Object::updateUpgradeModules` (`0x006936FE`):

- `0x0069375B`, the ten-byte active gate, goes to the vtable-contract check;
- `0x0069379D`, the fourteen-byte virtual slot `+0x04` call, goes to a callback trampoline.

Inactive modules receive the displaced call byte-for-byte. Qualified active modules initialize
two 0x90-byte masks through `0x005EA666`, build them through virtual slot `+0x2C`, test empty/all/
any with `0x00444DCE`, `0x006AACB3` and `0x008097D6`, and run the lifecycle above. The dispatcher
continues at `0x006937AB`; the native slot `+0x18` notification remains unchanged.

All engine addresses and stock fingerprints live in `sage_patch/addresses/objects.py`. Applying
validates the whole stock dispatcher and every called contract before allocating the cave.
Verification checks both detours, the complete cave and the unchanged anchors.

## Composition and verification status

The patch composes with `upgrade-module-removal` in either order. It calls that patch's public
entry contract at `0x008D2688`; when the companion is present, its transient removal state and
recursive-callback guard remain authoritative. Automated tests apply and verify both orders.

The earlier aura path was confirmed in game for Beorn's later OBJECT-upgrade conflict. The
generalized removal lifecycle, all/any combinations, both ends of the 36-dword mask, interface
qualification and companion-patch composition are executed under x86 emulation and structurally
verified against the supplied RotWK binary. The broader module set still needs in-game coverage,
so the registry reports this patch as `partly` runtime-verified.

A binary carrying the earlier slot-rewrite `.aurconf` must be rebuilt from a clean backup. The
patch deliberately refuses to stack a second section with the same identity.
