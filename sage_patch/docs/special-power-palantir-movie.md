# SpecialPower PalantirMovie

`special-power-palantir-movie` enables the existing `PalantirMovie` field on two
previously silent paths in RotWK `2.01.2614.37001`:

- Direct SpecialPower starters with no matching SpecialPowerUpdate interface,
  provided `UpdateModuleStartsAttack = No`.
- Successful `PlayerUpgradeSpecialPower` activations, after the native upgrade
  checks and grants and immediately before the native trigger.

Existing update-driven movie requests retain their native timing and execute once.
No INI changes are needed; configure `PalantirMovie` in the `SpecialPower` as usual.
Empty names and an absent client singleton do nothing. Final template overrides
are respected. The native movie backend and its status/asset checks still decide
whether a requested movie is displayed.

The two hooks are `0x00897FA0` (six-byte no-update branch) and `0x008CC165`
(five-byte PlayerUpgrade trigger call). The first preserves the matched-update
branch and skips the existing FX/voice block after the added movie. The second
tail-calls `0x00897987` with the original `this`, return address and NULL argument.
Only these eleven existing code bytes and the PE headers are changed; the
relocatable code lives in `.spmovie`.

The movie helper borrows the final template's string for the synchronous request;
the native client copies it before returning. It preserves all general registers,
flags, x87/SSE state and MXCSR. No additional owned strings, save state or gameplay
state are introduced. Engine addresses and fingerprints are centralized in
`addresses/player.py`; apply checks before mutation, and verify checks the complete
generated code, both hooks and all unchanged anchors.

This patch does not change `InitiateAtLocationSound`, `InitiateSound`, InitiateFX,
unit voices, targets, cooldowns or update scheduling. StartsAttack=Yes with no
matching update receives no fallback movie. Other specialized powers that bypass
the starter are outside this patch's scope.

```bash
python -m sage_patch apply special-power-palantir-movie --in game.dat.backup --out game-movie.dat
python -m sage_patch verify special-power-palantir-movie game-movie.dat
```

Tests execute the generated helper and the patched original starter/PlayerUpgrade
routines against mocked engine services, including empty configuration, template
overrides, StartsAttack, disabled objects, invalid upgrades, ordering, no duplicate
requests, and preserved caller state. Applying and verifying alongside `hero-mana`
and `special-power-music` works in both orders. The original audio routine changes
only at the music patch's own hook. Actual movie playback has not been tested in game.

See [special-power-presentation-research.md](special-power-presentation-research.md)
for the source investigation, binary identity and exact original control flow.
