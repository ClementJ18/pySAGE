"""Conversion-correctness tests for the typed value converters.

Values mirror real corpus shapes: `#MULTIPLY( MACRO 1.1 )` operations, float
literals with a trailing `f`, percentages, macro operands.
"""

import pytest

from sage_ini.model.enums import (
    AllowedWhenConditions,
    AudioPriority,
    ButtonBorderTypes,
    DamageFXTypes,
    Dispositions,
    DistributionType,
    FactionSide,
    KindOf,
    LocomotorSetType,
    ObjectFilterRules,
    Stances,
    WeaponPrefireType,
)
from sage_ini.model.game import Game
from sage_ini.model.objects import resolve_annotation
from sage_ini.model.types import (
    RGBA,
    AnimAndDuration,
    AttackPriorityTarget,
    BannerCarrierPosition,
    Bone,
    DeathEntry,
    Degrees,
    FCurveKey,
    FlagList,
    Float,
    FloatRange,
    FXList,
    Int,
    IntRange,
    List,
    MapFile,
    Nullable,
    QuotedList,
    RandomVariable,
    RangeDuration,
    Reference,
    RespawnRules,
    ScaledObjectFilter,
    ScienceRequirements,
    Sound,
    String,
    Tuple,
    UpgradeWithDelay,
)
from sage_ini.parser.blockparser import parse

# These public names are typed aliases (`Annotated[PyType, converter]`) so a field declared
# with them reads as its converted value type. The tests drive the converter behind the alias,
# which is exactly what the model extracts at access time — so resolve it here, once.
AttackPriorityTarget = resolve_annotation(AttackPriorityTarget)
BannerCarrierPosition = resolve_annotation(BannerCarrierPosition)
FCurveKey = resolve_annotation(FCurveKey)
RGBA = resolve_annotation(RGBA)
Bone = resolve_annotation(Bone)
Degrees = resolve_annotation(Degrees)
Float = resolve_annotation(Float)
FloatRange = resolve_annotation(FloatRange)
FXList = resolve_annotation(FXList)
Int = resolve_annotation(Int)
IntRange = resolve_annotation(IntRange)
RandomVariable = resolve_annotation(RandomVariable)
ScaledObjectFilter = resolve_annotation(ScaledObjectFilter)
ScienceRequirements = resolve_annotation(ScienceRequirements)
Sound = resolve_annotation(Sound)
String = resolve_annotation(String)


def game_with(**macros) -> Game:
    game = Game()
    game.add_macros({k: str(v) for k, v in macros.items()})
    return game


class TestPlainNumbers:
    def test_int_and_float(self):
        game = Game()
        assert Int.convert(game, "5") == 5
        assert Float.convert(game, "12.5") == 12.5

    def test_percent_becomes_fraction(self):
        assert Float.convert(Game(), "80%") == pytest.approx(0.80)

    def test_negative(self):
        assert Float.convert(Game(), "-4.5") == -4.5

    def test_float_suffix_is_tolerated(self):
        # corpus: `DefaultUnitPriority = 100.0f`
        assert Float.convert(Game(), "100.0f") == 100.0

    def test_macro_operand(self):
        game = game_with(RANGE=120)
        assert Float.convert(game, "RANGE") == 120.0


