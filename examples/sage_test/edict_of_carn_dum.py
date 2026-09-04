"""A system test for Mornamarth's Edict of Carn Dûm, against the real engine.

The scenario the whole `sage_test` model was designed around: **a level 7 Mornamarth and a Hall
of the King's Men, and does casting the Edict on the hall actually do what the data says.**

Reaching that state by playing would take ten minutes of a real match. Declared as a scenario it
costs one map: `objectExperienceLevel` and `objectUpgradesList` are ordinary WorldBuilder object
properties, so the hero starts at level 7 with the ability already unlocked and the hall is
already standing.

**What the mod data says should happen**, read out of `__edain_data.big`:

    Command_SpecialAbilityMorgomirEdikt  ->  SpecialAbilitySchergendesGrossorks
      unlocked by  UnpauseSpecialPowerUpgrade  TriggeredBy = Upgrade_Level_7   <- the level 7
      targeting    NEED_TARGET_POS, ObjectFilter  NONE +AngmarBarracks … ALLIES
      effect       OCLSpecialPower -> OCL_MorgomirEdikt -> MorgomirEdiktModifier
                   -> MorgomirEdiktModifierWeapon
                   -> AttributeModifierNugget, Radius 35, +AngmarBarracks ALLIES
      modifier     ModifierList MorgomirEdiktModifier: Duration 3000,
                   Upgrade = Upgrade_RaiseShield Delay:10

So the hall gains the object-scoped upgrade `Upgrade_RaiseShield`, and keeps it. Measured: the
power executes within a tenth of a second of the order, the upgrade appears on the hall at
**+3.0 s** — the `ModifierList`'s own `Duration` — and it is still there thirty seconds later.
`GameObject.upgrades` reads object-scoped upgrades, so that is directly assertable, and it is the
assertion.

The recharge is checked first, as a **precondition rather than the result**. A special power the
engine accepts goes onto its `ReloadTime`; if that clock has not moved, the order was discarded
and the upgrade was never going to appear, so failing on the recharge says *the cast did not
happen* instead of the far less useful *the upgrade did not show up*.

The cheaper recruits you notice in game are a second, separate mechanism - the hall's command set
offers `_Edikt` variants of its units, and those are their own templates with their own prices
(`AngmarDunedainPikemanHorde` costs 600, `AngmarDunedainPikemanHorde_Edikt` costs 450). This
script reports that from the ini rather than asserting it, because proving it in the running game
means recruiting one of each and diffing the treasury, which is a second test rather than a
footnote to this one.

**Prerequisites**

- A RotWK install with Edain, passed with `--install`.
- `game.dat` carrying **both** `command-line-skirmish` (to start the match at all) and
  **`live-bridge`** (to issue the cast). Ordering is what needs the bridge; the setup checks run
  without it, and `--no-cast` stops after them.
- An **elevated** shell: the game runs as administrator, so reading its memory is refused
  otherwise.

Run from the repo root:

    python examples/sage_test/edict_of_carn_dum.py --install C:\\RotWK
    python examples/sage_test/edict_of_carn_dum.py --install C:\\RotWK --no-cast
"""

from __future__ import annotations

import io
import shutil
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

import sage_live  # noqa: E402
from sage_live.api.session import CAST_LOCATION  # noqa: E402
from sage_map import parse_map, write_map  # noqa: E402
from sage_test import Scenario, Seat  # noqa: E402
from sage_test.compile import compile_into  # noqa: E402
from sage_test.harness import Match, bind_handles  # noqa: E402
from sage_test.runner import install_map, launch  # noqa: E402

TEMPLATE = "maps\\map mp harlindon\\map mp harlindon.map"

#: Indices into the loaded mod's `playertemplate.ini` order - Edain's.
ANGMAR, MORDOR = 12, 10

#: The power the Edict button fires, and the object-scoped upgrade it leaves on the hall.
EDICT_POWER = "SpecialAbilitySchergendesGrossorks"
EDICT_UPGRADE = "Upgrade_RaiseShield"

#: The upgrade lands at the end of the `ModifierList`'s `Duration = 3000`, measured at +3.0s.
#: The budget is generous over that because a slow frame rate stretches it.
EDICT_LANDS_WITHIN_S = 15.0

#: Beside `Player_1_Start` on the template map. The hall sits within the nugget's radius 35 of
#: the point the Edict is cast at, and the hero stands clear of it.
HERO_AT = (4180.0, 2500.0, 0.0)
HALL_AT = (4300.0, 2500.0, 0.0)


def read_template(install: Path, name: str = TEMPLATE) -> bytes:
    from pyBIG import InDiskArchive  # noqa: PLC0415 - optional dependency, only needed here

    for archive in sorted(install.glob("*.big")):
        try:
            big = InDiskArchive(str(archive))
        except Exception:  # noqa: BLE001 - a .big we cannot open is not the one
            continue
        entries = {entry.lower(): entry for entry in big.file_list()}
        if name in entries:
            return big.read_file(entries[name])
    raise SystemExit(f"{name} is not in any .big under {install}")


