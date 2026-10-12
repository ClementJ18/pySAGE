# `GrantScienceUpgrade`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`).

This is the write-up for **`grant-science-upgrade`** and its editor twin
**`grant-science-upgrade-wb`**, [`patches/grant_science_upgrade.py`](../patches/grant_science_upgrade.py),
with tests in
[`tests/sage_patch/test_grant_science_upgrade.py`](../../tests/sage_patch/test_grant_science_upgrade.py).

```sh
sage-patch apply grant-science-upgrade --in game.dat.backup --out game.dat
sage-patch apply grant-science-upgrade-wb --in Worldbuilder.exe --out Worldbuilder_patched.exe
```

**Status: built and static-verified, not run in a game.** Both halves apply, verify and are
detected on the real binaries (the repo's `game.dat` and RotWK 2.01's `worldbuilder.exe`), and each
composes with its `object-image-upgrade` counterpart in either order. §6 is the in-game checklist
still to run.

**What it would do:** bring back Zero Hour's upgrade module that grants a science to the owning
player when the upgrade triggers:

```ini
Behavior = GrantScienceUpgrade ModuleTag_GrantAnduril
    TriggeredBy  = Upgrade_ReforgeNarsil
    GrantScience = SCIENCE_Anduril
End
```

RotWK has no such module, and the string `GrantScience` does not occur anywhere in `game.dat`.
Stock INI can give a player a science in three ways only: `PlayerTemplate` `IntrinsicSciences[MP]`
at game start, `Rank` `SciencesGranted` on a rank-up, and a `PURCHASE_SCIENCE` button. Maps also
have script action 280, `PLAYER_GRANT_SCIENCE`.

## 1. The engine already has the grant

Script action 280 dispatches (switch table `0x007CF857`, case arm `0x007CE037`) to
`ScriptActions::doGrantScience` at `0x007BD1BA`. That handler makes the two calls a module needs:

| address | what | convention |
|---|---|---|
| `0x005FEF8F` | `ScienceStore::friendlyNameToScience(const AsciiString &)`, which returns `-1` for an unknown name | `__thiscall` on `[THE_SCIENCE_STORE]` (`0x00DE3B20`), `ret 4` |
| `0x006AE3A7` | `Player::grantScience(ScienceType)` | `__thiscall`, `ret 4` |

`grantScience` checks `ScienceStore` `0x005FECBA`, which returns byte `+0x30` of the science, its
`IsGrantable` (default `Yes`). It then calls `Player::addScience` at `0x006AE186`, which:

- returns at once if the player already has the science (`0x006AC207`), so a grant is idempotent;
- appends the science to `Player+0x310` (`PLAYER_SCIENCES`);
- walks the player's objects (`[Player+0x34C]`, from `0x006AE1BC`) and notifies their modules.
  This is how special powers that require the science wake up.

A module that makes the same two calls therefore behaves exactly like `PLAYER_GRANT_SCIENCE`, with
no new game logic.

## 2. The module

