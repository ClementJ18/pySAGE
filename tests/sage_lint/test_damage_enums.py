"""Damage type, subtype and FX names are three separate engine tables, and the linter has to tell
them apart: each of the tokens below once passed lint and then stopped the game at load
("Token '...' is not a valid member of the index list")."""

from pathlib import Path

from sage_lint.linter import lint_folder


def _lint(tmp_path: Path, text: str) -> list[str]:
    path = tmp_path / "data/ini/test.ini"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return [str(d) for d in lint_folder(tmp_path).items if d.span.file.endswith("test.ini")]


def _weapon(sub_type: str) -> str:
    return (
        "Weapon TagWeapon\n"
        "    DamageNugget\n"
        "        Damage        = 1.0\n"
        "        DamageType    = UNRESISTABLE\n"
        f"        DamageSubType = {sub_type}\n"
        "    End\n"
        "End\n"
    )


def test_a_damage_fx_name_is_not_a_subtype(tmp_path):
    """`FLOOD_HORSE` is a `DamageFXType`; the subtype table holds four names."""
    assert any("FLOOD_HORSE" in line for line in _lint(tmp_path, _weapon("FLOOD_HORSE")))


def test_the_morgul_blade_subtype_is_accepted(tmp_path):
    assert not any("BECOME_UNDEAD" in line for line in _lint(tmp_path, _weapon("BECOME_UNDEAD")))


def test_an_fx_name_is_not_an_armor_row(tmp_path):
    found = _lint(tmp_path, "Armor TestArmor\n    Armor = FIRE3 300%\nEnd\n")
    assert any("'FIRE3'" in line for line in found)


def test_the_fire_alias_is_not_an_armor_row(tmp_path):
    """The binary has no `FIRE` name; only the modifier parser tolerates it."""
    found = _lint(tmp_path, "Armor TestArmor\n    Armor = FIRE 300%\nEnd\n")
    assert any("'FIRE'" in line for line in found)


def test_fire_is_still_read_in_a_modifier_line(tmp_path):
    """Shipped `ModifierList`s write `ARMOR 50% FIRE` and load, so it must not be reported there."""
    found = _lint(tmp_path, "ModifierList FireWard\n    Modifier = ARMOR 50% FIRE\n    Duration = 0\nEnd\n")
    assert not any("FIRE" in line for line in found)
