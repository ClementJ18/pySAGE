"""The patch-notes transform: reading the spreadsheet export, the filters, and the BBcode the
two posts come out as. Data-free (the CSVs are written in the test), so it is core-suite."""

from datetime import date

from sage_mods.edain.patch_notes import (
    UNTRANSLATED,
    Note,
    apply_formatting,
    batch_dates,
    output_paths,
    parse_notes,
    read_notes,
    render_notes,
    write_notes,
)

HEADER = "Faction,English,German,Beta,Date\n"


def sheet(tmp_path, body: str, name: str = "Edain 4.8.csv"):
    path = tmp_path / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def note(**kwargs) -> Note:
    fields = {
        "factions": ("Gondor",),
        "english": "a note",
        "german": "eine Notiz",
        "beta": False,
        "date": None,
    }
    fields.update(kwargs)
    return Note(**fields)  # type: ignore[arg-type]


class TestApplyFormatting:
    def test_each_marker_becomes_its_tag(self):
        assert apply_formatting("*a* **b** ***c***") == "[i]a[/i] [b]b[/b] [b][i]c[/i][/b]"

    def test_two_runs_on_one_line_stay_two_runs(self):
        assert apply_formatting("**a** and **b**") == "[b]a[/b] and [b]b[/b]"

    def test_text_without_markers_is_untouched(self):
        assert apply_formatting("Gondor archers cost 300") == "Gondor archers cost 300"


class TestParseNotes:
    def test_a_row_becomes_a_note(self, tmp_path):
        path = sheet(tmp_path, "Gondor,cheaper archers,billigere Bogen,,01/02/2026\n")
        (parsed,) = read_notes(path)
        assert parsed == Note(
            factions=("Gondor",),
            english="cheaper archers",
            german="billigere Bogen",
            beta=False,
            date=date(2026, 2, 1),
        )

    def test_empty_spacer_rows_are_dropped(self, tmp_path):
        path = sheet(tmp_path, ",,,,\nGondor,a,b,,\n,,,,\n")
        assert len(read_notes(path)) == 1

    def test_a_batch_date_carries_back_over_the_rows_above_it(self, tmp_path):
        path = sheet(
            tmp_path,
            "Gondor,newer,neuer,,\nGondor,newest,neuster,,02/02/2026\nGondor,older,alter,,01/02/2026\n",
        )
        assert [n.date for n in read_notes(path)] == [
            date(2026, 2, 2),
            date(2026, 2, 2),
            date(2026, 2, 1),
        ]

    def test_rows_of_the_undated_open_batch_have_none(self, tmp_path):
        path = sheet(tmp_path, "Gondor,dated,x,,01/02/2026\nGondor,still open,y,,\n")
        assert [n.date for n in read_notes(path)] == [date(2026, 2, 1), None]

    def test_a_comma_separated_faction_cell_becomes_several_factions(self, tmp_path):
        path = sheet(tmp_path, '"Gondor, Rohan",a,b,,\n')
        assert read_notes(path)[0].factions == ("Gondor", "Rohan")

    def test_the_beta_column_is_case_insensitive(self, tmp_path):
        path = sheet(tmp_path, "Gondor,a,b,true,\nGondor,c,d,FALSE,\n")
        assert [n.beta for n in read_notes(path)] == [True, False]

    def test_a_missing_column_leaves_the_field_empty(self):
        (parsed,) = parse_notes([{"Faction": "Gondor", "English": "a"}])
        assert parsed.german == "" and parsed.beta is False and parsed.date is None

    def test_an_unparseable_date_keeps_the_batch_below_it(self, tmp_path):
        path = sheet(tmp_path, "Gondor,a,b,,sometime\nGondor,c,d,,01/02/2026\n")
        assert [n.date for n in read_notes(path)] == [date(2026, 2, 1), date(2026, 2, 1)]

    def test_a_bom_from_the_spreadsheet_export_is_tolerated(self, tmp_path):
        path = tmp_path / "notes.csv"
        path.write_text(HEADER + "Gondor,a,b,,\n", encoding="utf-8-sig")
        assert read_notes(path)[0].factions == ("Gondor",)