It is `object-image-upgrade`'s registration skeleton and nothing else of that patch: the same
`TooltipUpgrade` layout twin, so the stock `UpgradeMux` evaluates `TriggeredBy` / `ConflictsWith` /
`RequiresAllTriggers` / `RequiresAllConflictingTriggers`, and copied vtables in which only Apply
(`+0x28`) and Unapply (`+0x20`) differ. See
[object-image-upgrade.md](object-image-upgrade.md#implementation-notes) for the twin itself. The
sidecar, UI hooks and image lookups of that patch have no counterpart here.

| piece | what it is |
|---|---|
| `register` | replays the six arguments of the wrapped `addModule` call, then `addModule("GrantScienceUpgrade", 0x84, ...)` and `ret 0x18` |
| `runtime_factory` | Tooltip's runtime factory `0x006504C2`, then `UpgradeMux` (`+0x10`) repointed at the cave's vtable copy |
| `moduledata_factory` | `operator new(0x140)`, Tooltip's ctor `0x0065563C`, the cave's ModuleData vtable and `build_fields` |
| `build_fields` | the inherited `UpgradeModule` fields, then one row: `GrantScience`, the stock AsciiString parser, `+0x138` |
| `apply` | below |
| `unapply` | `ret`: a granted science stays granted |

**Storage costs nothing.** Tooltip's ModuleData already holds an engine `AsciiString` at `+0x138`
with a stock destructor, so the ModuleData does not grow. Its second `AsciiString`, at `+0x13C`,
stays empty; it is a string with a destructor too, so it is not spare room for anything else.

**Apply** (`ecx` = `UpgradeMux*`; `Object*` at `[mux-8]` and `ModuleData*` at `[mux-0xC]`), as
emitted:

```asm
push esi / push edi
mov  esi, ecx
mov  edi, [esi-8]            ; Object*
test edi, edi  / je done
mov  eax, [esi-0Ch]          ; ModuleData*
add  eax, 138h               ; &GrantScience
cmp  dword [eax], 0 / je done   ; no GrantScience line: empty AsciiString
push eax
mov  ecx, [0DE3B20h]         ; TheScienceStore
call 005FEF8Fh               ; friendlyNameToScience
cmp  eax, -1   / je done
mov  esi, eax                ; ScienceType
mov  ecx, edi
call 0068B678h               ; Object::getControllingPlayer
test eax, eax  / je done
push esi
mov  ecx, eax
call 006AE3A7h               ; Player::grantScience (IsGrantable + addScience)
done:
pop edi / pop esi / ret
```

The name is resolved when the module fires, not at parse time, as `doGrantScience` does and as Zero
Hour did. Resolving at parse time would mean a `ScienceType` in a slot with an AsciiString
destructor, so the ModuleData would have to grow. The cost of resolving late is that an unknown
name does nothing in game; `sage-lint` reports it instead, because `ini_surface` types
`GrantScience` as `Ref:sciences`.

## 3. Hook sites: composing with `object-image-upgrade`

`object-image-upgrade` owns `0x0065A7F2`, the `TooltipUpgrade` `addModule` call, and
`object-image-upgrade-wb` owns the editor's `0x00C75BBF`. The registration stub does not depend on
which stock module it wraps, because it replays the six arguments it displaces, so both halves wrap
the **next** call, `AudioLoopUpgrade`'s:

| binary | call | asserted before it |
|---|---|---|
| `game.dat` | `0x0065A82A` (`GRANT_SCIENCE_UPGRADE_REGISTER_CALL`), `e8 cf c8 ff ff` | `push 0x650532`, `push 0x6504FA`, `mov ecx, edi`, `mov [ebp-4], 0xD6` |
| `Worldbuilder.exe` | `0x00C75C24` (`WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL`), `e8 97 e0 01 00` | `push 0xC8B7A0`, `push 0xC8B730`, `mov ecx, [ebp-0x4E8]` |

The patches share callees (the Tooltip factories and ctor) but no edited bytes.

The editor half is parser-only: Tooltip's stock runtime factory and the editor's own ModuleData
ctor, field-table builder and AsciiString parser, with the EBP-framed `build_fields` that
[object-image-upgrade.md](object-image-upgrade.md#worldbuilder-registration) explains. Without it
Worldbuilder cannot parse the block and closes during its loading screen.

## 4. Behaviour

- **Grant once, never revoked.** Unapply is neutral, matching Zero Hour. Losing the upgrade or the
  object leaves the science with the player.
- **The recipient is the controlling player when the module fires.** Capturing the object later
  does not give the science to the capturer.
- **`IsGrantable = No` sciences are refused** silently, by the engine's own check.
- **Save games:** the science sits in `Player+0x310`, which the player already saves. The module's
  fired state is stock `UpgradeMux` state. Even a re-fire after loading is harmless, because
  `addScience` is idempotent.
- **Desync / replays:** none. Every player runs the same `game.dat`.

## 5. Not covered

- Zero Hour's other upgrade-science keywords. Only `GrantScience` exists.
- Lists (`GrantScience = A B`). Use two modules.
- Revoking on Unapply.

The registration skeleton is shared: it lives in
[`patches/utils/tooltip_twin.py`](../patches/utils/tooltip_twin.py), which this patch and
[`special-power-refund-upgrade`](special-power-refund-upgrade.md) are both built from.
`object-image-upgrade` still carries its own copy.

## 6. To check in a game

1. With `TriggeredBy` met, the science appears in the spellbook as bought, and powers gated on it
   become usable without a refresh. This is the module walk in `addScience`.
2. With `IsGrantable = No`, nothing is granted.
3. Two objects with the module, or a re-trigger: nothing doubles and nothing errors.
4. Save, reload: the science is still there and no second grant fires.
5. A skirmish AI owner gets the science too.
6. With an unknown `GrantScience` name, the game loads and the module does nothing.
7. Worldbuilder with `grant-science-upgrade-wb` loads a mod whose INI uses the block, and places
   the object.