class TestOperations:
    def test_multiply_with_macro(self):
        # corpus: `#MULTIPLY( MORDOR_HARADRIM_BOW_RANGE 1.1 )`
        game = game_with(RANGE=100)
        assert Float.convert(game, "#MULTIPLY( RANGE 1.1 )") == pytest.approx(110.0)

    def test_divide(self):
        assert Float.convert(Game(), "#DIVIDE( 100 4 )") == 25.0

    def test_add(self):
        game = game_with(BASE=50)
        assert Float.convert(game, "#ADD( BASE 5 )") == 55.0

    def test_subtract(self):
        # corpus: `#SUBTRACT( SARUMAN_FIREBALL_RANGE 25 )`
        game = game_with(RANGE=500)
        assert Float.convert(game, "#SUBTRACT( RANGE 25 )") == 475.0

    def test_two_macro_operands(self):
        # corpus: `#MULTIPLY( ROHAN_ENT_HEALTH ROHAN_ENT_FIRE_THRESHOLD )`
        game = game_with(HEALTH=2000, THRESHOLD=0.25)
        assert Float.convert(game, "#MULTIPLY( HEALTH THRESHOLD )") == pytest.approx(500.0)

    def test_nested_operation(self):
        assert Float.convert(Game(), "#ADD( #MULTIPLY( 2 3 ) 4 )") == 10.0

    def test_int_of_operation_truncates(self):
        game = game_with(RANGE=100)
        assert Int.convert(game, "#MULTIPLY( RANGE 2 )") == 200

    def test_unresolved_macro_raises_valueerror(self):
        with pytest.raises(ValueError):
            Float.convert(Game(), "#MULTIPLY( UNKNOWN_MACRO 2 )")


class TestMacroCase:
    def test_exact_case_resolves_without_warning(self):
        game = game_with(CREATE_A_HERO_DAMAGE=150)
        assert Float.convert(game, "CREATE_A_HERO_DAMAGE") == 150.0
        assert game._pending_warnings == []

    def test_mismatched_case_resolves_and_warns(self):
        # corpus: a `#define CREATE_A_HERO_LUFTSTOSS...` referenced as `...LUFTSTOss...`.
        game = game_with(CREATE_A_HERO_LUFTSTOSS_DAMAGE_LVL_1=200)
        assert Float.convert(game, "CREATE_A_HERO_LUFTSTOss_DAMAGE_LVL_1") == 200.0
        codes = [code for code, _, _ in game._pending_warnings]
        assert codes == ["macro-case"]

    def test_mismatched_case_inside_an_operation_warns(self):
        game = game_with(LEGOLAS_RELOADTIME_MIN=500)
        assert Float.convert(game, "#MULTIPLY( legolas_reloadtime_min 2 )") == 1000.0
        assert [code for code, _, _ in game._pending_warnings] == ["macro-case"]

    def test_has_macro_is_case_insensitive_and_side_effect_free(self):
        game = game_with(FOO=1)
        assert game.has_macro("foo")
        assert not game.has_macro("BAR")
        assert game._pending_warnings == []  # checking existence raises no warning

    def test_a_genuine_non_macro_value_passes_through(self):
        game = game_with(FOO=1)
        assert game.get_macro("STRUCTURE") == "STRUCTURE"
        assert game._pending_warnings == []


class TestDegrees:
    def test_in_range(self):
        assert Degrees.convert(Game(), "90") == 90

    def test_unsigned_range_is_allowed(self):
        # The engine accepts unsigned degrees too (0..360), so 270 is valid.
        assert Degrees.convert(Game(), "270") == 270

    def test_out_of_range_still_converts(self):
        # Range is a lint judgment (the out-of-range rule), not a parse fact:
        # 400 is a fine integer, so conversion accepts it and never raises.
        assert Degrees.convert(Game(), "400") == 400


