# Object image upgrade

`object-image-upgrade` adds `ObjectImageUpgrade`, a presentation-only upgrade behavior for
changing the `SelectPortrait` and `ButtonImage` of one concrete object instance. It works for
heroes and normal units; objects created from the same `Object` definition can therefore display
different images according to the upgrades applied to each instance.

The patch affects only object-aware UI image resolution. In particular, an object's recruitment
or build button remains unchanged: that UI path reads the image from its `CommandButton`, not from
the concrete object. No gameplay attributes or simulation state are changed.

## INI usage

```ini
Behavior = ObjectImageUpgrade ModuleTag_Level5Image
    TriggeredBy    = Upgrade_Level_5
    ConflictsWith  = Upgrade_SomethingOptional
    RequiresAllTriggers = No
    RequiresAllConflictingTriggers = No
    SelectPortrait = HP_Hero_Level5
    ButtonImage    = HI_Hero_Level5
End
```

`TriggeredBy` and `ConflictsWith` use the normal `UpgradeModule` evaluation. The behavior applies
when that evaluation succeeds. A conflict that is present at evaluation time can prevent the
behavior from activating.

`SelectPortrait` and `ButtonImage` are mapped-image asset references. Their values must name
`MappedImage` assets loaded in the active INI and asset set. The patch resolves both names when the
behavior applies. An empty or unknown name resolves to no image and therefore supplies no override
for that field; the normal resolver, or another valid matching override, can still provide it.

Either image field may be omitted. For example, a behavior can replace only the selected-object
portrait while leaving the effective button image alone.

## Triggering and precedence

Multiple `ObjectImageUpgrade` behaviors on the same object are supported. For each image field,
the last successfully applied behavior with a valid image wins. Consequently:

- a later successful trigger can replace an earlier portrait, button image, or both;
- a behavior with only `SelectPortrait` does not erase a valid `ButtonImage` supplied by another
  behavior, and vice versa;
- repeating or alternating upgrade sequences are supported; and
- retriggering the same behavior on the same object makes it the most recent winner again.

The implementation reuses the existing record for the same object instance and source behavior.
Repeated triggers therefore do not allocate an unbounded number of records. An `A -> B -> A`
sequence reorders and refreshes the existing A record rather than creating a third one.

## Sticky image semantics

An applied image override is deliberately **sticky**. It is not automatically removed when the
upgrade named by `TriggeredBy` is later lost. Likewise, a `ConflictsWith` upgrade acquired after a
successful activation does not roll the image back to an earlier or vanilla value.

SAGE reevaluates upgrade modules through several lifecycle and reset callbacks. Those callbacks do
not provide a reliable persistent-deactivation edge for this use case. Treating them as one could
clear a valid image during an ordinary reevaluation or reset. The patch therefore preserves stock
upgrade evaluation for activation and uses sticky presentation state instead of adding risky
Evaluate/Unapply rollback logic.

To switch back, trigger another `ObjectImageUpgrade` that explicitly supplies the desired image:

```ini
Behavior = ObjectImageUpgrade ModuleTag_ArmoredImage
    TriggeredBy    = Upgrade_ArmorMode
    SelectPortrait = HP_Unit_Armored
    ButtonImage    = HI_Unit_Armored
End

Behavior = ObjectImageUpgrade ModuleTag_NormalImage
    TriggeredBy    = Upgrade_NormalMode
    SelectPortrait = HP_Unit_Normal
    ButtonImage    = HI_Unit_Normal
End
```

The mod must arrange for `Upgrade_NormalMode` to be evaluated after the return to normal mode. Its
successful application then becomes the most recent override. Removing `Upgrade_ArmorMode` alone
does not perform that transition.

## Scope of the visual change

`SelectPortrait` changes the portrait returned for the concrete selected object. `ButtonImage`
changes the effective object button image on the patched object-aware UI path, including uses such
as HeroBar entries.

Recruitment and build buttons are intentionally outside this patch. They resolve their art from a
`CommandButton`, before or independently of a concrete object instance, so their vanilla image
does not change when `ObjectImageUpgrade` applies.

## Lifetime and capacity

