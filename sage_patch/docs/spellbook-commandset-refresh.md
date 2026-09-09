# Persistent spellbook CommandSet refresh

**Status: experimental; core function runtime-verified in game.** The automatic patch switched
the permanently visible left spellbook bar both for a normal CommandSetUpgrade and for a set built through
`commandset-button-upgrade`'s new `CommandButtons` field. It does **not** change the separately
opened spellstore window.

## Diagnosis and binary identity

Before the patch, the user observed that CommandSetUpgrade set the name at `Object+0x43C`, that
`Object::getCommandSetString` returned it, and that `CommandSetStore::findCommandSet` found the new
set. The UI nevertheless retained its cached `CommandSet *`. Setting its saved Player pointer at
`UI+0x28` to zero once triggered stock rebuilding, visibly adopting the new set. That is the live
evidence for cache invalidation. The subsequent automatic-patch test confirmed the fix.

All addresses here belong to **game.dat**, version 2.01.2614.37001 (the resource displays
2.1.2614.37001), preferred ImageBase `0x00400000`. The clean local backup was rechecked at
`tools/BFME-FILES/game.dat.backup`: 11,346,944 bytes, SHA-256
`948bac5ed89e33c605ac8b7e5c901e4b2554d953bc35b4ca3be4d7ff7c46cbd8`.
WorldBuilder's `0x0124...` Apply and `0x022...` globals must not be used in these game patches.
This game.dat has no relocation directory and does not request DYNAMIC_BASE. The patch uses the
PE section mapping and dynamically allocated cave; no runtime heap address or CE address is used.

## Stock cache and the five-byte hook

The cache function starts at `0x00930F96`. Its existing game-state and Player-validity checks run
first. At `0x00930FDE`, ESI is the UI and EDI the selected, validated Player (or null):

```asm
00930FDE  cmp edi,[esi+28]   ; 3B 7E 28
00930FE1  je 00931038        ; 74 55
```

Those five bytes become a `jmp rel32` to read-only cave `.sbcsref`. The cave handles:

- Different Player: jump to untouched `0x00930FE3` (stock clears the set, saves the Player and
  retains its null checks and lookup).
- Same null Player: keep the stock early return.
- Same non-null Player: call `Player::getSpellBookObject` (`0x006AD0F8`), then, if present,
  `Object::getCommandSetString` (`0x0069156B`) and `CommandSetStore::findCommandSet` (`0x0071EFA2`)
  with `this = [THE_COMMAND_SET_STORE]` (`0x00DE7744`). A missing Object resolves to a null set.
- Same resolved pointer as `[ESI+0x2C]`: return through stock `0x00931038`, without marking buttons.
- Different pointer, including loss/reappearance of a set: EAX carries it into stock `0x0093100C`.
  The existing code stores `[ESI+0x2C]` and sets exactly bytes `UI+0x30` through `UI+0x50` to 1.

This is a pointer comparison, not an unconditional rebuild. Each active same-player check adds
up to three existing helper calls. In-place edits of an unchanged CommandSet pointer are outside
this patch's invalidation criterion. The lookup uses the original global invariant; it does not
invent a null-store path that stock code lacks.

Update `0x009312B9` calls the cache function at `0x00931318`; at `0x0093134A` it loads the saved
set and at `0x00931351` calls `CommandSet::getCommandButton` (`0x0080C837`). The complete cache
function, both caller windows and helper ABI windows are fingerprinted before any allocation.
Verify checks the same untouched bytes, exact detour and exact cave. The public Object getter
may be detoured by another patch; its original call target, not an immutable prologue, is pinned.

## ABI, isolation and residual risks

The hook is a JMP, not a CALL. No extra stack frame is introduced. ESI/EDI remain callee-saved
across the three helpers; the first two take no stack arguments and the lookup consumes its one
argument with `ret 4`. The shared stock epilogue restores EDI/ESI. EAX/ECX/EDX and flags are
volatile. The marking entry specifically expects EAX to hold the resolved set.

The stock CommandSetUpgrade Apply, including its two post-set selection calls at `0x008B7C87`, is
untouched. The former diagnostic Drawable guard had no confirmed effect and has been removed.
No UpgradeMux conditions, science ownership, SpecialPower modules, releaseBuffer,
UnUpgrade/re-evaluation cycle, or spellstore are modified. The transient cleared override
observed during normal re-evaluation is not patched out. `THE_IN_GAME_UI` keeps its existing
meaning and address.

The successful cases establish the core purpose, but do not yet justify graduation under the
repository's deliberately conservative definition: the patch changes a regularly invoked path
and the lifecycle and multiplayer cases below have not run in game. It changes only five stock
bytes, has exact whole-function and helper-ABI fingerprints, reuses the stock rebuild path, and
has no INI or persistent-data format. Remaining risks do not currently indicate a concrete
defect, but bound what has and has not been demonstrated:

- It compares `CommandSet *` identity. Mutating the contents of the same set in place will not
  invalidate the bar; `commandset-button-upgrade` creates/chooses distinct sets for different
  overlay combinations, which is why the tested composition is covered.
- A same-Player update performs up to three extra existing calls. This is client UI work, but a
  very large increase in UI update frequency has not been profiled over long sessions.
- Loss of a SpellBookObject or a failed set lookup changes the cached pointer to null through the
  stock path. The null and recovery paths are structurally and execution-tested, but were not
  among the reported in-game cases.
- `Player::getSpellBookObject` can initialize its own cached ObjectID. Stock already calls it on
  Player changes, but this patch can call it on same-Player updates too. Tests preserve its ABI;
  they cannot prove that this extra cache initialization is irrelevant to every synced-state path.
- The engine's observer, save/load, reconnect, multiplayer and replay machinery is not modified.
  Tests exercise the cache's Player/null branches, not those end-to-end lifecycles; none of these
  sessions was part of the reported playtest.
- The reference build has the SHA-256 above. Installation checks exact cache/helper fingerprints,
  not the whole-file hash, so other patches on disjoint bytes can compose. Another executable
  version needs new reverse engineering rather than reused VAs.

## Verification and remaining in-game coverage

The data-free tests execute the emitted cave against mocked engine calls (including volatile
register clobbers and stack cleanup), check the stock write/marking boundaries, reject changed
fingerprints without partial mutation, and verify detour/cave tamper detection. Full tests apply
and verify an in-memory copy of the clean backup, including both orders with
`commandset-button-upgrade`. The backup is never written.

The address audit decodes the actual rel32 calls, globals and vtable slots from that backup,
including the stock Apply/setter/UI chain. Tests pin the 75-byte emitted refresh code to the
in-game-tested version. Repeated-update execution tests cover upgrade/revoke, stable-pointer
no-op, loss/recovery of the Object and Player changes. None substitutes for a multiplayer or
save/load session.

To remove an already installed diagnostic guard, regenerate the patched game.dat from this clean
backup with the updated patch list. Deleting its Python module does not undo a detour in an
existing binary. No installed game.dat is modified as part of this source-code cleanup.

The core visible result is established. Useful follow-up coverage is still to revoke/regrant,
change Player/observer context, save/load, replay and leave the set unchanged through a long
session while watching for repeated rebuilding or flicker. Until a mixed-binary multiplayer test
shows otherwise, use the same patched binary on every peer; presentation-only intent is not enough
to dismiss the helper's internal cache write without runtime evidence.
