# Reversible UpgradeModule removal

`upgrade-module-removal` fixes native OBJECT upgrade removal in RotWK
`2.01.2614.37001`. Behaviors with a removal implementation can reverse their effects
with `Permanent = No`. Omitted `Permanent` already defaults to `No`; the constructor
and Boolean parser are fingerprinted and left unchanged. `Permanent = Yes` keeps the
effect. PLAYER upgrades, upgrade source counting and AttributeModifiers are unchanged.

This patch is independently selectable. It also composes with
[experience-level-down](experience-level-down.md), including its optional
[XP bounds](experience-xp-cap.md). Modules with no removal implementation
do not acquire an artificial inverse.

```ini
Behavior = UnpauseSpecialPowerUpgrade ModuleTag_LevelAbility
    SpecialPowerTemplate = SpecialAbilityLevelPower
    TriggeredBy = Upgrade_LevelPower
    Permanent = No
End
```

The matching SpecialPower should start paused. To preserve its remaining recharge
on regrant, use the existing `ObeyRechageOnTrigger = Yes` parameter where appropriate
(the engine's parameter name includes this spelling);
the patch preserves the native grant behavior for either value.

## Native evidence and correction

The supplied original is `tools/BFME-FILES/game.dat.backup`. Addresses below are VAs,
mapped through the PE section table with `file_offset`.

At `0x00691478`, EBX receives the module's UpgradeMux interface from virtual slot
`+0x28`. Its event slot `+0x0C` calls `0x008D2901`, which delegates to `0x008D278A`.
An intersecting removal event returns true only for an active mux and clears its
`+4` execution byte. ModelCondition removal at `0x008D286F` remains native.

The dispatcher at `0x008D2688` subsequently calls the removal slot `+0x20` unless
the Permanent getter at `+0x1C` is true. `UnpauseSpecialPowerUpgrade`'s removal
handler at `0x008B9701` reads the execution byte again through `0x004986C4`.
It sees zero in the original binary and skips pausing the matching power.

The event detour restores active state before calling the dispatcher, then clears
it after return, including when Permanent skips removal. The original `POP ECX`
at `0x006914A6` still cleans the pushed argument. EBX and other callee-saved registers
retain the native ABI.

A simple restore/call/clear hook alone permits recursive removal while its callback
sees an active flag. Two small dispatcher detours use byte value `2` only while an
already-active handler is running. It remains nonzero to native Boolean getters.
The event check accepts state `1` only; nested events do not clear or remove the same
module again, and nested reset dispatches skip state `2`. The native setter clears
the state on return. No tracker field, object field, TLS, or persistent storage is added.

The reset caller `0x0068E083` is untouched. Inactive reset handlers still see zero;
active ones see a nonzero state, and Permanent still skips their inverse. The
dispatcher never unconditionally activates an inactive reset module.

The ordinary `SpecialPowerModuleInterface::isReady` at `0x00896C72` checks pause
count in its local-timer branch, but its `SharedSyncedTimer` branch bypasses that
check. A detour rejects nonzero local pause count before either branch. This fixes
native readiness rather than changing only button appearance. Native `pauseCountdown`
at `0x00896756` still owns pause counts, timestamps and cooldown shifting on resume.
Alternate SpecialPowerUpdate interfaces are not modified by this readiness hook.

## Hooks and validation

| Hook VA | Original bytes | Replacement |
| --- | --- | --- |
| `0x006914A0` | `53 E8 E2 11 24 00` | `JMP rel32` + `90` to event wrapper |
| `0x008D2688` | `56 8B 74 24 08` | `JMP rel32` to dispatcher guard |
| `0x008D2698` | `8B 06 8B CE FF 50 20` | `JMP rel32` + two `90` bytes to callback wrapper |
| `0x008D27D3` | `80 7E 04 00 74 08` | `80 7E 04 01 75 08` |
| `0x00896C72` | `56 8B F1 80 7E 18 00` | `JMP rel32` + two `90` bytes to readiness gate |

The `.uprem` cave is code-only and allocated with the existing allocator. Its
address and jump displacements depend on previously allocated sections. Full
native code windows, the real vtable `0x00C6EA50`, constructor and parser evidence
are checked before any mutation. Unknown bytes or a pre-existing `.uprem` reject
application. Verification checks the complete cave, every hook and preserved anchors.
The level-down verifier accepts only a completely verified companion patch.

Python 3.13 tests execute the native event, grant checks, TriggeredBy/conflict bit
tests, ModelCondition removal, dispatcher, UnpauseSpecialPowerUpgrade grant/removal,
pause/resume and readiness code in Unicorn. Engine services and allocations are
modeled. Tests cover explicit/omitted No, Yes, regrant, cooldown, shared timers,
multi-level loss, nested same-module removal/reset, inactive reset and a second
native status-removal handler (`0x008B955F`). Stack, callee-saved registers and x87
balance are asserted. Capstone decodes complete hooks and cave instructions.

## Applying and testing in RotWK

```sh
python -m sage_patch apply upgrade-module-removal --in game.dat --out game.dat
python -m sage_patch verify upgrade-module-removal game.dat
```

Use a copy of the original binary, or the combined sequence in
[experience-xp-cap](experience-xp-cap.md). Keep the original for restoration.

No in-game test was performed for this follow-up. In a test map, unlock a paused
power by an OBJECT upgrade, use the ability, remove the upgrade, attempt activation,
and regrant it. Repeat with omitted Permanent, explicit No and Yes, and with a
shared timer and an active cooldown. Check actual activation and remaining cooldown,
not only the button. Repeat with several lost levels and another reversible behavior.
Test save/load, replay and multiplayer with the same patched binary on all peers.

Callbacks that regrant their own upgrade while its inverse is still running retain
the native already-executed grant suppression; this patch does not reconcile such
self-regrant scripts or reconstruct sources. Custom irreversible side effects and
module destruction during callbacks need separate analysis. Alternate interfaces,
script paths that bypass readiness, and mod-specific activation gates require
in-game coverage; no general SpecialPower activation rewrite is claimed.
