# CostModifierUpgrade discount groups

`cost-modifier-upgrade-groups` adds one optional field to `CostModifierUpgrade`:

```ini
Behavior = CostModifierUpgrade ModuleTag_BlacksmithDiscount
  TriggeredBy = Upgrade_BlacksmithEnabled
  UpgradeDiscount = Yes
  DiscountGroup = BlacksmithForging
  Percentage = 0% -10% -15% -20%
  ApplyToTheseUpgrades = Upgrade_ForgedBlades Upgrade_HeavyArmor
  LabelForPalantirString = CONTROLBAR:BlacksmithDiscount
End
```

`DiscountGroup` is an `AsciiString`. It affects only `UpgradeDiscount = Yes`. Empty or absent is
fully stock: the carrier Object's actual template name remains the Player record key and the
Palantir retains the stock aggregate query.

## Group semantics

Stock upgrade discounts group active modules by this exact tuple:

```text
(carrier template name, complete Percentage vector, complete ApplyToTheseUpgrades vector)
```

The patch replaces only the first element when `DiscountGroup` is non-empty:

```text
(DiscountGroup, complete Percentage vector, complete ApplyToTheseUpgrades vector)
```

Consequently, differently named carrier Objects and different `BuildVariations` can increment one
shared ladder. Different group names remain separate records and the stock final price query adds
their current values. The vectors deliberately remain part of the key: modules using the same
group name but different `Percentage` or `ApplyToTheseUpgrades` definitions form separate records
rather than silently sharing an incoherent level.

The add and remove hooks are at the common Player helpers `0x006B2C67` and `0x006B1992`. Those
helpers are used by ordinary activation, deletion and both ownership-transfer arms, so every
lifecycle path selects the same key. Object-cost mode (`UpgradeDiscount = No`) never calls them
and remains unchanged.

## Palantir value

In stock, the upgrade-mode Palantir getter at `0x0092F712` passes the empty `AsciiString` to
`Player::getUpgradeDiscount`. Empty matches every record, so a label owned by Object A can display
the sum of unrelated discounts from Object B.

For a non-empty group, the patch instead searches `Player+0x3D0..+0x3D4` for the exact tuple above
and returns that record's current percentage at `+0x20`. The shown number is therefore the current
rung contributed by the selected module's group, not the total price reduction of an arbitrary
upgrade. If no exact record exists it shows zero. An empty group still executes the original
empty-name sum.

The ControlBar still finds one module named `CostModifierUpgrade` on the selected Object. This
patch does not add multiple Palantir rows for multiple visible CMU blocks.

## Binary implementation

Target: RotWK `game.dat` build `2.01.2614.37001`.

`CostModifierUpgradeModuleData` grows from `0x15C` to `0x160`; the appended `AsciiString` is at
`+0x15C`. The patch:

- changes the allocation immediate at `0x006500BC`;
- wraps the constructor call at `0x006500D4` to initialize the appended string;
- detours the destructor entry at `0x008B9E4D` to release it before native destruction;
- relocates the seven-row field table from `0x00C6EF48`, appends `DiscountGroup` with parser
  `0x0042EE5E`, and repoints the push at `0x008B9ECD`;
- selects the group key at Player add/remove entries `0x006B2C67` and `0x006B1992`;
- replaces the upgrade-mode query window `0x0092F722..0x0092F73A` with exact record lookup.

The `.cmugrp` section contains the copied stock field rows, keyword and executable helpers. Stock
rows are copied verbatim after their names and offsets are fingerprinted. All addresses and
record-layout constants live in the appropriate `sage_patch/addresses` modules.

## Compatibility

The patch composes with `player-upgrade-discount` in either application order. That patch changes
which upgrade types may consume the Player records; this patch changes how explicitly grouped
records are formed. The stock final price calculation remains untouched.

All peers in a multiplayer match must use the same patched binary and data. Saves created under
the patch are internally consistent because add, remove and capture use one key. Loading a save
created before the patch is not supported when a currently active module gains a non-empty
`DiscountGroup`: the saved Player record is keyed by carrier name, while later removal is keyed by
the group. Rebuild or restart such a match rather than changing the field in a live save.

The patch has structural verification against the supplied RotWK binary and executed x86 tests
for add/remove key symmetry, constructor/destructor ownership, exact group lookup, empty-group
fallback and companion-patch composition. It has not yet been confirmed in a running game.