class TestBatchDates:
    def test_the_recorded_dates_come_back_newest_first(self):
        notes = [
            note(date=date(2026, 1, 15)),
            note(date=date(2026, 2, 2)),
            note(date=date(2026, 2, 1)),
        ]
        assert batch_dates(notes) == (date(2026, 2, 2), date(2026, 2, 1), date(2026, 1, 15))

    def test_a_batch_of_several_notes_is_listed_once(self):
        notes = [note(date=date(2026, 2, 1)), note(date=date(2026, 2, 1))]
        assert batch_dates(notes) == (date(2026, 2, 1),)

    def test_the_undated_open_batch_contributes_no_date(self):
        assert batch_dates([note(date=None)]) == ()

    def test_the_dates_of_a_sheet_are_the_ones_it_records(self, tmp_path):
        path = sheet(tmp_path, "Gondor,a,b,,\nGondor,c,d,,02/02/2026\nGondor,e,f,,01/02/2026\n")
        assert batch_dates(read_notes(path)) == (date(2026, 2, 2), date(2026, 2, 1))


class TestRenderNotes:
    def test_a_faction_becomes_a_heading_and_a_list(self):
        result = render_notes([note(english="cheaper archers", german="billiger")])
        assert result.english == "[u]Gondor[/u]\n[list]\n[li]cheaper archers[/li]\n[/list]\n\n"
        assert result.count == 1 and result.factions == ("Gondor",)

    def test_leading_dashes_nest_the_notes(self):
        notes = [note(english="archers"), note(english="-cost 300"), note(english="--was 350")]
        assert result_lines(render_notes(notes).english) == [
            "[u]Gondor[/u]",
            "[list]",
            "[li]archers",
            "[list]",
            "[li]cost 300",
            "[list]",
            "[li]was 350[/li]",
            "[/list]",
            "[/li]",
            "[/list]",
            "[/li]",
            "[/list]",
        ]

    def test_general_map_and_ai_lead_the_post(self):
        notes = [
            note(factions=("Rohan",)),
            note(factions=("AI",)),
            note(factions=("Angmar",)),
            note(factions=("General",)),
            note(factions=("Map",)),
        ]
        assert render_notes(notes).factions == ("General", "Map", "AI", "Angmar", "Rohan")

    def test_the_german_post_translates_the_headings_it_knows(self):
        result = render_notes([note(factions=("Dwarves",))])
        assert result.english.startswith("[u]Dwarves[/u]")
        assert result.german.startswith("[u]Zwerge[/u]")

    def test_a_note_in_several_factions_appears_under_each(self):
        result = render_notes([note(factions=("Gondor", "Rohan"), english="siege costs less")])
        assert result.english.count("[li]siege costs less[/li]") == 2
        assert result.count == 1  # counted once, listed twice

    def test_an_untranslated_note_is_marked_in_the_other_post(self):
        result = render_notes([note(english="cheaper archers", german="")])
        assert "[li]cheaper archers[/li]" in result.english
        assert f"[li]{UNTRANSLATED} cheaper archers[/li]" in result.german

    def test_beta_notes_are_left_out_unless_asked_for(self):
        notes = [note(english="public"), note(english="beta only", beta=True)]
        assert "beta only" not in render_notes(notes).english
        assert "beta only" in render_notes(notes, beta=True).english

    def test_after_keeps_only_what_came_later_than_that_day(self):
        # The date names the batch already posted, so that batch is itself left out.
        notes = [
            note(english="new", date=date(2026, 2, 2)),
            note(english="same day", date=date(2026, 2, 1)),
            note(english="old", date=date(2026, 1, 1)),
        ]
        kept = render_notes(notes, after=date(2026, 2, 1)).english
        assert "new" in kept
        assert "same day" not in kept and "old" not in kept

    def test_the_undated_open_batch_survives_every_cut_off(self):
        # The newest work sits below the last dated row, its Date cell not yet filled in. It is
        # the latest batch, not the oldest, so no cut-off may drop it.
        notes = [note(english="old", date=date(2026, 1, 1)), note(english="undated", date=None)]
        kept = render_notes(notes, after=date(2099, 1, 1)).english
        assert "undated" in kept and "old" not in kept

    def test_nothing_matching_renders_empty_posts(self):
        result = render_notes([note(beta=True)])
        assert (result.english, result.german, result.count, result.factions) == ("", "", 0, ())


class TestWriteNotes:
    def test_the_posts_are_named_after_the_sheet(self, tmp_path):
        english, german = output_paths(tmp_path, "Edain 4.8")
        assert english.name == "Edain 4.8 - English.txt"
        assert german.name == "Edain 4.8 - German.txt"

    def test_both_files_are_written(self, tmp_path):
        result = render_notes([note(english="cheaper archers", german="billiger")])
        english, german = write_notes(result, tmp_path, "Edain 4.8")
        assert english.read_text(encoding="utf-8") == result.english
        assert german.read_text(encoding="utf-8") == result.german


def result_lines(document: str) -> list[str]:
    return [line for line in document.splitlines() if line]
