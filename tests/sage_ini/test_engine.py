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
    AppliedPatch,
    BlockDelta,
    Engine,
    EnumDelta,
    FieldDelta,
    LimitDelta,
    NestedDelta,
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


class TestNestedBlocks:
    """A sub-block a patch lets a block contain.

    Registering the block type and nesting it are two different facts, and only the pair makes the
    sub-block legal where it is written - the schema keeps nested groups in their own map, so a
    block that exists but is not nested is reported as an unknown attribute of its parent."""

    def _engine(self) -> Engine:
        return Engine(
            blocks=(BlockDelta("MergePlayerArmy", base="NestedAttribute", patch="p"),),
            nested=(NestedDelta("Act", "MergePlayerArmy", patch="p"),),
        )

    def test_the_parent_gains_the_sub_block(self):
        with self._engine().activate() as problems:
            assert problems == []
            assert REGISTRY["Act"]._nested["MergePlayerArmy"] == ["MergePlayerArmy"]

    def test_the_parents_own_sub_blocks_survive(self):
        stock = set(REGISTRY["Act"]._nested)
        with self._engine().activate():
            assert set(REGISTRY["Act"]._nested) == stock | {"MergePlayerArmy"}

    def test_a_sibling_sharing_the_dict_does_not_gain_it(self):
        """`Act` and `Scenario` are handed the *same* `nested_attributes` object by the stock
        model, so an implementation that mutated it in place would nest the block under both."""
        stock = set(REGISTRY["Scenario"]._nested)
        with self._engine().activate():
            assert set(REGISTRY["Scenario"]._nested) == stock

    def test_reverting_takes_it_back_off(self):
        stock = set(REGISTRY["Act"]._nested)
        with self._engine().activate():
            pass
        assert set(REGISTRY["Act"]._nested) == stock

    def test_type_names_the_class_when_it_differs_from_the_keyword(self):
        engine = Engine(
            blocks=(BlockDelta("SplitBlock", base="NestedAttribute", patch="p"),),
            nested=(NestedDelta("Act", "MergePlayerArmy", type="SplitBlock", patch="p"),),
        )
        with engine.activate() as problems:
            assert problems == []
            assert REGISTRY["Act"]._nested["MergePlayerArmy"] == ["SplitBlock"]

    def test_an_unknown_parent_is_reported_not_raised(self):
        engine = Engine(nested=(NestedDelta("NoSuchBlock", "Whatever", patch="p"),))
        with engine.activate() as problems:
            assert any("NoSuchBlock" in problem for problem in problems)

    def test_an_unknown_child_is_reported_not_raised(self):
        engine = Engine(nested=(NestedDelta("Act", "NeverRegistered", patch="p"),))
        with engine.activate() as problems:
            assert any("NeverRegistered" in problem for problem in problems)
            assert "NeverRegistered" not in REGISTRY["Act"]._nested

    def test_nesting_alone_is_not_a_stock_engine(self):
        assert not Engine(nested=(NestedDelta("Act", "X", patch="p"),)).is_stock
        assert STOCK.is_stock


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


