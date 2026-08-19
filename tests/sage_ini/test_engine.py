"""Tests for `sage_ini.engine` - describing a patched engine's INI surface and applying it.

The properties that matter here are the ones a wrong implementation would still "work" without:

* a field added to a base class reaches the subclasses that already flattened their schema
  (`Object` -> `ChildObject`), which a naive `_fieldspec[name] = ...` silently would not;
* applying is *reversible* - the model is global, so a test or a second engine that does not get
  the stock schema back would poison everything after it;
* an injected enum member is a real member, so membership, iteration, `isinstance` and the INI
  converters all treat it exactly like a hand-written one; and
* nothing in the loading path raises, whatever the file says (CONVENTIONS.md rule 4).
"""

import enum

import pytest

from sage_ini.engine import (
    FORMAT_VERSION,
    STOCK,
    BlockDelta,
    Engine,
    EnumDelta,
    FieldDelta,
    LimitDelta,
    NoopDelta,
    Source,
    active,
    dump_engine,
    load_engine,
    parse_engine,
    parse_type,
    revert,
)
from sage_ini.loader import load_game
from sage_ini.model import enums as e
from sage_ini.model.objects import REGISTRY, resolve_annotation


def _engine(**kwargs) -> Engine:
    return Engine(**kwargs)


class TestTypeGrammar:
    @pytest.mark.parametrize(
        "spec",
        ["Bool", "Int", "Float", "String", "Label", "Opaque", "ModuleTag", "Int[]", "String[]"],
    )
    def test_every_scalar_and_list_spelling_resolves(self, spec):
        """Each spelling yields something the model can store as a field annotation - which for
        the scalars is an `Annotated` alias, exactly as a hand-written field declares them."""
        converter, error = parse_type(spec)
        assert error == ""
        assert hasattr(resolve_annotation(converter), "convert")

    def test_a_reference_names_a_game_table(self):
        converter, error = parse_type("Ref:upgrades")
        assert error == ""
        assert converter.key == "upgrades"

    def test_an_enum_spelling_resolves_to_the_model_enum(self):
        assert parse_type("Enum:ModelCondition") == (e.ModelCondition, "")
        listed, error = parse_type("Enum[]:WeaponSetConditions")
        assert error == ""
        assert listed.element is e.WeaponSetConditions

    @pytest.mark.parametrize("spec", ["", "int", "Integer", "Int[", "Enum:NoSuchEnum", "Wat:x"])
    def test_anything_outside_the_grammar_is_an_error_not_a_guess(self, spec):
        converter, error = parse_type(spec)
        assert converter is None
        assert error


class TestApplying:
    def test_a_field_is_added_to_the_block_and_converts(self):
        engine = _engine(fields=(FieldDelta("SpecialPower", "ManaCost", "Int", 0, "hero-mana"),))
        assert engine.apply() == []
        cls = REGISTRY["SpecialPower"]
        assert "ManaCost" in cls._fieldspec
        assert cls._defaults["ManaCost"] == 0

    def test_a_field_on_a_base_class_reaches_its_subclasses(self):
        """`_fieldspec` is flattened per class at creation, so a subclass that was built before
        the engine landed has to be rebuilt too - otherwise `Object.ManaPool` exists and
        `ChildObject.ManaPool` does not, and half the mod's objects report it as unknown."""
        _engine(fields=(FieldDelta("Object", "ManaPool", "Int", 0, "hero-mana"),)).apply()
        assert "ManaPool" in REGISTRY["Object"]._fieldspec
        assert "ManaPool" in REGISTRY["ChildObject"]._fieldspec

    def test_a_limit_overrides_the_stock_ceiling(self):
        engine = _engine(limits=(LimitDelta("commandset.max_slots", 80, "commandset-limit"),))
        assert engine.limit("commandset.max_slots") == 80
        # An unraised limit still answers, with the stock value.
        assert engine.limit("commandset.max_visible_buttons") == 33

    def test_a_retired_field_is_marked_but_stays_known(self):
        _engine(
            noops=(NoopDelta("SpecialPower", "UnitCost", "replaced by ManaCost", "hero-mana"),)
        ).apply()
        cls = REGISTRY["SpecialPower"]
        assert "UnitCost" in cls._fieldspec  # still parses; it is not an unknown attribute
        assert "replaced by ManaCost" in cls._noops["UnitCost"]
        assert "hero-mana" in cls._noops["UnitCost"]

    def test_retiring_a_field_the_block_does_not_have_is_reported(self):
        problems = _engine(noops=(NoopDelta("SpecialPower", "NotAField"),)).apply()
        assert problems and "nothing for the patch to have retired" in problems[0]

    def test_an_unknown_block_or_enum_is_reported_not_raised(self):
        problems = _engine(
            fields=(FieldDelta("NoSuchBlock", "X", "Int"),),
            enum_members=(EnumDelta("NoSuchEnum", "X"),),
        ).apply()
        assert len(problems) == 2
        assert any("unknown block type" in p for p in problems)
        assert any("unknown enum" in p for p in problems)

    def test_a_bad_field_type_is_reported_and_the_rest_still_applies(self):
        problems = _engine(
            fields=(
                FieldDelta("SpecialPower", "Broken", "NotAType"),
                FieldDelta("SpecialPower", "Fine", "Int"),
            )
        ).apply()
        assert len(problems) == 1
        assert "Fine" in REGISTRY["SpecialPower"]._fieldspec


