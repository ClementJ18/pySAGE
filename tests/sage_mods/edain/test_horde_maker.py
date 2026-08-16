"""The horde formation model: the `HordeContain` block rendered from a list of slots, and read
back out of one. Data-free (every block is written in the test), so it is core-suite."""

from sage_mods.edain.horde_maker import (
    SIZES_COMMENT,
    Slot,
    parse_formation,
    parse_sizes,
    render_formation,
)


def row(unit: str, x: float, *ys: float) -> list[Slot]:
    return [Slot(unit=unit, x=x, y=y) for y in ys]


class TestRenderFormation:
    def test_slots_count_only_the_ranked_soldiers(self):
        slots = [*row("Soldier", 1.0, 1.0, -1.0), Slot("Banner", 1.0, 0.0, banner=True)]
        assert "Slots = 2" in render_formation(slots)

    def test_a_payload_line_per_unit_in_the_order_they_appear(self):
        block = render_formation([*row("Pikemen", 0.0, 1.0, -1.0), *row("Archers", 1.0, 0.0)])
        payload = [line for line in block.splitlines() if line.startswith("InitialPayload")]
        assert payload == ["InitialPayload = Pikemen 2", "InitialPayload = Archers 1"]

    def test_ranks_run_front_to_back_and_left_to_right(self):
        block = render_formation([*row("Soldier", 0.0, 1.0, -1.0), *row("Soldier", 2.0, 1.0, -1.0)])
        ranks = [line for line in block.splitlines() if line.startswith("RankInfo")]
        assert ranks[0].startswith("RankInfo = RankNumber:1 UnitType:Soldier Position:X:2.0 Y:1.0")
        assert "Position:X:2.0 Y:-1.0" in ranks[0]
        assert ranks[1].startswith("RankInfo = RankNumber:2")
        assert "Position:X:0.0 Y:1.0" in ranks[1]

    def test_each_soldier_follows_the_one_at_its_index_in_the_rank_ahead(self):
        block = render_formation([*row("Soldier", 1.0, 1.0, -1.0), *row("Soldier", 0.0, 1.0, -1.0)])
        second = [line for line in block.splitlines() if "RankNumber:2" in line][0]
        assert "Position:X:0.0 Y:1.0 Leader 1 0" in second
        assert "Position:X:0.0 Y:-1.0 Leader 1 1" in second

    def test_the_front_rank_has_no_leaders(self):
        block = render_formation(row("Soldier", 1.0, 1.0, -1.0))
        assert "Leader" not in block

    def test_a_rank_longer_than_the_one_ahead_leaves_its_extras_leaderless(self):
        block = render_formation([*row("Soldier", 1.0, 0.0), *row("Soldier", 0.0, 1.0, -1.0)])
        second = [line for line in block.splitlines() if "RankNumber:2" in line][0]
        assert second.count("Leader") == 1

    def test_rank_numbers_run_on_across_the_units(self):
        block = render_formation([*row("Pikemen", 1.0, 0.0), *row("Archers", 0.0, 0.0)])
        ranks = [line for line in block.splitlines() if line.startswith("RankInfo")]
        assert "RankNumber:1 UnitType:Pikemen" in ranks[0]
        assert "RankNumber:2 UnitType:Archers" in ranks[1]

    def test_the_banner_carrier_gets_its_own_two_lines(self):
        block = render_formation([Slot("Banner", 2.0, 0.5, banner=True), *row("Soldier", 0.0, 0.0)])
        assert "BannerCarriersAllowed = Banner" in block
        assert "BannerCarrierPosition = UnitType:Banner Pos:X:2.0 Y:0.5" in block
        assert "UnitType:Banner Position" not in block  # never a rank of its own

    def test_a_formation_without_a_banner_carrier_writes_neither_line(self):
        block = render_formation(row("Soldier", 0.0, 0.0))
        assert "Banner" not in block

    def test_a_second_banner_carrier_is_ranked_like_any_other_soldier(self):
        block = render_formation(
            [Slot("Banner", 1.0, 0.0, banner=True), Slot("Banner", 0.0, 0.0, banner=True)]
        )
        assert block.count("BannerCarrierPosition") == 1
        assert "UnitType:Banner Position:X:0.0 Y:0.0" in block

    def test_an_empty_formation_still_renders_a_slot_count(self):
        assert render_formation([]).startswith("Slots = 0")


