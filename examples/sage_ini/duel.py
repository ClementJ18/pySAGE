"""A turn-by-turn duel: who dies first, MordorFighter or GondorFighter?

Each unit's health is the `MaxHealth` of its body module (`ActiveBody`). The two
units trade single blows; each blow subtracts the attacker's per-hit damage
(weapon nuggets vs the defender's armor, see damage_calc.py) from the defender's
remaining health, until one drops to zero.

Run from the repo root:  .venv/Scripts/python examples/duel.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import sage_ini.model.definitions  # noqa: E402,F401  (registers the typed classes)
from sage_ini.model.behaviors import Body  # noqa: E402
from sage_ini.model.game import Game  # noqa: E402
from sage_ini.model.nuggets import DamageNugget  # noqa: E402
from sage_ini.parser.blockparser import parse_file  # noqa: E402
from sage_ini.stats import ini_root, root_files  # noqa: E402


def load_game(root: Path) -> Game:
    """Parse every root .ini under `root` into one Game so cross-refs resolve."""
    game = Game()
    layers = (ini_root(root),)
    for path in root_files(root):
        game.load_document(parse_file(path, resolve_includes=True, include_layers=layers).document)
    return game


def max_health(obj) -> float:
    """The unit's health: MaxHealth of its body module (ActiveBody, ...)."""
    body = next((m for m in obj.modules if isinstance(m, Body)), None)
    return body.MaxHealth if body is not None else 0.0


def damage_per_hit(attacker, defender) -> float:
    """Attacker's primary-weapon DamageNuggets applied to the defender's armor."""
    weapon = attacker.WeaponSet[0].Weapon[0][1]
    armor = defender.ArmorSet[0].Armor
    return sum(
        nugget.Damage * armor.get_damage_scalar(nugget.DamageType)
        for nugget in weapon.Nuggets
        if isinstance(nugget, DamageNugget)
    )


def duel(game: Game, name_a: str, name_b: str) -> str:
    """Trade blows (a strikes first) until one dies; return the winner's name."""
    a = game.objects[name_a]
    b = game.objects[name_b]

    hp = {name_a: max_health(a), name_b: max_health(b)}
    dmg = {name_a: damage_per_hit(a, b), name_b: damage_per_hit(b, a)}

    print(f"{name_a}: {hp[name_a]:.0f} HP, {dmg[name_a]:.0f}/hit")
    print(f"{name_b}: {hp[name_b]:.0f} HP, {dmg[name_b]:.0f}/hit")

    if dmg[name_a] <= 0 and dmg[name_b] <= 0:
        print("  neither can damage the other — stalemate.")
        return ""

    turn_order = [(name_a, name_b), (name_b, name_a)]
    blows = 0
    while hp[name_a] > 0 and hp[name_b] > 0:
        attacker, defender = turn_order[blows % 2]
        hp[defender] -= dmg[attacker]
        blows += 1
        print(f"  blow {blows}: {attacker} hits {defender} -> {hp[defender]:.0f} HP")

    loser = name_a if hp[name_a] <= 0 else name_b
    winner = name_b if loser == name_a else name_a
    print(f"  {loser} dies first after {blows} blows; {winner} wins.")
    return winner


if __name__ == "__main__":
    game = load_game(Path("data"))
    duel(game, "MordorFighter", "GondorFighter")