The patch stores local presentation-side override records for object instances in a fixed sidecar
pool. Each record is associated with:

- the `Object *` address;
- the object's `ObjectID`;
- the source behavior runtime; and
- the resolved portrait and button `Image *` values.

The `ObjectID` is checked together with the pointer. If SAGE destroys an object and later reuses
the same address for a new object, a record from the old instance cannot supply images to the new
one. When Apply encounters that same pointer with a different ID, it may reclaim the stale record.
The same object, ID, and source behavior also reuse their existing record on retrigger.

The current implementation has **2048 records**. Reuse and same-address stale-record reclamation
keep ordinary use well away from this limit, but this is not unlimited storage. An extreme or very
long-running session with many once-used behavior instances and insufficient pointer reuse could
fill the pool because there is no general object-destruction cleanup. If the pool is full, a new
source has no override recorded; existing sources can still be refreshed and reordered. The patch
does not write out of bounds or alter simulation state in this case.

The practical failure mode of capacity exhaustion is therefore a missing visual override, not a
gameplay effect. Content should nevertheless avoid designing around an unlimited number of unique,
one-shot `ObjectImageUpgrade` instances during one active session.

## Multiplayer and determinism

The patch is designed to be multiplayer-safe and presentation-only. It changes local UI resolution
through the `Image *` sidecar and marks the ControlBar dirty after Apply. It does not modify object,
player, upgrade, command, RNG, Xfer/serialization, or other synchronized simulation state. The
sidecar is neither serialized nor included in simulation CRC state.

With identical patched `game.dat`, INI, and assets on every peer, the simulation-desync risk is
therefore very low. Process-local pointer values are used only as local lookup keys and are never
synchronized.

This is deliberately not an absolute guarantee of identical presentation. Different assets, a
failed image lookup, or sidecar exhaustion could make an override appear on one client but not
another. Such a difference is visual and is not expected to cause a SAGE simulation desync, as
long as no separate mod logic incorrectly depends on the displayed image.

## Troubleshooting

### The image does not change

Check that the `MappedImage` name is spelled correctly and that its definition and backing asset
are loaded in the current branch or asset set. An unresolved name creates no override for that
field. Also confirm that the normal `TriggeredBy`/`ConflictsWith` evaluation actually permits the
behavior to apply.

### The recruitment or build image remains unchanged

This is expected. Recruitment and build buttons use the `CommandButton` image path, which this
patch intentionally does not intercept.

### Removing the upgrade does not restore the old image

This is expected sticky behavior. Trigger another `ObjectImageUpgrade` with the portrait or button
image that should become active.

## Implementation notes

These details document the current RotWK `game.dat` implementation and are primarily useful to
contributors:

- `ObjectImageUpgrade` is registered as a separate module while using `TooltipUpgrade` as the
  confirmed layout twin: ModuleData is `0x140` bytes, the runtime is `0x1C` bytes, and
  `UpgradeMux` is at runtime offset `+0x10`.
- The private ModuleData fields at `+0x138` (`SelectPortrait`) and `+0x13C` (`ButtonImage`) are
  engine `AsciiString` values parsed with the stock ASCII-string parser. The exposed INI surface
  types them semantically as mapped-image references (`Ref:mappedimages`).
- The sidecar key is `Object * + ObjectID + source runtime`. It deliberately does not use
  `Drawable *`: the pointer at `Object + 0x84` is not a stable identity for the full object
  lifetime.
- Stock upgrade evaluation and lifecycle handling remain in place. The custom Apply callback is
  at vtable slot `+0x28`; the `+0x20` Unapply callback is a neutral return, implementing the sticky
  semantics without an Evaluate/Unapply rollback wrapper.
- Each object-aware resolver scans matching records in order and retains the last non-null image
  for its field. Fallback paths replay the displaced vanilla instructions when there is no valid
  override.

The Apply and UI paths have been exercised in game with heroes and normal units, both image fields,
multiple behaviors, last-triggered precedence, `TriggeredBy`, conflicts present at activation, and
repeating or alternating upgrades. The sticky behavior and unchanged recruitment path are
intentional limits of that tested scope.
