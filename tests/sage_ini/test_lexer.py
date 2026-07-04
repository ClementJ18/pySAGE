"""Unit tests for sage_ini.parser.lexer.

Comment grammar (engine-faithful, see PLAN.md corpus findings): `;`, `//`, and
`--` each start a comment at any position in a line; the first marker wins;
there is no quote or URL awareness. Every rule here is pinned by a real line
shape from the game-data corpus.
"""

from sage_ini.parser.lexer import Line, tokenize
from sage_ini.parser.location import Span


def single(text: str) -> Line:
    lines = tokenize(text, file="test.ini")
    assert len(lines) == 1
    return lines[0]


class TestBasicLines:
    def test_attribute_line_passes_through(self):
        line = single("BuildCost = 300")

        assert line.content == "BuildCost = 300"
        assert line.comment is None
        assert line.raw == "BuildCost = 300"

    def test_indentation_stripped_from_content_kept_in_raw(self):
        line = single("\tBuildCost  =  300  ")

        assert line.content == "BuildCost  =  300"
        assert line.raw == "\tBuildCost  =  300  "

    def test_positions_are_one_based_and_file_is_recorded(self):
        lines = tokenize("Object Foo\n  BuildCost = 1\nEnd\n", file="unit.ini")

        assert [line.number for line in lines] == [1, 2, 3]
        assert all(line.file == "unit.ini" for line in lines)
        assert lines[1].span == Span("unit.ini", 2, 2)

    def test_line_count_matches_input_including_blanks(self):
        lines = tokenize("a\n\n\nb\n")

        assert len(lines) == 4
        assert lines[1].is_blank and lines[2].is_blank

    def test_blank_line_has_empty_content_and_no_comment(self):
        line = single("   \t  ")

        assert line.content == ""
        assert line.comment is None
        assert line.is_blank


class TestCommentMarkers:
    def test_semicolon_full_line_comment(self):
        line = single("; Moved from MordorInfantry.INI Aug 24 2005")

        assert line.content == ""
        assert line.comment == "; Moved from MordorInfantry.INI Aug 24 2005"
        assert not line.is_blank

    def test_double_slash_full_line_comment(self):
        line = single("// this is required for garrisoned objects")

        assert line.content == ""
        assert line.comment == "// this is required for garrisoned objects"

    def test_decorative_banner_is_a_comment(self):
        line = single(";//////////////////////////////")

        assert line.content == ""
        assert line.comment == ";//////////////////////////////"

    def test_trailing_semicolon_comment(self):
        line = single("WadingParticleSys = WaterRipplesTrail  ; used when wading")

        assert line.content == "WadingParticleSys = WaterRipplesTrail"
        assert line.comment == "; used when wading"

    def test_trailing_double_slash_comment(self):
        line = single("OkToChangeModelColor = Yes // colorable")

        assert line.content == "OkToChangeModelColor = Yes"
        assert line.comment == "// colorable"

    def test_glued_double_slash_is_a_comment(self):
        # corpus: createaheropowers.inc
        line = single("SpecialPowerTemplate = SpecialAbilityATeleportToCaster//older name HACK!")

        assert line.content == "SpecialPowerTemplate = SpecialAbilityATeleportToCaster"
        assert line.comment == "//older name HACK!"

    def test_glued_empty_double_slash_comment(self):
        # corpus: createahero.ini `ShadowSizeX = 20//`
        line = single("ShadowSizeX = 20//")

        assert line.content == "ShadowSizeX = 20"
        assert line.comment == "//"

    def test_double_dash_is_a_comment(self):
        # corpus: lastallianceunits.ini
        line = single("FastHitsResetReaction = Yes    If set -- when hits occur faster")

        assert line.content == "FastHitsResetReaction = Yes    If set"
        assert line.comment == "-- when hits occur faster"

    def test_first_marker_wins(self):
        # corpus: skirmishaidata.ini `;//When the AI decides...`
        line = single("EconomyUpgradeProbability = 1 : 1050\t;//When the AI decides")

        assert line.content == "EconomyUpgradeProbability = 1 : 1050"
        assert line.comment == ";//When the AI decides"

    def test_url_is_truncated_like_the_engine_does(self):
        # corpus: webpages.ini — the engine has no URL awareness
        line = single("URL = http://www.ea.com")

        assert line.content == "URL = http:"
        assert line.comment == "//www.ea.com"


class TestNonComments:
    def test_single_slash_in_path_is_not_a_comment(self):
        line = single("ButtonImage = Art/Textures/button.tga")

        assert line.content == "ButtonImage = Art/Textures/button.tga"
        assert line.comment is None

    def test_single_dash_negative_number_is_not_a_comment(self):
        line = single("Offset = X:-12.0 Y:-5.0 Z:0.0")

        assert line.content == "Offset = X:-12.0 Y:-5.0 Z:0.0"
        assert line.comment is None

    def test_define_directive_is_content(self):
        line = single("#define STRONG_DAMAGE 120")

        assert line.content == "#define STRONG_DAMAGE 120"
        assert line.comment is None

    def test_include_directive_is_content(self):
        line = single('#include "..\\Common\\LivingWorldDefaultRTSSettings.inc"')

        assert line.content == '#include "..\\Common\\LivingWorldDefaultRTSSettings.inc"'
        assert line.comment is None

    def test_multiply_expression_is_content(self):
        line = single("Damage = #MULTIPLY( STRONG_DAMAGE 1.5 )")

        assert line.content == "Damage = #MULTIPLY( STRONG_DAMAGE 1.5 )"
        assert line.comment is None

    def test_macro_reference_in_value_is_content(self):
        # corpus: createaheroanims.inc
        line = single("AnimationName = #(MODEL)_U_SPCE")

        assert line.content == "AnimationName = #(MODEL)_U_SPCE"
        assert line.comment is None


class TestTokenizeShape:
    def test_default_filename(self):
        assert tokenize("End")[0].file == "<string>"

    def test_empty_text_yields_no_lines(self):
        assert tokenize("") == []

    def test_trailing_newline_does_not_add_phantom_line(self):
        assert len(tokenize("End\n")) == 1

    def test_commented_out_include_is_a_comment(self):
        # corpus: wotrscenario001.inc `//#include "..."`
        line = single('//#include "..\\Common\\LivingWorldCities.inc"')

        assert line.content == ""
        assert line.comment == '//#include "..\\Common\\LivingWorldCities.inc"'