class TestRanges:
    def test_float_range(self):
        # corpus: `PitchShift = -5 5`
        assert FloatRange.convert(Game(), "-5 5") == (-5.0, 5.0)

    def test_int_range(self):
        assert IntRange.convert(Game(), "1000 2000") == (1000, 2000)

    def test_single_token_is_a_zero_width_range(self):
        # corpus audio `Delay = 1000` gives one token; both bounds collapse to it.
        assert IntRange.convert(Game(), "1000") == (1000, 1000)

    def test_random_variable_defaults_to_uniform(self):
        rv = RandomVariable.convert(Game(), "0 1")
        assert (rv.low, rv.high) == (0.0, 1.0)
        assert rv.distribution is DistributionType.UNIFORM

    def test_random_variable_reads_distribution_token(self):
        # corpus: `InitialDelay = 1000 1000 UNIFORM`
        rv = RandomVariable.convert(Game(), "1 1 UNIFORM")
        assert rv.distribution is DistributionType.UNIFORM

    def test_range_duration_min_max_with_macro_operations(self):
        # corpus: `ClipReloadTime = Min: #MULTIPLY( MIN 2 ) Max:#MULTIPLY( MAX 2 )` — each
        # bound is a spaced `#OP( ... )`, so the whole expression must reach eval_number, not
        # just its leading `#MULTIPLY(` fragment.
        game = Game()
        game.macros.update({"MIN": "500", "MAX": "1000"})
        rd = RangeDuration.convert(game, "Min: #MULTIPLY( MIN 2 ) Max:#MULTIPLY( MAX 2 )")
        assert (rd.min, rd.max) == (1000, 2000)

    def test_range_duration_plain_min_max(self):
        assert RangeDuration.convert(Game(), "Min:1300 Max:1000").min == 1300

    def test_range_duration_single_value_sets_both_bounds(self):
        rd = RangeDuration.convert(Game(), "4000")
        assert (rd.min, rd.max) == (4000, 4000)


class TestEnumCase:
    def test_audio_priority_accepts_uppercase_silently(self):
        # The corpus writes `Priority = HIGH`; the engine token is lower-case, so a
        # CaseInsensitiveEnum resolves it without an enum-case warning.
        game = Game()
        assert AudioPriority.convert(game, "HIGH") is AudioPriority.HIGH
        assert game._pending_warnings == []

    def test_exact_match_records_no_warning(self):
        game = Game()
        assert KindOf.convert(game, "STRUCTURE") is KindOf.STRUCTURE
        assert game._pending_warnings == []

    def test_case_insensitive_match_resolves_and_warns(self):
        game = Game()
        assert KindOf.convert(game, "Structure") is KindOf.STRUCTURE
        assert [code for code, *_ in game._pending_warnings] == ["enum-case"]

    def test_override_marker_matches_case_insensitively(self):
        # A +/- override token resolves the same member, ignoring case.
        assert KindOf.convert(Game(), "+Structure") is KindOf.STRUCTURE

    def test_genuinely_unknown_member_still_raises(self):
        with pytest.raises(KeyError):
            KindOf.convert(Game(), "NOT_A_KINDOF")


class TestReference:
    def test_unknown_name_passes_through(self):
        # No table for the kind yet -> lossless raw name, never raises.
        assert FXList.convert(Game(), "FX_HealGlow") == "FX_HealGlow"

    def test_resolves_when_table_is_populated(self):
        game = Game()
        marker = object()
        game.fxlists["FX_HealGlow"] = marker
        assert FXList.convert(game, "FX_HealGlow") is marker

    def test_distinct_kinds_use_distinct_tables(self):
        game = Game()
        game.audioevents["Snd"] = "AUDIO"
        # a Sound resolves against audioevents; the same name as an FXList does not
        assert Sound.convert(game, "Snd") == "AUDIO"
        assert FXList.convert(game, "Snd") == "Snd"

    def test_each_kind_is_keyed_to_its_own_table(self):
        assert isinstance(FXList, Reference)
        assert FXList.key == "fxlists"
        assert Sound.key == "audioevents"

    def test_resolves_case_insensitively_and_warns(self):
        # The engine interns names case-insensitively, so a reference whose casing differs from
        # the definition still resolves — but the mismatch is flagged for the linter.
        game = Game()
        marker = _Definition("fxlists", "FX_HealGlow")
        game.register(marker)
        assert FXList.convert(game, "fx_healglow") is marker
        assert [code for code, *_ in game._pending_warnings] == ["reference-case"]

    def test_exact_case_resolves_without_warning(self):
        game = Game()
        marker = _Definition("fxlists", "FX_HealGlow")
        game.register(marker)
        assert FXList.convert(game, "FX_HealGlow") is marker
        assert game._pending_warnings == []


class _Definition:
    """A minimal registrable stand-in (only `key`/`name`, what `Game.register` reads)."""

    def __init__(self, key: str, name: str) -> None:
        self.key = key
        self.name = name


