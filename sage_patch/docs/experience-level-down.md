# Experience level-down

`experience-level-down` adds automatic unit/hero level-down after an actual reduction of
tracker XP in RotWK `2.01.2614.37001`. It retains the remaining XP, removes lost level
AttributeModifiers through the native Object removal function, and removes only OBJECT
upgrades through the native upgrade removal path. PLAYER upgrades are untouched.

This is independently selectable. To let a `LevelGrantSpecialPower` supply negative XP,
also apply [level-grant-special-power-negative-experience](level-grant-special-power-negative-experience.md).
That patch remains a separate one-byte change; it is not duplicated here.

```sh
python -m sage_patch apply level-grant-special-power-negative-experience --in tools/BFME-FILES/game.dat.backup --out game.dat
python -m sage_patch apply experience-level-down --in game.dat --out game.dat
python -m sage_patch verify experience-level-down game.dat
python -m sage_patch verify level-grant-special-power-negative-experience game.dat
```

Python callers can use `ExperienceLevelDownPatch()` and
`LevelGrantSpecialPowerNegativeExperiencePatch()` in an `apply_patches` list, in either order.
No INI fields, experience sinks or persistent tracker fields are added.

## Binary evidence and hooks

The supplied `tools/BFME-FILES/game.dat.backup` is 11,346,944 bytes, ImageBase `0x00400000`.
Every address is a VA mapped with `file_offset`, never assumed to be a file offset.
The patch fingerprints all edited instruction windows, the stock upward cascade, collection
lookup/resolution/mode helpers, native effect-removal functions, queue processing/enqueueing,
the object level-change handler and its virtual slot at `0x00C3149C`.
Unknown layouts fail before allocating or modifying the image. A `.xpdown` section already
present rejects reapplication. Verification checks the entire cave, hooks and untouched anchors.

| Hook VA | Original bytes | Replacement on the supplied clean image |
| --- | --- | --- |
| `0x0079D69E` | `8B 41 28 3B C2 7E 05 39 41 24 7D 52` | twelve `90` bytes |
| `0x0079D6E6` | `F3 0F 10 49 10 FF 75 14 F3 0F 58 C8 F3 0F 11 49 10 E8 45 FA FF FF` | `E9 15 59 73 00` + seventeen `90` bytes |
| `0x0079D929` | `F3 0F 11 46 10 50 E8 0D F8 FF FF` | `E9 46 57 73 00` + six `90` bytes |
| `0x008215A2` | `8A 46 10 8B CD 50 53 FF 76 0C E8 68 FD FF FF` | `E9 E7 1D 6B 00` + ten `90` bytes |
| `0x0082134D` | `8B 46 34 2B 46 30` | `E9 63 20 6B 00 90` |
| `0x00821375` | `8B 46 50 2B 46 4C` | `E9 58 20 6B 00 90` |

Those jump displacements describe the 1,007-byte cave at VA `0x00ED3000` when these two patches
alone are applied to the supplied original. `allocate_section` computes the actual location
after any other patches; the jump bytes are regenerated accordingly. All hooks replace whole
instructions of the same total length. `.xpdown` is code-only, executable/readable, with no
runtime writes into the section.

The early maximum-rank rejection is moved to the XP addition window, after the stock SSE
multipliers and x87 adjustment. The rounded new float is compared with the old float using
an ordered comparison. Actual decreases bypass the maximum-rank rejection; unchanged or
increased XP retains the stock rejection. This also handles inverted multipliers and deltas
too small to change the stored float. NaN is not treated as a decrease. `xmm2` is saved/restored
and the cave does not change the x87 stack. Trainability and ExperienceSink routing stay native.

The absolute XP setter's store/check window similarly distinguishes a real decrease from
equal/increased XP. `0x0079D141` itself is untouched: positive XP, explicit level grants and
`LevelUpUpgrade` still use the native upward cascade and virtual handler. There is no global
"XP and rank disagree" trigger. `0x0079D76D`, the explicit XP-resetting level setter, is not
called by the automatic downward path.

## Selecting and removing levels

The downward helper accepts `this = tracker` and the stock feedback argument (`ret 4`),
preserves EBX/ESI/EDI/EBP and checks that virtual slot `+0x10` is the Object handler at
`0x0079DA9D`. Other tracker subclasses retain their stock level check.

The native lookup at `0x0068931C` obtains the tracker collection. Its sentinel is `*collection`,
its next pointer is `node+0`, and the effective record is obtained by passing `node+8` to
`0x00688D3C`. The chained resolver at `0x00465AF4` follows `+4`. The mode predicate at
`0x00688DB0` receives the record in **ESI**, as the native next-level finder does. It tests
`+0x101` in multiplayer and `+0x102` in singleplayer.

