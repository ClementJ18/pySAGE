# `PortraitImageName` and `ButtonImageName` on a model condition state

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Static recovery plus emulated tests of the cave -
**nothing here has been run in a game yet**; §6 is what a first session should look at. Shipped as
[`../patches/model_condition_images.py`](../patches/model_condition_images.py).

**The finding in one sentence.** Both fields parse into every `ConditionState`, but the two UI
image resolvers only consult them through a Create-a-Hero hero's own record, so for any other
object they are parsed and never read.

## 1. The fields

Rows 4 and 5 of the `ModelConditionState` field table at `0x00BE0A78` (the one
`MODEL_FIELD_TABLE_ROW` names), both `INI::parseAsciiString` (`0x0042EE5E`):

```
00be0ab8  {"PortraitImageName", 0x0042EE5E, 0, 0x60}
00be0ac8  {"ButtonImageName",   0x0042EE5E, 0, 0x5C}
```

`OverrideTooltip` (`+0x74`) from the same table *is* generic: `W3DModelDraw::setModelState` pushes it
into the Drawable (`0x004C455B`..`0x004C4562`, `Drawable+0x348` via `0x006796DA`). The two image
fields have no such consumer.

## 2. Why only Create-a-Hero heroes show them

The select portrait of an object comes from `0x00694F06`:

```
00694f2b  mov  eax, [esi+4]                 ; ThingTemplate
00694f2e  test byte [eax+0x11f], 0x40       ; KindOf[190] = CREATE_A_HERO
00694f36  je   0x694f9a                     ; clear: the template path
...
00694f7e  push [esi+0x74]                   ; the hero's id
00694f81  mov  ecx, [0xde3d84]              ; TheCreateAHeroManager
00694f87  call 0x619562                     ; its record, searched through the GameInfo slots
00694f90  mov  eax, [eax+0x13c]             ; the record's portrait Image *
...
00694faa  call 0x73d0a3                     ; (template, object) -> ThingTemplate::getSelectPortrait
```

The button image (`0x0073D0BA`, eight callers including the hero bar) is the same shape: the same
`CREATE_A_HERO` test at `0x0073D0CC`, the record's `+0x140`, else `0x0073D0F1`, which reloads the
template and tail-jumps to `ThingTemplate::getButtonImage` (`0x0073CFEF`).

`ThingTemplate::getSelectPortrait` (`0x0073CF31`) resolves `SelectPortrait` (`template+0x74`) once,
caches the `Image *` at `+0x498` and frees the name, so the template path costs a pointer read.

The record's two images are what a CaH hero's chosen appearance resolved to, and they are fixed for
the game. Nothing on either path asks a draw module for its current state, so this is not a
performance trade-off, just a feature built for Create-a-Hero and never generalised.

## 3. A model draw's current state

`W3DModelDraw::setModelState` is vtable slot `+0x100`. There are two implementations, and the only
`.rdata` dwords holding them are seven vtables, exactly the model draw family of
[`draw-module-scale.md`](draw-module-scale.md) §5:

| implementation | vtables (slot `+0x100` at) | stores the new state |
|---|---|---|
| `0x004C451D` | `0x00BE00E8` `0x00BE1C98` `0x00BE2020` `0x00BE25E8` `0x00BE2B80` `0x00BE3D40` | `0x004C52B2`: `mov eax,[ebp+8]` ... `mov [esi+0x14], eax` |
| `0x0047A0AD` (`W3DHordeModelDraw`) | `0x00BDC910` | `0x0047AA8A`: `mov [esi+0x14], ebx` |

So `m_curState` is `module+0x14`, and "slot `+0x100` is one of the two" is an exact test for a
module that has it. `getObjectDrawInterface` (`+0xA8`, `0x004C9323`) is **not** a usable test: its
body (`return this ? this+0xC : 0`) is identical-code-folded with unrelated casts, sits in 34 slots,
and also answers for the non-model draw at `0x00BDF708`.

From the object: `Object::getDrawable` (`0x0070E013`) is `mov eax,[ecx+0x84]; ret`, and the
Drawable's draw modules are a NULL-terminated pointer array at `Drawable+0x14C`
([`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md) §2; `0x006728A1` walks it).

An `AsciiString` is a pointer to `{refs, UnsignedShort length at +4, chars at +8}` or NULL
(`0x00401E64`). Images are looked up by name with `0x006DA34C`, `__thiscall` on `[0x00DE4AC0]`,
`(AsciiString *) -> Image *`, `ret 4` (what `object-image-upgrade` already calls).

## 4. The patch

Four `jmp` hooks into one `.mcimg` cave:

| site | stock | does |
|---|---|---|
| `0x0073D0A3` | `mov ecx,[esp+4]; test ecx,ecx` | portrait: the state's image, else replay and resume at `0x0073D0A9` |
| `0x0073D0F1` | `mov ecx,[esp+4]; jmp 0x73CFEF` | button: the state's image, else replay |
| `0x004C455B` | `mov ecx,[esi+8]; lea eax,[edi+0x74]` | base `setModelState`: dirty check, replay |
| `0x0047A0C8` | `mov ecx,[esi+0xC0]` | Horde `setModelState`: dirty check, replay |

No branch lands inside any displaced range, and none of the four is touched by another registered
patch (`tests/sage_patch/test_model_condition_images.py` applies it alongside
`object-image-upgrade` in both orders).

**Resolution.** Walk the Drawable's modules in order. For the first model draw whose current state
has a non-empty name that resolves to an image, use that image. An empty or unknown name, or no
model draw, falls through to the stock template path unchanged.

**Precedence**, top wins: `object-image-upgrade`'s override (it hooks the resolver entries), then a
Create-a-Hero record, then the current model state, then the template. The portrait hook sits in
`0x0073D0A3`, which `0x00694F06` also calls for the object a container displays instead of itself,
so that object's state is consulted too.

**Refresh.** The ControlBar only re-resolves when its dirty byte (`[0x00DE7744]+0x28`, cleared by
`evaluateContextUI` at `0x0071EBDA`) is set. On `setModelState`, if the old state is non-NULL,
differs from the new one, and either name's `AsciiString` buffer pointer differs, the cave sets
that byte. States that inherit a name from `DefaultConditionState` share the buffer, so moving
between them costs nothing. Two states that spell the same name separately cause one spurious
re-evaluation. A first state (old NULL) is a fresh drawable that nothing has selected yet.

## 5. INI

```ini
Draw = W3DScriptedModelDraw ModuleTag_Draw
    DefaultConditionState
        Model = GUHero_SKN
    End
    ConditionState = MOUNTED
        Model             = GUHeroMounted_SKN
        PortraitImageName = HP_Hero_Mounted
        ButtonImageName   = HI_Hero_Mounted
    End
End
```

A state with neither field shows the Object's `SelectPortrait` / `ButtonImage`. A name set on
`DefaultConditionState` is copied into every state that follows it, so it acts as the draw's
default over the Object's.

## 6. Unknown, and what to check in game

- **Transition states.** `TransitionState` blocks go through `setModelState` too. One without the
  fields shows the template image for its duration; whether that flickers visibly is untested.
- **The hero bar.** Its buttons go through `0x0073D0BA`, and `object-image-upgrade` saw them
  update on the same dirty byte. Confirm they follow a state change without a reselect.
- **Multiple model draws.** The first in module order with a name wins; check it is the one a mod
  expects on an object with several draws (a mount and a rider).
- **A CaH hero's own states.** CaH heroes take the record path and never reach this cave; if
  their portrait should follow state too, the `CREATE_A_HERO` arm needs the same treatment.
