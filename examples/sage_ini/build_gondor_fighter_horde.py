"""Build a unit from scratch in Python: a GondorFighter horde, its members,
their weapon, and the command buttons that drive it.

`sage_ini`'s model is parse-driven — a typed `Object`/`Weapon`/`CommandButton`
is built from an AST `Block`, not from a constructor. So "creating a unit purely
from Python" means assembling the AST yourself and feeding it to the same two
public entry points the loader uses:

  * `print_document(doc)`  -> canonical .ini text (paste it into a mod)
  * `game.load_document(doc)` -> the typed, cross-referenced model (read fields back)

The two tiny helpers below (`attr`, `block`) hide the boilerplate of building
`Attribute`/`Block` nodes (every node carries a `Span`; for hand-built content a
single placeholder span is fine — spans only matter for diagnostics pointing at
real files).

Run from the repo root:  .venv/Scripts/python examples/build_gondor_fighter_horde.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import sage_ini.model.definitions  # noqa: E402,F401  (registers the typed classes)
from sage_ini.model.behaviors import HordeContain  # noqa: E402
from sage_ini.model.game import Game  # noqa: E402
from sage_ini.parser.ast import Attribute, BlankLine, Block, IniDocument  # noqa: E402
from sage_ini.parser.location import Span  # noqa: E402
from sage_ini.parser.printer import print_document  # noqa: E402

# Hand-built nodes need a span, but there is no source file behind them; one
# placeholder serves every node (spans only locate diagnostics in real files).
SPAN = Span("<python>", 1, 1)


def attr(key: str, value, *, equals: bool = True) -> Attribute:
    """An `Key = value` line (or a bare `Key value` line when equals=False)."""
    return Attribute(key=key, value=str(value), uses_equals=equals, span=SPAN)


def block(name: str, label: str | None, *children, equals: bool = False) -> Block:
    """A `Name Label ... End` block. Top-level definitions and bare sub-blocks use
    no `=` (the engine's definition form); module slots like `Behavior = ActiveBody`
    pass equals=True so the first label token is read as the module class."""
    return Block(
        name=name,
        label=label,
        uses_equals=equals,
        children=list(children),
        span=SPAN,
    )


# A Weapon whose damage payload is a nested DamageNugget (the `Nuggets` group on
# the Weapon class). Slash 50 SWORD_SLASH damage at melee range.
def gondor_fighter_sword() -> Block:
    return block(
        "Weapon",
        "GondorFighterSword",
        attr("AttackRange", 18.0),
        attr("MeleeWeapon", "Yes"),
        attr("DelayBetweenShots", 1000),
        attr("FiringDuration", 400),
        block(
            "DamageNugget",
            None,
            attr("Damage", 50),
            attr("Radius", 0.0),
            attr("DamageType", "SWORD_SLASH"),
            attr("DamageFXType", "SWORD_SLASH"),
            attr("DeathType", "NORMAL"),
        ),
    )


# Three buttons the horde's command set will reference by name.
def command_buttons() -> list[Block]:
    attack_move = block(
        "CommandButton",
        "Command_GondorFighterHordeAttackMove",
        attr("Command", "ATTACK_MOVE"),
        attr("ButtonImage", "BCAttackMove"),
        attr("TextLabel", "CONTROLBAR:AttackMove"),
        attr("ButtonBorderType", "ACTION"),
    )
    stop = block(
        "CommandButton",
        "Command_GondorFighterHordeStop",
        attr("Command", "STOP"),
        attr("ButtonImage", "BCStop"),
        attr("TextLabel", "CONTROLBAR:Stop"),
        attr("ButtonBorderType", "ACTION"),
    )
    toggle_formation = block(
        "CommandButton",
        "Command_GondorFighterHordeToggleFormation",
        attr("Command", "HORDE_TOGGLE_FORMATION"),
        attr("ButtonImage", "BCFormation"),
        attr("TextLabel", "CONTROLBAR:ToggleFormation"),
        attr("ButtonBorderType", "ACTION"),
    )
    return [attack_move, stop, toggle_formation]


# Numbered slots (`1 = ...`) map button positions to the CommandButton names above.
def command_set() -> Block:
    return block(
        "CommandSet",
        "GondorFighterHordeCommandSet",
        attr("1", "Command_GondorFighterHordeAttackMove"),
        attr("2", "Command_GondorFighterHordeStop"),
        attr("3", "Command_GondorFighterHordeToggleFormation"),
    )


# One soldier: kindof flags, a draw module, an active body, an armor set and a
# weapon set wiring slot PRIMARY to the weapon defined above.
def gondor_fighter() -> Block:
    return block(
        "Object",
        "GondorFighter",
        attr("Side", "Men"),
        attr("EditorSorting", "UNIT"),
        attr("BuildCost", 100),
        attr("BuildTime", 30),
        attr("VisionRange", 150),
        attr("KindOf", "SELECTABLE INFANTRY SCORE CAN_ATTACK ARMY_SUMMARY"),
        block(
            "Draw",
            "W3DScriptedModelDraw ModuleTag_Draw",
            attr("OkToChangeModelColor", "Yes"),
            equals=True,
        ),
        block(
            "Behavior",
            "ActiveBody ModuleTag_Body",
            attr("MaxHealth", 300),
            attr("InitialHealth", 300),
            equals=True,
        ),
        block(
            "ArmorSet",
            None,
            attr("Armor", "GondorFighterArmor"),
        ),
        block(
            "WeaponSet",
            None,
            attr("Weapon", "PRIMARY GondorFighterSword"),
        ),
    )


# The armor the member's ArmorSet points at (so the reference resolves).
def gondor_fighter_armor() -> Block:
    return block(
        "Armor",
        "GondorFighterArmor",
        attr("Armor", "DEFAULT 100%", equals=True),
        attr("Armor", "SWORD_SLASH 80%", equals=True),
    )


# The selectable unit the player actually trains: KIND HORDE, the command set
# above, and a HordeContain that spawns 8 GondorFighter members.
def gondor_fighter_horde() -> Block:
    return block(
        "Object",
        "GondorFighterHorde",
        attr("Side", "Men"),
        attr("EditorSorting", "UNIT"),
        attr("BuildCost", 300),
        attr("BuildTime", 30),
        attr("CommandSet", "GondorFighterHordeCommandSet"),
        attr("KindOf", "SELECTABLE CAN_ATTACK HORDE ARMY_SUMMARY"),
        block(
            "Behavior",
            "HordeContain ModuleTag_Horde",
            attr("Slots", 8),
            attr("InitialPayload", "GondorFighter 8"),
            attr("ObjectStatusOfContained", "UNSELECTABLE NO_COLLISIONS"),
            attr("RankInfo", "RankNumber:1 UnitType:GondorFighter Position:X:0 Y:0"),
            equals=True,
        ),
    )


def build_document() -> IniDocument:
    """Assemble every block into one document, blank-line separated for readability."""
    blocks: list = [
        gondor_fighter_sword(),
        *command_buttons(),
        command_set(),
        gondor_fighter_armor(),
        gondor_fighter(),
        gondor_fighter_horde(),
    ]
    children: list = []
    for index, blk in enumerate(blocks):
        if index:
            children.append(BlankLine(span=SPAN))
        children.append(blk)
    return IniDocument(file="<python>", children=children, span=SPAN)


def main() -> None:
    doc = build_document()

    # 1) Emit canonical .ini text — paste this straight into a mod's ini folder.
    print("=" * 70)
    print("GENERATED .INI")
    print("=" * 70)
    print(print_document(doc, align_equals=True))

    # 2) Load the very same AST into a typed Game and read fields back. This is the
    #    loader's own path (no reparse), so cross-references resolve.
    game = Game()
    game.load_document(doc)
    diagnostics = game.validate()

    print("=" * 70)
    print("TYPED READ-BACK")
    print("=" * 70)

    weapon = game.weapons["GondorFighterSword"]
    nugget = weapon.Nuggets[0]
    print(f"weapon {weapon.name}: range {weapon.AttackRange}, melee={weapon.MeleeWeapon}")
    print(f"  payload: {nugget.Damage} {nugget.DamageType.name} damage")

    member = game.objects["GondorFighter"]
    wielded = member.WeaponSet[0].Weapon[0][1]  # (slot, weapon) of the first set
    armor = member.ArmorSet[0].Armor
    print(f"member {member.name}: cost {member.BuildCost}, wields {wielded.name}")
    print(f"  armor {armor.name} vs SWORD_SLASH lets through {armor.damage_scalars()}")

    horde = game.objects["GondorFighterHorde"]
    kinds = " ".join(getattr(k, "name", str(k)) for k in horde.KindOf)
    print(f"horde {horde.name}: cost {horde.BuildCost}, KindOf [{kinds}]")
    contain = next(m for m in horde.modules if isinstance(m, HordeContain))
    for unit, count in contain.InitialPayload:
        unit_name = getattr(unit, "name", unit)
        print(f"  payload: {count} x {unit_name} (slots {contain.Slots})")

    cmd_set = game.commandsets["GondorFighterHordeCommandSet"]
    print(f"command set {cmd_set.name}:")
    for slot, button in sorted(cmd_set.CommandButtons.items()):
        print(f"  [{slot}] {button.name} -> Command {button.Command.name}")

    print(f"\nvalidation diagnostics: {len(list(diagnostics))}")
    for diag in diagnostics:
        print(f"  {diag}")


if __name__ == "__main__":
    main()
