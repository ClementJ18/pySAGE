# Build — `CommandSet` limit → 64 (ROTWK `game.dat` 2.01.2614)

Reproducible binary patch built on the RE in
[`../docs/commandset-button-limit.md`](../docs/commandset-button-limit.md). Applied and
**runtime-verified in-game**: the build loads `CommandSet` blocks up to 64 entries and
multi-select is stable. See
[`../docs/push-visible-command-range.md`](../docs/push-visible-command-range.md) for the paging
rule you must follow when surfacing buttons past 33.

## What it does

Raises `MAX_COMMANDS_PER_COMMAND_SET` from 33 to **64** (the shipped limit; `CommandSetLimitPatch`
takes any N in 34..127) so a `CommandSet` INI block may define `1`..`64` without the
`"Error parsing field '34'…"` load abort, and so the extra buttons are stored.

- **Grow the object** (14 edits): grows `CommandSet` from `0xA0` to `0x11C`; `m_command[64]` stays
  at `+0x14`; the count/flag fields move `0x98/0x9c → 0x114/0x118`.
- **Relocate the field table**: adds a `.cmdext` PE section (VA `0xed3000` on a clean image — the
  RVA is computed, so it lands past any cave another patch already added) holding a fresh 64-slot
  field-parse table + the new `"34".."64"` name strings, and repoints the two references
  (`0x72065c`, `0x71c2ee`).
- **Widen the AI's set-walk** (1 edit): `BuildAssistant::canMakeUnit`'s bound at `0x7950e2`,
  `cmp [ebp-8], 33 → 64`. That loop reads buttons rather than populating a UI array, so unlike the
  draw loops it can be widened — and left at 33 the AI would be blind to exactly the buttons this
  patch newly allows.

The patch stops there deliberately: it lifts only the *data* limit. Widening the
`getCommandButton`-caller **draw** loops would overrun the ControlBar's **fixed 33-slot UI
arrays** (`ControlBar +0xdc / +0x160`) and crash — so >33 *on screen* is a separate ControlBar/UI
project, and you page with `PUSH_VISIBLE_COMMAND_RANGE` in the meantime. Every edit verifies its
expected original bytes before writing.

## Build

```sh
# from this directory; needs: pip install capstone pefile
# game.dat.backup is the clean 2.01.2614 original — ALWAYS patch from it.
OUT=game.dat python patch.py   # -> ./game.dat  (COUNT=N for a limit other than 64)
python verify.py               # re-disassembles every edit + dumps the 64-slot table
python finalcheck.py           # pefile sanity check
```

`patch.py` always reads `game.dat.backup` and writes `$OUT` (default `patched.dat`).

## Install & test

1. **Back up** the original: `game.dat → game.dat.orig`.
2. Replace the game's `game.dat` with this folder's `game.dat` and launch.
   - Confirmed: no immediate anti-tamper failure on this 2.01.2614 build.
3. **Functional test.** A `CommandSet` with 34–64 entries loads **without**
   `"Error parsing field '34'…"`; multi-select is stable.
4. **Paging.** Only 33 buttons draw at once. To reach entries past 33, page with a
   `PUSH_VISIBLE_COMMAND_RANGE` button — see [`../docs/push-visible-command-range.md`](../docs/push-visible-command-range.md).
   The hard rule: `CommandRangeStart + CommandRangeCount ≤ 64`, or you read off the end of the
   array (slot 64 = the count field) and crash.

## Caveats / known risks

- **Multiplayer & replays:** the patched exe differs from vanilla; expect version-hash mismatch
  and lockstep desync against unpatched peers, and old replays may not play. Test MP only
  between identically-patched clients.
- **Pool bucket:** the `0x11C` object goes through the SAGE DMA allocator; verify no heap issues
  over a long session.
- **33-button display ceiling remains.** The patch lifts only the *data* limit (a set may define
  up to 64). The ControlBar still shows 33 at a time — page with `PUSH_VISIBLE_COMMAND_RANGE`.

## Files

| file | purpose |
|------|---------|
| `game.dat.backup` | clean 2.01.2614 original — the patch **input** (do not edit) |
| `game.dat` | the shipped build (N=64), patch **output** |
| `patch.py` | thin CLI over the [patching framework](../README.md#the-patch-framework); runs `CommandSetLimitPatch` from `game.dat.backup` |
| `verify.py` | static verification: instructions + table dump |
| `finalcheck.py` | pefile validity check |
| `dump.py` | minidump (`.dmp`) parser — faulting EIP/regs + game.dat-relative stack walk |
