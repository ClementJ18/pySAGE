# Object image upgrade

`object-image-upgrade` adds a presentation-only upgrade behavior to RotWK:

```ini
Behavior = ObjectImageUpgrade ModuleTag_Level5Image
    TriggeredBy    = Upgrade_Level_5
    SelectPortrait = HP_Hero_Level5
    ButtonImage    = HI_Hero_Level5
End
```

`SelectPortrait` affects the selected-object portrait. `ButtonImage` affects object-aware image
resolution such as HeroBar entries. Recruitment remains unchanged because it resolves the image
from its `CommandButton`, not from the concrete object.

## Design

The patch registers a new module without changing or replacing `TooltipUpgrade`. It reuses that
module's established `UpgradeMux` layout: 0x140 bytes of ModuleData, a 0x1C-byte runtime, and the
generic `TriggeredBy` processing. Its private ModuleData tail is:

| Offset | Type | Field |
|---:|---|---|
| `+0x138` | `AsciiString` | `SelectPortrait` |
| `+0x13C` | `AsciiString` | `ButtonImage` |

Apply resolves each name through `TheMappedImageCollection` on every successful trigger. The name
must refer to a mapped image present in the active INI/assets; a missing name resolves to null and
does not override that image field. A fixed patch-owned
sidecar stores `(Object *, source module *, select Image *, button Image *)`.
The two UI getters scan only pointer rows; there are no per-frame string lookups or upgrade
queries. The `+0x20` callback is intentionally a no-op; stock `+0x04`/`+0x08` upgrade evaluation is
left untouched, and custom Apply occupies `+0x28`.

The hooks scan matching rows from first to last and retain the last non-null image. Thus, when an
object has multiple `ObjectImageUpgrade` behaviors, the last successfully applied behavior wins
for each non-null field. Reapplying the same `(Object *, source module *)` does not allocate a
duplicate row: its existing row is stably moved to the occupied tail and overwritten, so an
`A -> B -> A` sequence makes A win again without consuming a third slot. A later successful
trigger, including a repeating or alternating upgrade sequence, can overwrite the image again.
They never inspect the object's internal module storage and scan only patch-owned rows. The fixed table has
2048 rows; if exhausted, a new source is ignored rather than writing out of bounds, while an
existing source can still be moved to the tail and refreshed. Upgrade loss and late
`ConflictsWith` use the documented sticky semantics below; row cleanup is intentionally absent.
No object-destruction hook is installed because the former Drawable hook cannot safely clean a
table keyed by Object pointers.

This is deliberately sticky presentation state. `ConflictsWith` can prevent activation when it is
already true at trigger time. Losing `TriggeredBy` later, or gaining `ConflictsWith` later, does
not automatically restore an earlier or vanilla image. Use a later `ObjectImageUpgrade` when an
explicit overwrite is wanted. This behavior is a documented limitation/feature, not reversible
upgrade lifecycle semantics.

## Hooks and confirmed engine facts

| Address | Use |
|---:|---|
| `0x0065A7F2` | append the new ModuleFactory registration after TooltipUpgrade |
| `0x00694F06` | `Object::getEffectiveSelectPortrait`, `ECX = Object *` |
| `0x0073D0BA` | effective object button image, cdecl `(ObjectTemplate *, Object *)` |
| `0x006DA34C` | `MappedImageCollection::findImageByName` |
| `0x00DE4AC0` | `TheMappedImageCollection` |

The select hook steals eight bytes so the call beginning at `0x00694F09` is never split. Every
fallback replays the displaced instructions and resumes in the untouched stock function.

## Multiplayer and persistence

The patch changes no `Object`, `Drawable`, player, upgrade, command or simulation state. Its
sidecar is not serialized or included in CRC state and contains only UI pointers derived from INI
names. It reads no clock and uses no RNG. With identical `game.dat` and INI data on all peers it
therefore has very low desync risk when every peer uses identical patched `game.dat`, INI and
assets. Pointer values are process-local and are never synchronized. Sticky behavior likewise
changes presentation only; it is not a desync path.

The Apply/UI path has been exercised successfully in game with heroes and normal units, both image
fields, multiple behaviors, last-triggered precedence, `TriggeredBy`, `ConflictsWith` at activation,
and repeating or alternating upgrades. Hero recruitment remains vanilla because it uses the
separate `CommandButton` path. The fixed sidecar is not reclaimed; long-running content that
reaches 2048 distinct `(Object *, source module *)` pairs will have later new-source overrides
ignored. Retriggering an existing pair reuses its row. No destructor cleanup is installed.
