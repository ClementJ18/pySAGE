"""Walk a hero up its experience ranks and watch the engine state change.

Each `ExperienceLevel` whose `TargetNames` names the unit is a rung on its rank
ladder; reaching a rank grants that level's `Upgrades` and applies its
`AttributeModifiers`. Because the granted upgrades feed back into the upgrade
machinery, raising the rank also fires whatever armor/weapon/locomotor upgrades
those levels trigger — all of it resolved by `UnitState.set_rank`.

Run from the repo root:  .venv/Scripts/python examples/rank_levels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import sage_ini.model.definitions  # noqa: E402,F401  (registers the typed classes)
from sage_ini.model.game import Game  # noqa: E402
from sage_ini.model.state import UnitState  # noqa: E402
from sage_ini.parser.blockparser import parse_file  # noqa: E402
from sage_ini.stats import ini_root, root_files  # noqa: E402


def load_game(root: Path) -> Game:
    """Parse every root .ini under `root` into one Game so cross-refs resolve."""
    game = Game()
    layers = (ini_root(root),)
    for path in root_files(root):
        game.load_document(parse_file(path, resolve_includes=True, include_layers=layers).document)
    return game


def report(game: Game, name: str) -> None:
    obj = game.objects.get(name)
    if obj is None:
        print(f"{name}: not in corpus")
        return

    state = UnitState(obj)
    print(f"\n{name}  (ranks {state.min_rank:g}-{state.max_rank:g})")
    for rank in state.ranks.ranks:
        state.set_rank(rank)
        upgrades = sorted(state.ranks.current_level._fields.get("Upgrades", "").split())
        mods = [m.name for m in state.ranks.modifier_lists]
        health = state.max_health
        line = (
            f"  rank {rank:>2g}: health={health:g}" if health is not None else f"  rank {rank:>2g}:"
        )
        if upgrades:
            line += f"  +upgrades {' '.join(upgrades)}"
        if mods:
            line += f"  modifiers={len(mods)}"
        print(line)


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "data"
    if not root.exists():
        print("corpus not present (data/ is gitignored) — nothing to show")
        return
    game = load_game(root)
    for name in ("GondorGandalf", "MordorWitchKing", "MordorTavern"):
        report(game, name)


if __name__ == "__main__":
    main()