class TestOpaqueAndStructured:
    def test_bone_is_raw_token(self):
        assert Bone.convert(Game(), "B_SPINE0") == "B_SPINE0"

    def test_anim_and_duration_parses_colon_pairs(self):
        # corpus: `CustomAnimAndDuration = AnimState:USER_3 AnimTime:0 TriggerTime:0`
        result = AnimAndDuration.convert(Game(), "AnimState:USER_3 AnimTime:0 TriggerTime:0")
        assert result == {"AnimState": "USER_3", "AnimTime": "0", "TriggerTime": "0"}


class TestListOfTuple:
    def test_single_line_is_one_tuple(self):
        # `Weapon = PRIMARY MyWeapon`: the whole line is one element, not one
        # element per whitespace token.
        conv = List[Tuple[Int, String]]
        assert conv.convert(Game(), "1 Foo") == [(1, "Foo")]

    def test_repeated_key_is_one_tuple_per_line(self):
        conv = List[Tuple[Int, String]]
        assert conv.convert(Game(), ["1 Foo", "2 Bar"]) == [(1, "Foo"), (2, "Bar")]

    def test_missing_trailing_token_is_none(self):
        # An optional trailing slot left out (`TriggerSpecialPower = ModuleTag`
        # with no position) resolves to None rather than consuming the converter.
        assert Tuple[String, Int].convert(Game(), "Foo") == ("Foo", None)

    def test_list_of_scalar_still_splits_a_single_line(self):
        # `KindOf = INFANTRY CAVALRY`: scalar elements split by whitespace.
        assert List[Int].convert(Game(), "1 2 3") == [1, 2, 3]

    def test_repeated_key_flattens_multi_token_lines(self):
        # A repeated scalar list key whose lines each carry several tokens flattens
        # into one list — `KindOf` written on two lines, not one element per line.
        assert List[Int].convert(Game(), ["1 2", "3 4 5"]) == [1, 2, 3, 4, 5]

    def test_macro_token_expands_to_its_flags(self):
        # An engine `#define` naming several flags expands in place: a macro token
        # in a list becomes the tokens it stands for (and recurses).
        game = game_with()
        game.macros["TRIO"] = "1 2 3"
        game.macros["PAIR_AND_TRIO"] = "9 TRIO"
        assert List[Int].convert(game, "TRIO 4") == [1, 2, 3, 4]
        assert List[Int].convert(game, "PAIR_AND_TRIO") == [9, 1, 2, 3]

    def test_enum_member_token_wins_over_a_same_named_macro(self):
        # `#define GANDALF <object names>` (for an ExperienceLevel's TargetNames)
        # must not rewrite the `KindOf` bit GANDALF: the enum member is kept, the
        # macro only expands tokens that are not themselves flags.
        game = game_with(GANDALF="GondorGandalf GondorGandalfGrey")
        assert List[KindOf].convert(game, "HERO GANDALF") == [KindOf.HERO, KindOf.GANDALF]


class TestFlagList:
    def test_single_line_splits_like_a_list(self):
        assert FlagList[Int].convert(Game(), "1 2 3") == [1, 2, 3]

    def test_repeated_key_keeps_the_last_set_and_warns(self):
        # `KindOf` is a whole-set flag field: a second line replaces the first
        # (the engine keeps the last), and the duplication is flagged.
        game = Game()
        assert FlagList[Int].convert(game, ["1 2", "3 4 5"]) == [3, 4, 5]
        assert [code for code, *_ in game._pending_warnings] == ["repeated-flag-field"]