class TestEnumMembers:
    def test_an_injected_member_behaves_like_a_declared_one(self):
        _engine(enum_members=(EnumDelta("ModelCondition", "PRODUCING", 591, "x"),)).apply()
        member = e.ModelCondition["PRODUCING"]
        assert member.name == "PRODUCING"
        assert member.value == 591
        assert isinstance(member, e.ModelCondition)
        assert isinstance(member, enum.Enum)
        assert "PRODUCING" in e.ModelCondition.__members__
        assert e.ModelCondition.has("PRODUCING")
        assert member in list(e.ModelCondition)
        assert e.ModelCondition.PRODUCING is member

    def test_the_ini_converter_accepts_the_new_token(self):
        _engine(enum_members=(EnumDelta("ModelCondition", "PRODUCING", 591),)).apply()
        assert e.ModelCondition.convert(None, "PRODUCING") is e.ModelCondition["PRODUCING"]

    def test_a_member_the_model_already_names_is_not_an_error(self):
        assert _engine(enum_members=(EnumDelta("ModelCondition", "SNOW", 8),)).apply() == []

    def test_reverting_removes_the_member_completely(self):
        _engine(enum_members=(EnumDelta("ModelCondition", "PRODUCING", 591),)).apply()
        revert()
        assert "PRODUCING" not in e.ModelCondition.__members__
        assert not hasattr(e.ModelCondition, "PRODUCING")
        with pytest.raises(KeyError):
            e.ModelCondition["PRODUCING"]


class TestReverting:
    def test_revert_restores_the_stock_schema(self):
        before = dict(REGISTRY["Object"]._fieldspec)
        _engine(fields=(FieldDelta("Object", "ManaPool", "Int", 0),)).apply()
        revert()
        assert REGISTRY["Object"]._fieldspec == before
        assert "ManaPool" not in REGISTRY["ChildObject"]._fieldspec
        assert active() is STOCK

    def test_applying_a_second_engine_replaces_the_first(self):
        _engine(fields=(FieldDelta("Object", "First", "Int"),)).apply()
        _engine(fields=(FieldDelta("Object", "Second", "Int"),)).apply()
        assert "First" not in REGISTRY["Object"]._fieldspec
        assert "Second" in REGISTRY["Object"]._fieldspec

    def test_activate_scopes_the_change(self):
        engine = _engine(fields=(FieldDelta("Object", "Scoped", "Int"),))
        with engine.activate() as problems:
            assert problems == []
            assert active() is engine
        assert "Scoped" not in REGISTRY["Object"]._fieldspec
        assert active() is STOCK


class TestFileFormat:
    def test_a_full_document_round_trips(self):
        engine = Engine(
            fields=(FieldDelta("SpecialPower", "ManaCost", "Int", 0, "hero-mana"),),
            noops=(NoopDelta("SpecialPower", "UnitCost", "no longer read", "hero-mana"),),
            enum_members=(EnumDelta("ModelCondition", "PRODUCING", 591, "production-condition"),),
            limits=(LimitDelta("commandset.max_slots", 64, "commandset-limit"),),
            source=Source(build="RotWK 2.01", sha256="abc", generator="test"),
        )
        back = parse_engine(dump_engine(engine))
        assert back.warnings == ()
        assert back == Engine(
            fields=engine.fields,
            noops=engine.noops,
            enum_members=engine.enum_members,
            limits=engine.limits,
            source=engine.source,
        )

    def test_malformed_toml_degrades_to_stock_with_a_warning(self):
        engine = parse_engine("this is not = = toml")
        assert engine.is_stock
        assert len(engine.warnings) == 1

    def test_unknown_sections_and_keys_warn_and_are_skipped(self):
        engine = parse_engine(
            f"version = {FORMAT_VERSION}\n[[nonsense]]\nx = 1\n\n[[limits]]\n"
            'name = "no.such.limit"\nvalue = 5\n'
        )
        assert engine.limits == ()
        assert any("nonsense" in w for w in engine.warnings)
        assert any("no.such.limit" in w for w in engine.warnings)

    def test_a_newer_format_version_still_loads_what_it_understands(self):
        engine = parse_engine(
            f"version = {FORMAT_VERSION + 1}\n[[limits]]\n"
            'name = "commandset.max_slots"\nvalue = 64\n'
        )
        assert engine.limit("commandset.max_slots") == 64
        assert any("newer generator" in w for w in engine.warnings)

    def test_an_entry_missing_what_it_needs_is_dropped_with_a_warning(self):
        engine = parse_engine('version = 1\n[[fields]]\nblock = "Object"\nname = "X"\n')
        assert engine.fields == ()
        assert any("type" in w for w in engine.warnings)

    def test_a_missing_file_is_simply_the_stock_engine(self, tmp_path):
        assert load_engine(tmp_path / "nope.sagepatch") is STOCK

    def test_merge_is_last_wins_per_delta(self):
        first = _engine(limits=(LimitDelta("commandset.max_slots", 40),))
        second = _engine(limits=(LimitDelta("commandset.max_slots", 80),))
        assert first.merge(second).limit("commandset.max_slots") == 80


