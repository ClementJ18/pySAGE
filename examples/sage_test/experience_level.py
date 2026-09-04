"""A system test against the real engine: does a declared experience level actually apply?

The claim under test is the one the whole `sage_test` scenario model rests on — that
`objectExperienceLevel`, an ordinary WorldBuilder object property, gives a placed unit its level
before frame one, so a test can start from "a level 7 hero next to a finished building" without
asking the engine to do anything a player could not.

Two `GondorFighter`s are placed side by side, identical but for the level. If the property works
the levelled one comes back with more health, and both are owned by the seat that declared them.
Both halves matter: the health difference proves the level applied, and the ownership proves the
`Player_<startPos + 1>` binding did — which is the part that silently hands objects to nobody
when it is wrong.

**Prerequisites**

- A RotWK install, passed with `--install`, holding `game.dat` and the `.big` archives.
- `game.dat` carrying **`command-line-skirmish`**: `-file` alone starts a game with a random
  faction and no opponent, and dies before frame 1.
  `sage-patch apply command-line-skirmish --in game_original.dat --out game.dat`
- The binary under the name `game.dat` — a section-modified image run under any other filename
  dies at once inside `msvcr71.dll`.

Run from the repo root:

    python examples/sage_test/experience_level.py --install C:\\RotWK

`check` is the part that becomes a `pytest` test body once the fixtures land; everything else is
the wiring those fixtures will own.
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
from sage_map import parse_map, write_map  # noqa: E402
from sage_test import Scenario, Seat  # noqa: E402
from sage_test.compile import compile_into  # noqa: E402
from sage_test.harness import Match, bind_handles  # noqa: E402
from sage_test.runner import install_map, launch  # noqa: E402

#: A shipped multiplayer map, used as the template a scenario is compiled onto. It brings the
#: terrain, the start positions and the castle plots; the scenario only adds objects.
TEMPLATE = "maps\\map mp harlindon\\map mp harlindon.map"

#: Faction indices into the loaded mod's `playertemplate.ini` order. These are Edain's.
MEN, MORDOR = 3, 10

#: Beside `Player_1_Start` (4340, 2423) on that map, far enough apart that the two placements
#: cannot bind to each other's object.
LEVELLED_AT = (4200.0, 2500.0, 0.0)
PLAIN_AT = (4260.0, 2500.0, 0.0)


def read_template(install: Path, name: str = TEMPLATE) -> bytes:
    """Pull a map straight out of the install's `.big` archives."""
    from pyBIG import InDiskArchive  # noqa: PLC0415 - optional dependency, only needed here

    for archive in sorted(install.glob("*.big")):
        try:
            big = InDiskArchive(str(archive))
        except Exception:  # noqa: BLE001 - a .big we cannot open is simply not the one
            continue
        entries = {entry.lower(): entry for entry in big.file_list()}
        if name in entries:
            return big.read_file(entries[name])
    raise SystemExit(f"{name} is not in any .big under {install}")


def build_scenario() -> tuple[Scenario, object, object]:
    """The declaration: two seats, and two fighters that differ only in their level."""
    scenario = Scenario(
        "sage_test_experience",
        seats=(
            Seat.human(faction=MEN, start_position=0),
            Seat.easy_ai(faction=MORDOR, start_position=1),
        ),
    )
    levelled = scenario.place("GondorFighter", at=LEVELLED_AT, level=7)
    plain = scenario.place("GondorFighter", at=PLAIN_AT)
    return scenario, levelled, plain


def check(match: Match, levelled, plain) -> list[str]:
    """The assertions. Returns the failures, so every one is reported rather than the first."""
    failures: list[str] = []
    local = match.session.observe().local_player

    for label, handle in (("levelled", levelled), ("plain", plain)):
        obj = match[handle]
        if obj.owner_index != local:
            failures.append(
                f"the {label} fighter is owned by player {obj.owner_index}, not the local "
                f"player {local} - the Player_<startPos + 1> binding did not take"
            )

    levelled_health = match[levelled].max_health
    plain_health = match[plain].max_health
    if not levelled_health > plain_health:
        failures.append(
            f"objectExperienceLevel did not apply: the level 7 fighter has {levelled_health} "
            f"max health and the plain one {plain_health}"
        )
    return failures


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True, help="the RotWK install folder")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for frame 1")
    parser.add_argument("--keep", action="store_true", help="leave the generated map on disk")
    args = parser.parse_args()

    game_dat = args.install / "game.dat"
    if not game_dat.is_file():
        raise SystemExit(f"no game.dat in {args.install}")

    scenario, levelled, plain = build_scenario()
    parsed = parse_map(io.BytesIO(read_template(args.install)))
    compile_into(scenario, parsed)
    # Uncompressed: the engine reads either, and compressing a five-megabyte map in pure Python
    # costs more than the launch it is meant to make faster.
    path, file_argument = install_map(scenario.name, write_map(parsed, compress=False))
    print(f"map      {path}")
    print(f"-file    {file_argument}")

    failures: list[str] = []
    process = launch(file_argument, game_dat)
    print(f"launched pid {process.pid}; waiting for frame 1")
    try:
        deadline = time.monotonic() + args.timeout
        while True:
            if process.returncode is not None:
                raise SystemExit(
                    f"the game exited (rc 0x{process.returncode & 0xFFFFFFFF:08X}) before the "
                    "match started - is command-line-skirmish applied?"
                )
            if time.monotonic() > deadline:
                raise SystemExit(f"no match after {args.timeout}s")
            try:
                with sage_live.attach(process.pid) as session:
                    if session.observe().frame >= 1:
                        match = Match(scenario, session, bind_handles(scenario, session.observe()))
                        print(f"frame {session.observe().frame}; handles bound")
                        failures = check(match, levelled, plain)
                        break
            except Exception:  # noqa: BLE001 - the game is still loading; keep waiting
                pass
            time.sleep(1.0)
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