class TestTheManifest:
    """The `[[patches]]` list: what the binary is made of, as opposed to what it now accepts.

    Its own section because it answers a different question from every delta beside it - most
    patches change no INI at all, so a file that only recorded the surface would list none of
    them - and because the model must stay indifferent to it: it is provenance, not schema."""

    def test_the_list_round_trips_with_its_parameters(self):
        engine = Engine(
            patches=(
                AppliedPatch("commandset-limit", (("count", 64),), author="officialNecro"),
                AppliedPatch("cah-factions", (("sides", ("Rohan", "Lothlorien")),)),
                AppliedPatch("headless", experimental=True),
            )
        )
        back = parse_engine(dump_engine(engine))

        assert back.warnings == ()
        assert back.patches == engine.patches

    def test_a_patch_that_changes_no_ini_is_still_listed(self):
        """The whole point of the section. `is_stock` is about the INI surface, so a build made
        only of patches that add no field and no token is stock *and* has a manifest."""
        engine = parse_engine(
            f"""version = {FORMAT_VERSION}
[[patches]]
name = "crash-dump"
"""
        )

        assert engine.warnings == ()
        assert engine.is_stock
        assert engine.patches == (AppliedPatch("crash-dump"),)

    def test_a_description_is_written_as_a_comment_and_not_read_back(self):
        """Prose about a patch rather than a fact about the binary: it is in the file so a reader
        with nothing installed knows what the build does, and out of the data so rewording one
        can never read as drift."""
        engine = Engine(patches=(AppliedPatch("crash-dump", description="Write a minidump"),))
        text = dump_engine(engine)

        assert "# Write a minidump" in text
        assert parse_engine(text).patches == (AppliedPatch("crash-dump"),)

    def test_an_option_the_file_spells_wrongly_is_dropped_with_a_warning(self):
        engine = parse_engine(
            f"""version = {FORMAT_VERSION}
[[patches]]
name = "commandset-limit"
options = {{ count = 64, nested = {{ no = 1 }} }}
"""
        )

        assert engine.patches == (AppliedPatch("commandset-limit", (("count", 64),)),)
        assert any("nested" in w for w in engine.warnings)

    def test_an_entry_without_a_name_is_dropped_with_a_warning(self):
        engine = parse_engine(
            f"""version = {FORMAT_VERSION}
[[patches]]
author = "somebody"
"""
        )

        assert engine.patches == ()
        assert any("name" in w for w in engine.warnings)

    def test_merging_is_last_wins_per_patch_name(self):
        first = _engine(patches=(AppliedPatch("commandset-limit", (("count", 40),)),))
        second = _engine(patches=(AppliedPatch("commandset-limit", (("count", 80),)),))

        assert first.merge(second).patches == second.patches

    def test_the_manifest_changes_nothing_about_the_model(self):
        """Applying an engine that is nothing but a manifest is a no-op, and reverts cleanly."""
        engine = _engine(patches=(AppliedPatch("crash-dump"),))

        with engine.activate() as problems:
            assert problems == []
            assert active() is engine


class TestFileFormat:
    def test_a_full_document_round_trips(self):
        engine = Engine(
            patches=(AppliedPatch("hero-mana", (("pool", 100),)),),
            fields=(FieldDelta("SpecialPower", "ManaCost", "Int", 0, "hero-mana"),),
            nested=(NestedDelta("Act", "MergePlayerArmy", patch="campaign-army-verbs"),),
            noops=(NoopDelta("SpecialPower", "UnitCost", "no longer read", "hero-mana"),),
            enum_members=(EnumDelta("ModelCondition", "PRODUCING", 591, "production-condition"),),
            limits=(LimitDelta("commandset.max_slots", 64, "commandset-limit"),),
            source=Source(build="RotWK 2.01", sha256="abc", generator="test"),
        )
        back = parse_engine(dump_engine(engine))
        assert back.warnings == ()
        assert back == Engine(
            patches=engine.patches,
            nested=engine.nested,
            fields=engine.fields,
            noops=engine.noops,
            enum_members=engine.enum_members,
            limits=engine.limits,
            source=engine.source,
        )

    def test_a_retired_source_key_is_dropped_without_complaint(self):
        """`[source] game_dat` used to hold the path the file was generated from.

        It was removed because `.sagepatch` is committed to the mod's repository and a path is
        provenance nothing can use: `sha256` already identifies the binary exactly, while the path
        writes a home directory into a tracked file. Files written before the removal are still
        out there, so loading one has to drop the key silently - a warning would fire on every
        load until every mod regenerated, for a key that never meant anything.
        """
        engine = parse_engine(
            'version = 1\n\n[source]\nbuild = "RotWK 2.01"\n'
            'sha256 = "abc"\ngame_dat = "C:\\\\Users\\\\somebody\\\\game.dat"\n'
        )
        assert engine.warnings == ()
        assert engine.source == Source(build="RotWK 2.01", sha256="abc")
        assert "game_dat" not in dump_engine(engine)

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