class TestQuotedList:
    def test_keeps_quoted_names_with_spaces_as_single_tokens(self):
        # A list of quote-wrapped map names (e.g. AIBase.GameMapToUseOn): each `"..."` is one
        # element even with internal spaces, rather than splitting at every space.
        value = '"Evil Heroes Map 1 Player" "Helms Deep" "<ANY>"'
        assert QuotedList[MapFile].convert(Game(), value) == [
            '"Evil Heroes Map 1 Player"',
            '"Helms Deep"',
            '"<ANY>"',
        ]

    def test_single_quoted_value_is_a_one_element_list(self):
        assert QuotedList[MapFile].convert(Game(), '"<ANY>"') == ['"<ANY>"']

    def test_repeated_key_concatenates_each_line(self):
        assert QuotedList[MapFile].convert(Game(), ['"Map A"', '"Map B" "Map C"']) == [
            '"Map A"',
            '"Map B"',
            '"Map C"',
        ]


class TestOpenEnums:
    def test_closed_button_border_type(self):
        assert ButtonBorderTypes.convert(Game(), "ACTION") is ButtonBorderTypes.ACTION
        assert ButtonBorderTypes.convert(Game(), "NONE") is None  # metaclass maps none -> None

    def test_closed_engine_sets_resolve_to_members(self):
        # these were once open FakeEnums; they are now closed OpenSAGE enums
        game = Game()
        assert (
            DamageFXTypes.convert(game, "WITCH_KING_MORGUL_BLADE")
            is DamageFXTypes.WITCH_KING_MORGUL_BLADE
        )
        assert LocomotorSetType.convert(game, "SET_MOUNTED") is LocomotorSetType.SET_MOUNTED
        assert (
            AllowedWhenConditions.convert(game, "ATTACK_BUILDINGS")
            is AllowedWhenConditions.ATTACK_BUILDINGS
        )
        with pytest.raises(KeyError):
            LocomotorSetType.convert(game, "SET_NOT_A_REAL_SET")

    def test_data_extensible_sets_accept_any_token(self):
        # the remaining open engine sets keep an unknown token as its raw value
        game = Game()
        assert Stances.convert(game, "GUARD_AGGRESSIVE") == "GUARD_AGGRESSIVE"

    def test_faction_side_set_is_collected_from_player_templates(self):
        # the side vocabulary is data-defined: the union of every PlayerTemplate `Side`
        game = Game()
        game.load_document(
            parse(
                "PlayerTemplate FactionMen\n    Side = Men\nEnd\n"
                "PlayerTemplate FactionCivilian\n    Side = Civilian\nEnd\n",
                file="t",
            ).document
        )
        assert FactionSide.sides(game) == {"Men", "Civilian"}
        assert FactionSide.has(game, "Men")
        assert not FactionSide.has(game, "Atlantis")
        # conversion stays lossless even for an undeclared side
        assert FactionSide.convert(game, "Atlantis") == "Atlantis"


class TestEnumOverridePrefix:
    def test_plus_and_minus_resolve_to_the_same_member(self):
        # `+FLAG`/`-FLAG` are SAGE's add/remove override markers (child objects,
        # map.ini redefinitions); the member named is the same either way.
        game = Game()
        assert KindOf.convert(game, "+INFANTRY") is KindOf.INFANTRY
        assert KindOf.convert(game, "-CAVALRY") is KindOf.CAVALRY

    def test_override_markers_in_a_list_value(self):
        assert List[KindOf].convert(Game(), "+INFANTRY -CAVALRY SELECTABLE") == [
            KindOf.INFANTRY,
            KindOf.CAVALRY,
            KindOf.SELECTABLE,
        ]


class TestWeaponPrefireType:
    def test_prefire_members(self):
        game = Game()
        assert WeaponPrefireType.convert(game, "PER_CLIP") is WeaponPrefireType.PER_CLIP
        assert WeaponPrefireType.convert(game, "PER_POSITION") is WeaponPrefireType.PER_POSITION

    def test_trailing_marker_is_ignored(self):
        # The engine reads the type from the first token; a trailing marker
        # (corpus: `PreAttackType = PER_SHOT *`) is valid and resolves to it.
        game = Game()
        assert WeaponPrefireType.convert(game, "PER_SHOT *") is WeaponPrefireType.PER_SHOT
        assert WeaponPrefireType.convert(game, "PER_SHOT\t*") is WeaponPrefireType.PER_SHOT


