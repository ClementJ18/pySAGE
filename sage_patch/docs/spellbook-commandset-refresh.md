# Persistent spellbook CommandSet refresh

**Status: stable for the supported scope below; runtime-verified in game.** The automatic patch
switches the permanently visible left spellbook bar both for a normal CommandSetUpgrade and for a
set built through `commandset-button-upgrade`'s new `CommandButtons` field. The added spells were
used successfully. It does **not** change the separately opened spellstore window.

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

## ABI, isolation and supported scope

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

The patch is graduated from experimental after successful normal play, a 20-minute online
multiplayer match, replay playback, repeated transitions between player 1, observer and player 2,
whole-CommandSet changes, individual CommandButton overlays and actual use of the added spells.
Repeated execution produced no visible slowdown or flicker. These runs exercise both important
arms: the stock rebuild for a changed Player and the added same-Player comparison.

The stable contract is deliberately narrow:

- It targets the original RotWK `game.dat` 2.01.2614.37001 identified above. Installation checks
  exact cache/helper fingerprints rather than only trusting the version string. Another executable
  version needs new reverse engineering rather than reused VAs.
- Every multiplayer peer must use an identical patched binary. The online test met that condition;
  mixed binaries are unsupported.
- The intended trigger is a permanently granted `PlayerUpgrade`. Revoking and regranting upgrades
  is not part of the supported gameplay contract, although the generated-code tests exercise the
  resulting pointer changes.
- Invalidation compares `CommandSet *` identity. Mutating one CommandSet allocation in place will
  not refresh the bar. `CommandSetUpgrade` and `commandset-button-upgrade` select or create distinct
  sets, so the supported paths satisfy this requirement.

Within an ordinary match the Player's SpellBookObject is expected to persist. The defensive null,
loss and recovery branches remain structurally and execution-tested for teardown, load or
reinitialization paths. `Player::getSpellBookObject` may initialize its cached ObjectID, but the
same-binary multiplayer and replay tests showed no divergence. A same-Player update still performs
up to three existing helper calls; extended repeated play showed no visible performance impact.
No concrete defect remains known within the supported scope.

## Verification and runtime coverage

The data-free tests execute the emitted cave against mocked engine calls (including volatile
register clobbers and stack cleanup), check the stock write/marking boundaries, reject changed
fingerprints without partial mutation, and verify detour/cave tamper detection. Full tests apply
and verify an in-memory copy of the clean backup, including both orders with
`commandset-button-upgrade`. The backup is never written.

The address audit decodes the actual rel32 calls, globals and vtable slots from that backup,
including the stock Apply/setter/UI chain. Tests pin the 75-byte emitted refresh code to the
runtime-tested version. Repeated-update execution tests cover upgrade/revoke, stable-pointer no-op,
loss/recovery of the Object and Player changes.

Runtime coverage now includes normal play, 20 minutes of online multiplayer with identical
binaries, CommandSet and individual CommandButton changes, successful activation of the added
spells, replay playback, repeated player/observer switching and extended repeated checks without
visible performance degradation. Save/load during an active match and mixed-binary multiplayer
remain unclaimed rather than release blockers for the supported scope.
