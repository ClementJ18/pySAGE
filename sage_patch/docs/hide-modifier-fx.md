# hide-modifier-fx

**Goal:** give `Object` a `HideModifierFX = Yes` switch. Attribute modifiers keep applying to the
object, but the `FX`/`FX2`/`FX3` of their `ModifierList` are not played on it. It is meant for
invisible helper objects that a mechanic needs, like Edain's `BrandGroupObject`, which currently
pick up a leadership glow (`FX = FX_GenericLeadership`) from any aura whose `ObjectFilter` they
pass.

**Status:** static only. Applied and verified against the shipped build (63 patches, all still
detected afterwards), and the cave's routines run under unicorn in
`tests/sage_patch/test_hide_modifier_fx.py`. Not yet played.

## 1. There is nothing to configure today

`ModifierHolder::applyModifierList` (`0x00805A8E`) is where every one of the 32 modifier sources
ends up (see `OBJECT_APPLY_MODIFIER_LIST` in `address-notes.md`). It plays the list's FX in two
places, and neither one checks anything about the target:

```
; a list newly applied
00805ca4  call 0x6144fe / 0x61452e     ; pick FX, FX2 or FX3 (MultiLevelFX)
00805cb4  mov  ebx, [ebx+8]            ; the holder's Object
00805cb7  push 0 / push ebx / push eax
00805cbb  call 0x4b1b5a                ; FX_LIST_PLAY_AT_OBJECT

; a live list refreshed
00805d2c  mov  ecx, [ebx+8]
00805d2f  push edi(0) / push ecx / push eax
00805d32  call 0x4b1b5a
```

`AttributeModifierAuraUpdate` exposes `ObjectFilter`, `AffectsKindOf` and the `Affect*` switches,
but nothing that separates the effect from its FX. The stock way to keep a helper clear is to keep
it out of every filter. Across Edain those filters include `+INFANTRY` 360 times and `+CAVALRY`
363 times, so an object that needs `INFANTRY` for some other reason cannot do that.

A new KindOf was the first choice and is not available. `KindOfMaskType` is 224 bits, and
`herobar` has already used the last two free ones (`herobar.md` §2).

## 2. Where the flag lives

`ThingTemplate` has no free byte (`second-resource.md` §7.1). The flag therefore goes in a
**64 KiB array in the cave, indexed by the template's engine-assigned `UInt16` id** at `+0x5E8`.
Every id has a slot, so no bound check is needed. This avoids `hero-mana`'s pointer-keyed hash and
its `copyFrom` hook, because the id already goes wherever template identity goes. There are six
writers of `+0x5E8` in `.text`:

| site | what | effect on the flag |
|---|---|---|
| `0x0073FF8D` | constructor zeroes it | none; `newTemplate` assigns next |
| `0x006D2859` | `ThingFactory::newTemplate`, up-counting id, **before** any field parses | the parse function writes that template's own slot |
| `0x006D24BE` | `copyFrom` copies the source's id (override blocks via `newOverride`) | an override shares its original's slot, so it inherits the flag and can set it |
| `0x00740630` | the identity-keeping copy at `0x007405B1` restores the destination's own id after `copyFrom` | **hooked:** the destination's slot takes the source's flag, like every other copied field |
| `0x006D1126`/`0x006D113A` | `ThingFactory::addTemplate` on a name already registered: the newcomer takes the old id, and the old template gets a fresh one from the down-counter `0x00DA18E4` | **hooked:** the old template's new slot keeps its flag; the inherited slot is cleared for the newcomer's own fields |
| `0x006CFBCC` | a setter with no direct caller | not reached |

## 3. The patch

* **The field.** The `Object` field table is rebuilt in the cave with one extra row: keyword,
  the cave's parse function, `userData` 0, offset 0. All five references are repointed
  (`OBJECT_FIELD_TABLE_REFS`). The parse function reads `movzx eax, word [tmpl+0x5E8]` and calls
  the engine's own `INI::parseBool` (`0x0042E558`) with `store` pointing at that slot.
* **The gate.** Both `call 0x4b1b5a` sites are retargeted to a routine with the same cdecl
  shape. It follows `object → [+4] template → +0x5E8 id` and returns without playing when the
  slot is set; otherwise it tail-jumps to `FX_LIST_PLAY_AT_OBJECT`. The caller's own
  `add esp, 0xC` balances either way, and neither caller reads `eax`. A NULL object or template
  goes to the engine unchanged.
* **The two id movers** (§2) are `jmp` hooks that replay their displaced bytes. The displaced
  code has no relative operands, and no direct branch lands inside either window (`xref` of
  every interior byte is empty).

Everything is presentation. The modifier itself, which is the logic, is applied exactly as
before, so peers with and without the patch stay in sync.

## 4. Known limits

* **`map.ini` overrides persist.** An override shares its original's slot, so a `map.ini` that
  sets `HideModifierFX` on an existing object leaves the value set after that map, until the game
  restarts. Setting it in the global INI, which is where this field belongs, has no such problem.
* **Worldbuilder** (the stock editor) does not know the field. By the same reasoning as
  `special-power-music.md`, an editor INI containing it will fail to load until a counterpart
  exists. `sage_worldbuilder` is unaffected.
* **Other FX paths are untouched.** An aura's own `AntiFX`, a weapon's `FireFX`, and model
  conditions set by `ModelCondition =` on the `ModifierList` still apply. Only the list's
  `FX`/`FX2`/`FX3` are gated.

## 5. Verifying it in a game

1. `HideModifierFX = Yes` parses on an `Object` block; an unpatched `game.dat` rejects it.
2. `BrandGroupObject` with the field set, standing inside a leadership aura, shows no glow, and
   the bonus is still applied (check with `sage_live` or a visible stat).
3. A visible unit without the field, in the same aura, still glows.
4. A `ChildObject`/reskin of a flagged object is also hidden, and an override block that sets
   `HideModifierFX = No` shows the glow again.

## Addresses

| VA | what |
|---|---|
| `0x00805CBB`, `0x00805D32` | `MODIFIER_HOLDER_APPLY_FX_CALLS` |
| `0x004B1B5A` | `FX_LIST_PLAY_AT_OBJECT`, cdecl `(fx, object, unused)` |
| `0x0042E558` | `INI_PARSE_BOOL` |
| `0x00740630` | `THING_TEMPLATE_COPY_KEEP_ID` |
| `0x006D112D` | `THING_FACTORY_ID_SWAP` |
| `+0x5E8` | `THING_TEMPLATE_ID` |