def test_a_patched_field_converts_when_the_engine_is_loaded(tmp_path):
    """The end-to-end shape a mod actually uses: a `.sagepatch` beside the data, and a field the
    stock model has never heard of reading back as the typed value it is."""
    (tmp_path / "power.ini").write_text(
        "SpecialPower Test\n  ManaCost = 5\nEnd\n", encoding="utf-8"
    )
    (tmp_path / ".sagepatch").write_text(
        'version = 1\n[[fields]]\nblock = "SpecialPower"\nname = "ManaCost"\ntype = "Int"\n'
        'default = 0\npatch = "hero-mana"\n',
        encoding="utf-8",
    )
    loaded = load_game(tmp_path, engine=load_engine(tmp_path / ".sagepatch"))
    assert [d.code for d in loaded.diagnostics.items] == []
    assert loaded.game.specialpowers["Test"].ManaCost == 5


def test_a_broken_sagepatch_becomes_a_diagnostic_not_an_exception(tmp_path):
    (tmp_path / "power.ini").write_text("SpecialPower Test\nEnd\n", encoding="utf-8")
    (tmp_path / ".sagepatch").write_text("version = 1\n[[fields]]\nnot = valid\n", encoding="utf-8")
    loaded = load_game(tmp_path, engine=load_engine(tmp_path / ".sagepatch"))
    assert [d.code for d in loaded.diagnostics.items] == ["engine-config"]


class TestBlockDelta:
    """A patch can change which blocks *exist*, not just what a known block accepts.

    The properties worth pinning are the ones a naive `REGISTRY[name] = ...` would get wrong: a
    created block has to be a real class with its base's schema flattened into it, and both
    directions have to revert - a removed stock block must come back, or one test that removes it
    breaks every test after."""

    def test_a_created_block_is_registered_with_its_base_schema(self):
        engine = _engine(blocks=(BlockDelta("ProximityCaptureUpdate", base="Behavior"),))
        try:
            assert engine.apply() == []
            created = REGISTRY["ProximityCaptureUpdate"]
            assert issubclass(created, REGISTRY["Behavior"])
            assert created._fieldspec.keys() >= REGISTRY["Behavior"]._fieldspec.keys()
        finally:
            revert()
        assert "ProximityCaptureUpdate" not in REGISTRY

    def test_a_field_can_name_a_block_the_same_engine_creates(self):
        """Blocks are applied before fields, which is the whole reason the order is fixed."""
        engine = _engine(
            blocks=(BlockDelta("ProximityCaptureUpdate"),),
            fields=(FieldDelta("ProximityCaptureUpdate", "CaptureShare", "Int", 50),),
        )
        try:
            assert engine.apply() == []
            assert REGISTRY["ProximityCaptureUpdate"]._defaults["CaptureShare"] == 50
        finally:
            revert()

    def test_a_removed_block_comes_back_on_revert(self):
        engine = _engine(blocks=(BlockDelta("AutoFindHealingUpdate", removed=True),))
        try:
            assert engine.apply() == []
            assert "AutoFindHealingUpdate" not in REGISTRY
        finally:
            revert()
        assert "AutoFindHealingUpdate" in REGISTRY

    def test_creating_a_block_that_already_exists_is_a_problem_not_a_clobber(self):
        engine = _engine(blocks=(BlockDelta("AutoFindHealingUpdate"),))
        try:
            assert engine.apply() == ["'AutoFindHealingUpdate' is already a block type"]
        finally:
            revert()

    def test_removing_a_block_that_does_not_exist_says_so(self):
        engine = _engine(blocks=(BlockDelta("NoSuchModule", removed=True),))
        try:
            problems = engine.apply()
            assert len(problems) == 1
            assert "nothing for the patch to have removed" in problems[0]
        finally:
            revert()

    def test_an_unknown_base_is_a_problem(self):
        engine = _engine(blocks=(BlockDelta("Whatever", base="NoSuchBase"),))
        try:
            assert engine.apply() == ["Whatever: base unknown block type 'NoSuchBase'"]
            assert "Whatever" not in REGISTRY
        finally:
            revert()

    def test_blocks_round_trip_through_a_sagepatch(self):
        engine = _engine(
            blocks=(
                BlockDelta("ProximityCaptureUpdate", base="Behavior", patch="capture-the-flag"),
                BlockDelta("AutoFindHealingUpdate", removed=True, patch="capture-the-flag"),
            )
        )
        reloaded = parse_engine(dump_engine(engine))
        assert reloaded.warnings == ()
        assert reloaded.blocks == engine.blocks

    def test_an_engine_with_only_a_block_is_not_stock(self):
        assert not _engine(blocks=(BlockDelta("Whatever"),)).is_stock
