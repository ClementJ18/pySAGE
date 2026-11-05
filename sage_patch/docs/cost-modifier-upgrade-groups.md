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

### Worldbuilder

Install `cost-modifier-upgrade-groups-wb` on `Worldbuilder.exe` when loading data that contains
`DiscountGroup`. The game patch alone does not extend the editor's independent INI parser.
Suppressing editor diagnostics with `worldbuilder-silent-errors` does not register the keyword.

```bash
python -m sage_patch apply cost-modifier-upgrade-groups-wb --in Worldbuilder.exe.backup --out Worldbuilder-grouped.exe
python -m sage_patch verify cost-modifier-upgrade-groups-wb Worldbuilder-grouped.exe
```

The companion is parser-only. It consumes the value through the editor's native
`INI::getNextToken` and discards it. It does not allocate a string, change the `0x15C` ModuleData
layout, or install game discount and Palantir hooks. Original keywords retain their parsers,
and unrelated unknown keywords still reach the editor's existing diagnostic path.

The editor's private seven-row table is at `0x01F531D0`; its builder is at `0x01251CB0`.
Only the five-byte table-append call at `0x01251CCD` changes. A wrapper first replays the native
append with its original table and offset, then appends a separate `DiscountGroup` table. The
base UpgradeModule table and the private CostModifierUpgrade table remain in place. The extra
row and both helpers live in `.wbcmug`. The native append is `0x006CD090`, and the token reader
is `0x006D20A0`. All editor addresses and stock fingerprints are in `addresses/worldbuilder.py`.

The reference `Worldbuilder.exe.backup` has SHA-256
`005971beb68d0485846ff5f62d6f043e9c9b89d6576525ee25b56e9d305ec65d`.
Apply rejects mismatched hooks and dependencies before mutation, and verify checks the entire
new section, the detour and unchanged anchors. Tests execute the patched native field builder
and INI parser with modeled input, tokenizer and macro lookup services, and check companion-patch
composition.
The editor GUI has not been launched for acceptance testing.

### Game

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