XP comparison follows the native integer threshold convention (`CVTTSS2SI`, truncation),
with a guard preventing positive float overflow from being mistaken for negative XP.
If XP still meets the current record's threshold, the native cascade is used unchanged.
Otherwise, selection takes the greatest allowed `RequiredExperience <= XP`, with higher rank
breaking equal-threshold ties and collection order breaking exact ties. Candidates above the
original rank are excluded. Below every threshold, the lowest threshold/lowest rank is the
fallback. If no allowed record/collection/current key exists, XP is retained and the level
stays unchanged. Normal definitions should have one effective record per rank and increasing
thresholds; same-rank aliases are processed once in collection order.

Lost ranks are processed from highest to lowest. The record layout is confirmed by the native
grant routine at `0x00821319`: modifiers are four-byte Utf8String entries at `+0x30/+0x34`,
upgrades are four-byte template pointers at `+0x4C/+0x50`, threshold is `+0x18` and rank is `+0xFC`.

* `0x0068F259`: `ECX = Object*`, stack argument is the **address of the modifier string element**,
  `ret 4`. This is the native inverse of `0x0068F1A8`, not a manual modifier-vector edit.
* `0x00691438`: `ECX = Object*`, argument is `UpgradeTemplate*`, `ret 4`. The Lua dispatch at
  `0x00736E87` confirms `template+4 == 0` is PLAYER and nonzero is OBJECT. Only the latter is
  removed. Its `+0x38` bit is tested first so duplicate lost definitions cause one removal.
  An OBJECT upgrade is removed even if another source also granted it; no source counting is
  added, and the Player removal function `0x006AE60C` is never called.

The native upgrade removal clears `Object+0x28C` and visits upgrade interfaces obtained through
module virtual slot `+0x28`. Matching modules go through `0x008D2688`, which tests slot `+0x1C`,
calls removal slot `+0x20` and clears activation through slot `+0x24`. Tests execute that native
bit-clearing/notification path with a synthetic module. Concrete SpecialPower behavior and
command-button availability still require in-game confirmation: this is not evidence that
every upgrade-triggered behavior implements a reversible removal handler.

## Delayed grants and level state

The system at `[0x00DE8AC0]` owns the queue at `+0x10`. Nodes have next/previous pointers at
`+0/+4`, ObjectHandle at `+8`, level pointer at `+0x0C` and feedback flag at `+0x10`, as confirmed
by `0x00821567` and `0x008215C2`.

Before removing effects, the helper cancels queued grants for this object's handle with rank
`targetRank < grantRank <= oldRank` by clearing their level pointer. The queue hook skips those
cancelled nodes; native iteration and clearing still own their lifetime. Other objects and
valid intermediate levels remain untouched. Cancelled grants cannot return if the unit ascends
again before queue processing; fresh grants for those levels are independent nodes.
The queue passes its node as a private fourth stack argument to the native grant body,
and removes that extra argument after the native `ret 12`. The stock grant reads its original
three arguments at EBP `+8/+0x0C/+0x10`; the fourth is at `+0x14`. Binary inspection found one
direct caller (`0x008215AC`) and no stored pointers to this body. Hooks after each native
modifier/upgrade callback check the node again. If a nested XP reduction has cancelled the
currently executing grant, they jump to its native SEH epilogue at `0x0082146D`, preventing
the rest of its lost effects from being reapplied. Valid intermediate grants still continue.

The state-only wrapper reproduces the handler's saved ESI/EDI frame and enters at `0x0079DAB8`,
after enqueueing. The remainder of the native handler updates the Drawable, name/key and rank
without touching XP or regranting the lower level's existing effects. Its existing ancillary
notifications remain native. No manual health/damage recalculation or unrelated ability reset
is introduced.

## Validation and limits

Python 3.13 tests execute the generated x86, anchored native addition/setter/upward cascade,
state handler and queue processor in Unicorn. Engine services and most effect storage are
modeled; a separate test executes the actual native OBJECT-upgrade removal/module dispatcher.
Coverage includes single/multiple/no level loss, maximum rank and effective multipliers,
signed/fractional/overflow XP, reascending, delayed intermediate/cancelled grants, mode
filtering, equal thresholds, empty collections, duplicate upgrades, PLAYER preservation,
explicit grants, stack/register/x87 contracts, fingerprint rejection and reapplication.
Capstone decodes the cave and displaced instruction windows. Real-binary tests apply and
verify both patches in both orders and confirm the supplied original is unchanged.

No in-game tests have been performed. Actual modifier effects on combat/health, concrete
SpecialPower removal, script and `LevelUpUpgrade` interactions, reentrant module callbacks,
and save/replay/multiplayer behavior must be tested in RotWK. The patch does not reconstruct
which source granted an effect or undo irreversible work done by an upgrade's module.
