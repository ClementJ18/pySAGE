"""Tests for `sage_patch.sagepatch` - reading a patched binary back as a `.sagepatch`.

The two passes are tested for what each is *for*: detection has to recover a patch's parameters
(not just notice it), and the name-table pass has to find tokens whatever put them there -
including in a binary where detection recognises nothing at all.

The last class is the anti-drift gate. Every patch's `ini_surface` is a hand-written claim about
what the engine will accept afterwards, sitting next to assembly that could be changed without it
- so it is checked against the live model: the block exists, the type spells something the
grammar knows, the field is not one the stock engine already had (which would mean the patch adds
nothing), and the enum is real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_ini.engine import STOCK_LIMITS, Engine, dump_engine, load_engine, parse_type
from sage_ini.loader import load_game
from sage_ini.model import enums as model_enums
from sage_ini.model.objects import REGISTRY
from sage_patch.patcher import apply_patches
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import DesertWeatherPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.production_condition import _UPDATE_VA, ProductionConditionPatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import (
    detect_patches,
    differences,
    generate,
    generate_from_patches,
    name_table_members,
)
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import synthetic_image
from tests.sage_patch.test_terrain_resource_exp import _composable_image


def _tokens(engine: Engine) -> dict[str, tuple[str, int | None]]:
    return {delta.name: (delta.enum, delta.value) for delta in engine.enum_members}


class TestNameTables:
    def test_a_stock_image_adds_no_tokens(self):
        members, notes = name_table_members(synthetic_image())

        assert members == ()
        assert notes == ()

    def test_every_added_token_is_found_with_the_index_it_landed_on(self):
        image = synthetic_image()
        ProductionConditionPatch(
            condition="BUSY", weapon_set_flag="BUSY_WEAPONS", locomotor_set="SET_BUSY"
        ).apply(image)
        members, notes = name_table_members(image)

        assert notes == ()
        assert {(d.enum, d.name) for d in members} == {
            ("ModelCondition", "BUSY"),
            ("WeaponSetConditions", "BUSY_WEAPONS"),
            ("LocomotorSetType", "SET_BUSY"),
        }
        # The index is the bit/slot the engine gave it, read back rather than assumed.
        assert all(delta.value is not None for delta in members)

    def test_a_token_is_found_even_when_the_patch_that_added_it_is_not_recognised(self):
        """The two passes are independent, and this is the case that proves it: a token reaches
        the `.sagepatch` even when no patch is recognised at all - the token is what the INI
        needs, and something put it in the engine's live table whatever detection makes of it.

        Detection is defeated here by damaging a site `verify` checks, since a custom name no
        longer does it: every parameterized patch now recovers its own settings."""
        image = synthetic_image()
        ProductionConditionPatch(condition="SOMETHING_ELSE", weapon_set_flag="ALSO_CUSTOM").apply(
            image
        )
        # Break the hook's `jmp` into the cave. The model-condition table still carries the token.
        off = va_to_offset(image, _UPDATE_VA)
        image[off] = 0x90
        generated = generate(image)

        assert generated.patches == ()
        assert "SOMETHING_ELSE" in _tokens(generated.engine)
        assert any("named by no patch" in note for note in generated.notes)

    def test_two_patches_adding_conditions_both_land(self):
        image = synthetic_image()
        ProductionConditionPatch().apply(image)
        DesertWeatherPatch().apply(image)
        tokens = _tokens(generate(image).engine)

        assert "PRODUCING" in tokens
        assert "SAND" in tokens
        assert tokens["DESERT"] == ("MapWeatherType", 2)


class TestDetection:
    def test_a_parameterized_patch_reports_the_parameters_it_was_applied_with(self):
        image = _composable_image()
        CommandSetLimitPatch(count=100).apply(image)
        TerrainResourceExpPatch(keyword="SkipTheXP").apply(image)
        found = {type(patch): patch for patch in detect_patches(image)}

        assert found[CommandSetLimitPatch].count == 100
        assert found[TerrainResourceExpPatch].keyword == "SkipTheXP"

    def test_the_recovered_parameters_reach_the_written_surface(self):
        image = _composable_image()
        CommandSetLimitPatch(count=100).apply(image)
        engine = generate(image).engine

        assert engine.limit("commandset.max_slots") == 100

    def test_an_unpatched_image_carries_nothing(self):
        assert detect_patches(_composable_image()) == ()

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert detect_patches(bytearray(b"MZ" + bytes(4096))) == ()


class TestFromPatchNames:
    def test_named_patches_describe_their_default_surface(self):
        generated, unknown = generate_from_patches(["hero-mana", "commandset-limit"])

        assert unknown == []
        assert generated.engine.limit("commandset.max_slots") == 64
        assert {field.name for field in generated.engine.fields} == {
            "ManaCost",
            "ManaPool",
            "ManaRegen",
        }

    def test_an_unknown_name_is_returned_rather_than_raised(self):
        generated, unknown = generate_from_patches(["not-a-patch"])

        assert unknown == ["not-a-patch"]
        assert generated.engine.is_stock


class TestDrift:
    def test_a_matching_file_reports_no_differences(self):
        generated, _ = generate_from_patches(["hero-mana"])

        assert differences(generated.engine, generated.engine) == []

    def test_a_missing_delta_is_reported_from_both_sides(self):
        committed, _ = generate_from_patches(["hero-mana"])
        rebuilt, _ = generate_from_patches(["hero-mana", "commandset-limit"])
        problems = differences(committed.engine, rebuilt.engine)

        assert len(problems) == 1
        assert "in the binary but not in the file" in problems[0]
        assert differences(rebuilt.engine, committed.engine)[0].startswith("limit in the file")


def _same_converter(stock: object, declared: object) -> bool:
    """Whether two converters mean the same thing.

    Identity settles the scalars, which are shared singletons, and a class annotation like
    `SpecialPower`, which is the class itself. The parametrized ones - `Reference`, `List` - are
    built fresh by `parse_type` on every call and carry no `__eq__`, so they are compared by type
    and instance state. Shallow on purpose: the comparison can only ever miss a redundant delta,
    never reject a real re-typing.
    """
    if stock is declared:
        return True
    if type(stock) is not type(declared) or isinstance(stock, type):
        return False
    return getattr(stock, "__dict__", None) == getattr(declared, "__dict__", None)


class TestPatchSurfacesMatchTheModel:
    """Every registered patch's declared INI surface, checked against the live model."""

    @pytest.fixture(params=sorted(PATCHES), ids=sorted(PATCHES))
    def surface(self, request) -> Engine:
        return PATCHES[request.param]().ini_surface()

    def test_it_applies_cleanly(self, surface):
        assert surface.apply() == []

    def test_every_field_names_a_real_block_and_a_type_the_grammar_knows(self, surface):
        """ "Real" means the stock model's, *or* one this same surface introduces - a patch that
        registers a new module type with the engine's `ModuleFactory` necessarily declares fields
        on a block no stock binary has."""
        introduced = {b.name for b in surface.blocks if not b.removed}
        for delta in surface.fields:
            assert delta.block in REGISTRY or delta.block in introduced, (
                f"{delta.block} is not a block type, and this surface does not introduce it"
            )
            converter, error = parse_type(delta.type)
            assert converter is not None, f"{delta.block}.{delta.name}: {error}"

    def test_no_field_lands_on_a_block_the_same_surface_removes(self, surface):
        """Declaring a keyword on a block the patch just unregistered describes an INI nobody can
        write: the whole block is a parse error before the field is ever reached."""
        removed = {b.name for b in surface.blocks if b.removed}
        for delta in surface.fields:
            assert delta.block not in removed, f"{delta.block} is removed by this same patch"

    def test_every_block_delta_is_coherent(self, surface):
        """A removed block has to be one that exists to remove; a created one has to name a base
        that does."""
        for block in surface.blocks:
            if block.removed:
                assert block.name in REGISTRY, f"{block.name} is not a block type to remove"
            else:
                assert block.base in REGISTRY, f"{block.name}: base {block.base} is not a block"
                assert block.name not in REGISTRY, f"{block.name} already exists"

    def test_every_field_is_a_new_one_or_a_real_re_typing(self, surface):
        """A patch that "adds" a field the model already declares, *with the type it already has*,
        is either describing the wrong block or describing a field it does not actually change -
        both make the `.sagepatch` lie. Re-typing a stock field is allowed and is a thing patches
        do (`trigger-recharge-list` turns a single `SpecialPower` name into a list of them), so
        what is asserted is that the delta changes something."""
        introduced = {b.name for b in surface.blocks if not b.removed}
        for delta in surface.fields:
            if delta.block in introduced:
                continue  # a block the stock model has never had cannot re-type anything
            # No engine is applied here (the suite reverts after every test), so the fieldspec is
            # the stock schema.
            stock = REGISTRY[delta.block]._fieldspec.get(delta.name)
            if stock is None:
                continue
            converter, _error = parse_type(delta.type)
            assert not _same_converter(stock, converter), (
                f"{delta.block}.{delta.name} is already in the model with that type"
            )

    def test_every_token_names_a_real_enum(self, surface):
        for delta in surface.enum_members:
            assert hasattr(model_enums, delta.enum), f"{delta.enum} is not a model enum"

    def test_every_limit_is_one_this_version_defines(self, surface):
        for delta in surface.limits:
            assert delta.name in STOCK_LIMITS

    def test_a_raised_limit_is_above_the_stock_one(self, surface):
        for delta in surface.limits:
            assert delta.value > STOCK_LIMITS[delta.name]


_REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.mark.full
@pytest.mark.skipif(
    not _REAL_GAME_DAT.exists(), reason="requires a local game.dat (gitignored, absent in CI)"
)
class TestAgainstARealBinary:
    """The whole path on a real binary, which the synthetic images cannot cover: every patch site
    at its real address, every name table at its real length, and the file that comes out actually
    driving the model."""

    def test_an_unpatched_binary_describes_the_stock_engine(self):
        generated = generate(_REAL_GAME_DAT.read_bytes())

        assert generated.engine.is_stock or generated.patches, (
            "a binary with no patch detected should describe no deltas either"
        )

    def test_a_patched_binary_round_trips_into_a_working_model(self, tmp_path):
        """Patch a copy, write the `.sagepatch` it produces, load a mod against it, and read the
        patched field back as the int it is - the entire point of the feature, end to end."""
        patched = tmp_path / "game.dat"
        apply_patches(
            _REAL_GAME_DAT,
            [HeroManaPatch(), CommandSetLimitPatch(count=80)],
            output=patched,
        )
        engine = generate(patched.read_bytes(), patched).engine
        written = tmp_path / ".sagepatch"
        written.write_text(dump_engine(engine), encoding="utf-8")

        (tmp_path / "power.ini").write_text(
            "SpecialPower Test\n    ManaCost = 5\nEnd\n", encoding="utf-8"
        )
        loaded = load_game(tmp_path, engine=load_engine(written))

        assert [d.code for d in loaded.diagnostics.items] == []
        assert loaded.game.specialpowers["Test"].ManaCost == 5
        assert load_engine(written).limit("commandset.max_slots") == 80
