"""Unit tests for sage_ini.strings (the localization string-table loader)."""

from sage_ini.parser.location import Span
from sage_ini.strings import (
    load_string_locations,
    load_strings,
    parse_csv,
    parse_csv_spans,
    parse_str,
    parse_str_spans,
)


class TestParseStr:
    def test_reads_label_value_end_blocks(self):
        text = 'OBJECT:Fighter\n"Orc Warrior"\nEND\nCONTROLBAR:Build\n"Build"\nEND\n'
        assert parse_str(text) == {"OBJECT:Fighter": "Orc Warrior", "CONTROLBAR:Build": "Build"}

    def test_joins_multiline_values(self):
        assert parse_str('LABEL\n"first "\n"second"\nEND\n') == {"LABEL": "first second"}


class TestParseCsv:
    def test_reads_label_and_english_column(self):
        text = (
            "Object Name;German Description;English Description\n"
            "APT:armiestitle;Armeen;Armies\n"
            "APT:send;SENDEN;SEND\n"
        )
        # The header row's first column has no colon, so it is skipped; the
        # English (last) column becomes the value.
        assert parse_csv(text) == {"APT:armiestitle": "Armies", "APT:send": "SEND"}

    def test_skips_blank_and_headerless_lines(self):
        text = "APT:a;de;A\n\nnot a label row\nAPT:b;de;B\n"
        assert parse_csv(text) == {"APT:a": "A", "APT:b": "B"}


class TestLoadStrings:
    def test_loads_str_files_under_root(self, tmp_path):
        (tmp_path / "lotr.str").write_text('OBJECT:Foo\n"Foo Text"\nEND\n', encoding="utf-8")
        assert load_strings(tmp_path) == {"OBJECT:Foo": "Foo Text"}

    def test_loads_edain_lotr_csv(self, tmp_path):
        (tmp_path / "Lotr.csv").write_text(
            "Object Name;German Description;English Description\nAPT:send;SENDEN;SEND\n",
            encoding="utf-8",
        )
        assert load_strings(tmp_path) == {"APT:send": "SEND"}

    def test_root_overrides_overlay(self, tmp_path):
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        base.mkdir()
        mod.mkdir()
        (base / "lotr.str").write_text('OBJECT:Foo\n"Base"\nEND\n', encoding="utf-8")
        (mod / "lotr.str").write_text('OBJECT:Foo\n"Mod"\nEND\n', encoding="utf-8")

        # mod is the root, base the overlay: the mod's text wins.
        assert load_strings(mod, (base,)) == {"OBJECT:Foo": "Mod"}


class TestStringSpans:
    def test_parse_str_spans_point_at_the_label_line(self):
        text = 'OBJECT:Fighter\n"Orc Warrior"\nEND\nCONTROLBAR:Build\n"Build"\nEND\n'
        spans = parse_str_spans(text, "lotr.str")
        assert spans["OBJECT:Fighter"] == Span("lotr.str", 1, 1)
        assert spans["CONTROLBAR:Build"] == Span("lotr.str", 4, 4)

    def test_parse_csv_spans_point_at_the_row(self):
        text = (
            "Object Name;German Description;English Description\n"
            "APT:armiestitle;Armeen;Armies\n"
            "APT:send;SENDEN;SEND\n"
        )
        spans = parse_csv_spans(text, "Lotr.csv")
        # The header row is skipped, so the first label sits on line 2.
        assert spans["APT:armiestitle"] == Span("Lotr.csv", 2, 2)
        assert spans["APT:send"] == Span("Lotr.csv", 3, 3)

    def test_load_string_locations_resolves_a_str_file(self, tmp_path):
        path = tmp_path / "lotr.str"
        path.write_text('OBJECT:Foo\n"Foo Text"\nEND\n', encoding="utf-8")
        assert load_string_locations(tmp_path) == {"OBJECT:Foo": Span(str(path), 1, 1)}

    def test_load_string_locations_skips_map_scoped_tables(self, tmp_path):
        (tmp_path / "maps" / "MyMap").mkdir(parents=True)
        (tmp_path / "maps" / "MyMap" / "map.str").write_text(
            'MAP:Label\n"Map"\nEND\n', encoding="utf-8"
        )
        assert load_string_locations(tmp_path) == {}
