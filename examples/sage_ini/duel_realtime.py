"""A real-time duel: both units swing at once, then on their own attack cadence.

Unlike duel.py (strict alternation), here each unit attacks on a timeline driven
by its weapon's attack speed: ``AttackSpeed = FiringDuration + DelayBetweenShots``
(milliseconds). Both swing at t=0, then each again every `AttackSpeed` ms. Blows
that fall on the same instant resolve simultaneously (both land before deaths are
checked), so a same-tick mutual kill is a draw.

Run from the repo root:  .venv/Scripts/python examples/duel_realtime.py
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

EPS = 1e-6  # blows within this many ms count as the same instant


def load_game(root: Path) -> Game:
    game = Game()
    layers = (ini_root(root),)
    for path in root_files(root):
        game.load_document(parse_file(path, resolve_includes=True, include_layers=layers).document)
    return game


def max_health(obj) -> float:
    body = next((m for m in obj.modules if isinstance(m, Body)), None)
    return body.MaxHealth if body is not None else 0.0


def primary_weapon(obj):
    return obj.WeaponSet[0].Weapon[0][1]


def damage_per_hit(attacker, defender) -> float:
    weapon = primary_weapon(attacker)
    armor = defender.ArmorSet[0].Armor
    return sum(
        n.Damage * armor.get_damage_scalar(n.DamageType)
        for n in weapon.Nuggets
        if isinstance(n, DamageNugget)
    )


def duel(game: Game, name_a: str, name_b: str) -> str:
    units = {name: game.objects[name] for name in (name_a, name_b)}
    other = {name_a: name_b, name_b: name_a}

    hp = {n: max_health(o) for n, o in units.items()}
    dmg = {n: damage_per_hit(units[n], units[other[n]]) for n in units}
    interval = {n: primary_weapon(o).AttackSpeed for n, o in units.items()}
    next_at = {n: 0.0 for n in units}  # both swing at t=0

    for n in units:
        print(f"{n}: {hp[n]:.0f} HP, {dmg[n]:.0f}/hit every {interval[n]:.0f}ms")

    if dmg[name_a] <= 0 and dmg[name_b] <= 0:
        print("  neither can damage the other — stalemate.")
        return ""

    while hp[name_a] > 0 and hp[name_b] > 0:
        t = min(next_at.values())
        swinging = [n for n in units if abs(next_at[n] - t) < EPS]
        # simultaneous resolution: everyone on this tick lands before deaths apply
        for n in swinging:
            hp[other[n]] -= dmg[n]
        for n in swinging:
            next_at[n] += interval[n]
        for n in swinging:
            tgt = other[n]
            print(f"  t={t:6.0f}ms: {n} hits {tgt} -> {hp[tgt]:.0f} HP")

    dead = [n for n in units if hp[n] <= 0]
    if len(dead) == 2:
        print(f"  both fall at t={t:.0f}ms — draw.")
        return ""
    loser = dead[0]
    winner = other[loser]
    print(f"  {loser} dies first at t={t:.0f}ms; {winner} wins.")
    return winner


if __name__ == "__main__":
    game = load_game(Path("data"))
    duel(game, "MordorFighter", "GondorFighter")