class TestDispositions:
    def test_combined_flags_resolve_as_a_list(self):
        # CreateObject.Disposition combines flags on one line.
        flags = List[Dispositions].convert(Game(), "SEND_IT_FLYING BUILDING_CHUNKS LIKE_EXISTING")
        assert flags == [
            Dispositions.SEND_IT_FLYING,
            Dispositions.BUILDING_CHUNKS,
            Dispositions.LIKE_EXISTING,
        ]


class TestObjectFilterRules:
    def test_radius_damage_affects_members(self):
        # Weapon.RadiusDamageAffects: engine filter-rule flags, distinct from Relations.
        rules = List[ObjectFilterRules].convert(Game(), "ALLIES NEUTRALS NOT_SIMILAR")
        assert rules == [
            ObjectFilterRules.ALLIES,
            ObjectFilterRules.NEUTRAL,  # NEUTRALS is an alias of NEUTRAL
            ObjectFilterRules.NOT_SIMILAR,
        ]


class TestScienceRequirements:
    def test_none_is_no_requirement(self):
        assert ScienceRequirements.convert(Game(), "None") == []

    def test_or_separates_alternative_groups(self):
        # SCIENCE_GOOD OR (SCIENCE_DWARVES AND SCIENCE_TowerZwerge)
        groups = ScienceRequirements.convert(Game(), "SCIENCE_GOOD OR SCIENCE_A SCIENCE_B")
        assert groups == [["SCIENCE_GOOD"], ["SCIENCE_A", "SCIENCE_B"]]


class TestNullableReference:
    def test_none_sentinel_resolves_to_none(self):
        assert Nullable["Object"].convert(Game(), "NONE") is None
        assert Nullable["Object"].convert(Game(), "") is None


class TestUpgradeWithDelay:
    def test_upgrade_with_delay(self):
        value = UpgradeWithDelay.convert(Game(), "Upgrade_Drafted Delay:1000")
        assert value.Upgrades == ["Upgrade_Drafted"]
        assert value.Delay == 1000

    def test_several_upgrades_apply_together(self):
        # Every leading non-colon token is an upgrade (the engine's ModifierUpgrade).
        value = UpgradeWithDelay.convert(Game(), "Upgrade_A Upgrade_B Delay:50")
        assert value.Upgrades == ["Upgrade_A", "Upgrade_B"]
        assert value.Delay == 50

    def test_upgrade_without_delay(self):
        value = UpgradeWithDelay.convert(Game(), "Upgrade_Plain")
        assert value.Upgrades == ["Upgrade_Plain"]
        assert value.Delay is None


class TestBannerCarrierPosition:
    def test_unit_type_and_position(self):
        [value] = BannerCarrierPosition.convert(Game(), "UnitType:LAGondorFighter Pos:X:40.0 Y:0.0")
        assert value.UnitType == "LAGondorFighter"
        assert value.Pos == [40.0, 0.0, 0.0]

    def test_repeats_one_entry_per_line(self):
        values = BannerCarrierPosition.convert(
            Game(), ["UnitType:A Pos:X:1 Y:2 Z:3", "UnitType:B Pos:X:4 Y:5"]
        )
        assert [(v.UnitType, v.Pos) for v in values] == [
            ("A", [1.0, 2.0, 3.0]),
            ("B", [4.0, 5.0, 0.0]),
        ]


class TestRespawnRules:
    def test_parses_all_keys(self):
        # AutoSpawn -> bool, Cost/Time -> numbers, Health % -> fraction.
        rules = RespawnRules.convert(Game(), "AutoSpawn:No Cost:1500 Time:60000 Health:100%")
        assert rules.AutoSpawn is False
        assert rules.Cost == 1500
        assert rules.Time == 60000
        assert rules.Health == pytest.approx(1.0)

    def test_cost_resolves_a_macro(self):
        rules = RespawnRules.convert(game_with(ARVEDUI_BUILDCOST=2200), "Cost:ARVEDUI_BUILDCOST")
        assert rules.Cost == 2200

    def test_absent_keys_are_none(self):
        rules = RespawnRules.convert(Game(), "AutoSpawn:Yes")
        assert rules.AutoSpawn is True
        assert rules.Cost is None and rules.Time is None and rules.Health is None


