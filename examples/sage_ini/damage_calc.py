"""How much damage does MordorFighter do to GondorFighter per hit?

Loads the base game, takes the attacker's weapon (the nuggets on its primary
weapon) and applies each DamageNugget to the defender's armor: the damage dealt
for a nugget is `nugget.Damage * armor.get_damage_scalar(nugget.DamageType)`.

Run from the repo root:  .venv/Scripts/python examples/damage_calc.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import sage_ini.model.definitions  # noqa: E402,F401  (registers the typed classes)
from sage_ini.model.game import Game
from sage_ini.model.nuggets import DamageNugget
from sage_ini.parser.blockparser import parse_file
from sage_ini.stats import ini_root, root_files


def load_game(root: Path) -> Game:
    """Parse every root .ini under `root` into one Game so cross-refs resolve."""
    game = Game()
    layers = (ini_root(root),)
    for path in root_files(root):
        result = parse_file(path, resolve_includes=True, include_layers=layers)
        game.load_document(result.document)
    return game


def damage_between(game: Game, attacker_name: str, defender_name: str) -> float:
    attacker = game.objects[attacker_name]
    defender = game.objects[defender_name]

    # primary weapon of the attacker's first weapon set: Weapon is a list of
    # (slot, weapon) pairs, so [0][1] is the weapon of the first entry.
    weapon = attacker.WeaponSet[0].Weapon[0][1]
    armor = defender.ArmorSet[0].Armor

    total = 0.0
    print(f"{attacker_name} ({weapon.name}) vs {defender_name} ({armor.name}):")
    for nugget in weapon.Nuggets:
        if isinstance(nugget, DamageNugget):
            scalar = armor.get_damage_scalar(nugget.DamageType)
            dealt = nugget.Damage * scalar
            total += dealt
            print(f"  {nugget.DamageType.name:10} {nugget.Damage} x {scalar} = {dealt}")
    print(f"  total per hit: {total}")
    return total


if __name__ == "__main__":
    game = load_game(Path("data"))
    damage_between(game, "MordorFighter", "GondorFighter")