def build_scenario():
    """A level 7 Mornamarth, and a Hall of the King's Men to cast at.

    The level is declared twice on purpose. `objectExperienceLevel` is what makes the hero level
    7; `Upgrade_Level_7` is what the `UnpauseSpecialPowerUpgrade` module actually listens for, and
    shipped maps grant the level upgrades explicitly alongside the level for exactly this reason
    (`Moria.map` places a level 10 Gildor carrying `Upgrade_Level_1 … Upgrade_Level_10`). Without
    the upgrade the ability stays paused and the cast is silently discarded.
    """
    scenario = Scenario(
        "sage_test_edict",
        seats=(
            Seat.human(faction=ANGMAR, start_position=0),
            Seat.easy_ai(faction=MORDOR, start_position=1),
        ),
    )
    hero = scenario.place(
        "AngmarMorgramir",
        at=HERO_AT,
        level=7,
        upgrades=tuple(f"Upgrade_Level_{level}" for level in range(1, 8)),
    )
    hall = scenario.place("AngmarBarracks", at=HALL_AT)
    return scenario, hero, hall


def check_setup(match: Match, hero, hall) -> list[str]:
    """The scenario arrived as declared: both objects ours, and the hero actually levelled."""
    failures: list[str] = []
    local = match.session.observe().local_player
    for label, handle in (("Mornamarth", hero), ("the hall", hall)):
        owner = match[handle].owner_index
        if owner != local:
            failures.append(f"{label} is owned by player {owner}, not the local player {local}")

    held = {upgrade.lower() for upgrade in match[hero].upgrades}
    if "upgrade_level_7" not in held:
        failures.append(
            "Mornamarth does not hold Upgrade_Level_7, so the Edict is still paused - "
            f"object-scoped upgrades on him: {sorted(match[hero].upgrades)}"
        )
    return failures


def cast_edict(match: Match, hero, hall) -> list[str]:
    """Cast the Edict at the hall and wait for the upgrade it leaves behind.

    **The recharge is checked first, as a precondition rather than the result.** A power the
    engine accepts and executes goes onto its `ReloadTime`, and the caster's own module clock is
    what `power_cooldowns` reads. If that has not moved, the order was discarded and the upgrade
    was never coming - so failing here says *the cast did not happen*, which is far more useful
    than *the upgrade did not appear*.

    `Match.cast_and_confirm` retries rather than sleeping on a guess, because a cast is not
    reliably accepted the first time and the engine says nothing when it is not. How long it takes
    depends on how the game was started - about a second off the `.big` archives, several under
    `-mod`, where everything loads more slowly.
    """
    hero_id = match.id_of(hero)
    try:
        match.cast_and_confirm(
            EDICT_POWER, hero_id, form=CAST_LOCATION, position=match[hall].position
        )
    except TimeoutError as exc:
        return [str(exc)]

    def upgraded(current: Match) -> bool:
        return any(u.lower() == EDICT_UPGRADE.lower() for u in current[hall].upgrades)

    try:
        match.wait_until(upgraded, timeout=EDICT_LANDS_WITHIN_S, poll=0.1)
    except TimeoutError:
        return [
            f"the Edict fired but the hall never gained {EDICT_UPGRADE} within "
            f"{EDICT_LANDS_WITHIN_S}s - its upgrades: {sorted(match[hall].upgrades)}"
        ]
    return []


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True, help="the RotWK install folder")
    parser.add_argument("--no-cast", action="store_true", help="check the setup and stop")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for frame 1")
    parser.add_argument("--keep", action="store_true", help="leave the generated map on disk")
    args = parser.parse_args()

    game_dat = args.install / "game.dat"
    if not game_dat.is_file():
        raise SystemExit(f"no game.dat in {args.install}")

    scenario, hero, hall = build_scenario()
    parsed = parse_map(io.BytesIO(read_template(args.install)))
    compile_into(scenario, parsed)
    path, file_argument = install_map(scenario.name, write_map(parsed, compress=False))
    print(f"map    {path}")

    failures: list[str] = []
    process = launch(file_argument, game_dat)
    print(f"launched pid {process.pid}; waiting for frame 1")
    try:
        deadline = time.monotonic() + args.timeout
        session = None
        while session is None:
            if process.returncode is not None:
                raise SystemExit(
                    f"the game exited (rc 0x{process.returncode & 0xFFFFFFFF:08X}) before the "
                    "match started - is command-line-skirmish applied?"
                )
            if time.monotonic() > deadline:
                raise SystemExit(f"no match after {args.timeout}s")
            try:
                attached = sage_live.attach(process.pid, writable=not args.no_cast)
                if attached.observe().frame >= 1:
                    session = attached
                    break
                attached.close()
            except Exception:  # noqa: BLE001 - still loading, or the bridge is absent
                pass
            time.sleep(1.0)

        with session:
            match = Match(scenario, session, bind_handles(scenario, session.observe()))
            print("handles bound")
            failures += check_setup(match, hero, hall)
            if failures:
                print("  setup is wrong; not casting")
            elif not args.no_cast:
                failures += cast_edict(match, hero, hall)
    finally:
        process.kill()
        if not args.keep:
            shutil.rmtree(path.parent, ignore_errors=True)

    for failure in failures:
        print(f"  FAIL {failure}")
    print("PASS" if not failures else f"{len(failures)} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