class TestParseFormation:
    def test_positions_are_read_off_a_rank(self):
        slots = parse_formation("RankInfo = RankNumber:1 UnitType:Soldier Position:X:1.0 Y:-2.5")
        assert slots == [Slot("Soldier", 1.0, -2.5)]

    def test_a_leader_between_two_positions_is_not_mistaken_for_one(self):
        line = "RankInfo = RankNumber:2 UnitType:S Position:X:0.0 Y:1.0 Leader 1 0 "
        line += "Position:X:0.0 Y:-1.0 Leader 1 1"
        assert parse_formation(line) == [Slot("S", 0.0, 1.0), Slot("S", 0.0, -1.0)]

    def test_the_banner_carrier_line_is_read_as_the_banner(self):
        slots = parse_formation("BannerCarrierPosition = UnitType:Banner Pos:X:2.0 Y:0.0")
        assert slots == [Slot("Banner", 2.0, 0.0, banner=True)]

    def test_the_rest_of_a_horde_contain_is_ignored(self):
        block = """
            Behavior = HordeContain ModuleTag_04
                Slots = 1
                InitialPayload = Soldier 1
                BannerCarriersAllowed = Banner
                RankInfo = RankNumber:1 UnitType:Soldier Position:X:0.0 Y:0.0
            End
        """
        assert parse_formation(block) == [Slot("Soldier", 0.0, 0.0)]

    def test_comments_are_stripped_before_a_line_is_read(self):
        block = (
            "; RankInfo = RankNumber:1 UnitType:Ghost Position:X:9.0 Y:9.0\n"
            "RankInfo = RankNumber:1 UnitType:Soldier Position:X:0.0 Y:0.0 ;// the front rank\n"
        )
        assert parse_formation(block) == [Slot("Soldier", 0.0, 0.0)]

    def test_a_malformed_rank_is_skipped_rather_than_raising(self):
        block = "RankInfo = RankNumber:1 Position:X:0.0 Y:0.0\nRankInfo = UnitType:S nonsense\n"
        assert parse_formation(block) == []

    def test_nothing_to_read_is_an_empty_list(self):
        assert parse_formation("") == []


class TestSizes:
    def test_the_diameters_open_the_block_as_a_comment(self):
        block = render_formation(row("Soldier", 0.0, 0.0), {"Soldier": 8.0})
        assert block.startswith(f"{SIZES_COMMENT} Soldier=8.0\n")

    def test_a_formation_written_without_diameters_carries_no_comment(self):
        assert SIZES_COMMENT not in render_formation(row("Soldier", 0.0, 0.0))
        assert SIZES_COMMENT not in render_formation(row("Soldier", 0.0, 0.0), {})

    def test_the_comment_is_read_back_as_the_diameters(self):
        text = f"{SIZES_COMMENT} Pikemen=8.0 Archers=6.5\nSlots = 2\n"
        assert parse_sizes(text) == {"Pikemen": 8.0, "Archers": 6.5}

    def test_a_block_without_the_comment_reports_no_diameters(self):
        assert parse_sizes("RankInfo = RankNumber:1 UnitType:S Position:X:0.0 Y:0.0") == {}

    def test_a_token_that_is_not_a_pair_is_skipped(self):
        text = f"{SIZES_COMMENT} Pikemen=8.0 nonsense Archers=wide Ghosts=\n"
        assert parse_sizes(text) == {"Pikemen": 8.0}

    def test_the_comment_is_not_read_as_a_rank(self):
        block = render_formation(row("Soldier", 0.0, 0.0), {"Soldier": 8.0})
        assert parse_formation(block) == [Slot("Soldier", 0.0, 0.0)]


class TestRoundTrip:
    def test_a_rendered_block_reads_back_as_the_slots_it_was_written_from(self):
        slots = [
            Slot("Banner", 2.0, 0.0, banner=True),
            *row("Pikemen", 2.0, 1.0, -1.0),
            *row("Pikemen", 1.0, 1.0, 0.0, -1.0),
            *row("Archers", 0.0, 0.5, -0.5),
        ]
        assert set(parse_formation(render_formation(slots))) == set(slots)

    def test_a_read_block_renders_back_to_itself(self):
        block = render_formation([*row("Soldier", 1.0, 1.0, -1.0), *row("Soldier", 0.0, 1.0, -1.0)])
        assert render_formation(parse_formation(block)) == block

    def test_the_diameters_survive_the_trip_with_the_positions(self):
        slots = [*row("Pikemen", 1.0, 0.0), *row("Archers", 0.0, 0.0)]
        sizes = {"Pikemen": 8.0, "Archers": 6.5}
        block = render_formation(slots, sizes)
        assert parse_formation(block) == slots
        assert parse_sizes(block) == sizes
