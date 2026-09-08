"""A system-test harness for BFME2 / RotWK: declare a match, run it, assert on what happened.

The shape mirrors `sage_live` - one package per kind of conversation with the engine - and the
pipeline is one direction:

    Scenario  ->  a generated .map  ->  a launched game  ->  a live Session to assert against
    scenario.py   compile.py           runner.py            harness.py

Only `scenario` is import-free: it needs no game data, no `sage_map` and no Windows, so a test's
declaration can be built and checked anywhere. Everything downstream needs progressively more -
`compile` needs `sage_map`, `runner` needs an install, `harness` needs a running game.

`maps` sits beside `scenario` rather than in that chain: it reads the engine's own map cache to
say which maps can be started and how to spell them, and needs nothing but the file. A suite that
launches every shipped map parametrizes over it at collection time, which is why it is out here
and not behind an install.
"""

from __future__ import annotations

from sage_test.maps import MapEntry, load_map_cache, read_map_cache
from sage_test.scenario import Handle, Placement, Scenario, Seat

__all__ = [
    "Handle",
    "MapEntry",
    "Placement",
    "Scenario",
    "Seat",
    "load_map_cache",
    "read_map_cache",
]
