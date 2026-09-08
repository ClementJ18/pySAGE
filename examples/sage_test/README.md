# `sage_test` examples

System tests that run against the real engine. The library reference is
[`sage_test/README.md`](../../sage_test/README.md); this page is the runnable scripts.

Each script is one system test end to end — declare a scenario, compile it into a map, launch the
game on it, bind the declared objects to the live ones, assert. The `check`/`cast` functions are
what become `pytest` test bodies once the fixtures land; everything around them is the wiring
those fixtures will own.

## Prerequisites

- **A RotWK install**, passed with `--install`, holding `game.dat` and the `.big` archives.
- **`command-line-skirmish` on `game.dat`.** `-file` alone skips the menus but does not configure
  a match: the game starts with a random faction, no opponent and no starting resources, and dies
  before frame 1. `sage-patch apply command-line-skirmish --in game_original.dat --out game.dat`
- **`live-bridge` too, for anything that issues an order.** Reading needs only the first.
- **The binary named `game.dat`.** A section-modified image run under any other filename dies
  immediately inside `msvcr71.dll`, so a patched build cannot be copied aside and tried out.
- **An elevated shell** — the game runs as administrator, so reading its memory is refused
  otherwise.

Each script writes its map into `My Rise of the Witch-king Files\Maps`, and removes it again
unless `--keep` is passed.

## The scripts

| script | what it proves |
|---|---|
| [`experience_level.py`](experience_level.py) | `objectExperienceLevel` applies before frame one — two identical fighters, one declared at level 7, and the levelled one comes back with more health. Also the ownership binding, which is the half that silently hands objects to nobody when it is wrong. Needs no `live-bridge`. |
| [`edict_of_carn_dum.py`](edict_of_carn_dum.py) | A level 7 Mornamarth casts the Edict of Carn Dûm on a Hall of the King's Men, and the hall gains `Upgrade_RaiseShield`. Needs `live-bridge` to issue the cast; `--no-cast` runs the setup checks alone. |

## Reading the Edict example

It is worth reading `edict_of_carn_dum.py`'s docstring even if you never run it, because the
scenario is only three lines and the interesting part is *why* those three lines are what they
are. The ability is gated by `UnpauseSpecialPowerUpgrade … TriggeredBy = Upgrade_Level_7`, which
is why the hero is declared at level 7 **and** given `Upgrade_Level_7` explicitly — the level
property makes him level 7, but the module listens for the upgrade, and a scenario that sets only
the level produces a hero who looks right and whose ability is still paused.