class TestDeathEntry:
    def test_parses_anim_state_time_and_ocl(self):
        # AnimState -> ModelCondition; AnimTime -> number; RiderOCL falls back to its raw name
        # when the list isn't loaded (cross-references resolve against the game's tables).
        entry = DeathEntry.convert(
            Game(), "AnimState:DEATH_2 AnimTime:3000 RiderOCL:OCL_RohirrimSpawnDeadRider"
        )
        assert entry.AnimState.name == "DEATH_2"
        assert entry.AnimTime == 3000
        assert entry.RiderOCL == "OCL_RohirrimSpawnDeadRider"


class TestAttackPriorityTarget:
    def test_target_object_and_priority(self):
        [value] = AttackPriorityTarget.convert(Game(), "GondorFighter 10")
        assert value.Target == "GondorFighter"  # raw name when the object isn't loaded
        assert value.Value == 10

    def test_repeats_one_entry_per_line(self):
        values = AttackPriorityTarget.convert(Game(), ["GondorFighter 10", "GondorArcher 5"])
        assert [(v.Target, v.Value) for v in values] == [("GondorFighter", 10), ("GondorArcher", 5)]


class TestRGBA:
    def test_full_rgba(self):
        assert RGBA.convert(Game(), "R:255 G:128 B:0 A:64") == [255.0, 128.0, 0.0, 64.0]

    def test_missing_alpha_defaults_to_opaque(self):
        assert RGBA.convert(Game(), "R:255 G:255 B:255") == [255.0, 255.0, 255.0, 255.0]


class TestFCurveKey:
    def test_time_value_and_tangents(self):
        [key] = FCurveKey.convert(Game(), "T:100 V:360 I:1 O:2")
        assert (key.T, key.V, key.I, key.O) == (100, 360, 1, 2)

    def test_optional_tangents_are_none(self):
        [key] = FCurveKey.convert(Game(), "T:0 V:.50")
        assert (key.T, key.V) == (0, pytest.approx(0.5))
        assert key.I is None and key.O is None

    def test_repeats_one_entry_per_line(self):
        keys = FCurveKey.convert(Game(), ["T:0 V:0", "T:20 V:100"])
        assert [(k.T, k.V) for k in keys] == [(0, 0), (20, 100)]


class TestScaledObjectFilter:
    def test_bare_multiplier_has_no_filter(self):
        [value] = ScaledObjectFilter.convert(Game(), "50%")
        assert value.Scalar == 0.5
        assert value.ObjectFilter is None

    def test_multiplier_scoped_to_an_object_filter(self):
        # `DamageScalar = 50% NONE +COMMANDCENTER`: percentage then a filter.
        [value] = ScaledObjectFilter.convert(Game(), "50% NONE +COMMANDCENTER")
        assert value.Scalar == 0.5
        assert KindOf.COMMANDCENTER in value.ObjectFilter.inclusion

    def test_tab_between_multiplier_and_filter(self):
        # The data parts the two with a tab (`0.0\tANY +HERO`); it is still a
        # number then a filter, not a malformed Float.
        [value] = ScaledObjectFilter.convert(Game(), "0.0\tANY +HERO +PORTER")
        assert value.Scalar == 0.0
        assert KindOf.HERO in value.ObjectFilter.inclusion

    def test_each_repeated_occurrence_is_kept(self):
        # Repeated DamageScalar lines each scope to their own filter; all apply.
        values = ScaledObjectFilter.convert(Game(), ["50% NONE +INFANTRY", "100% NONE +CAVALRY"])
        assert [v.Scalar for v in values] == [0.5, 1.0]
        assert KindOf.INFANTRY in values[0].ObjectFilter.inclusion
        assert KindOf.CAVALRY in values[1].ObjectFilter.inclusion
