"""Build-order extraction (filtering + introduction-order + depth), prefix-tree aggregation,
pruning, and opening extraction. Synthetic PlayerStats/StatEvent only - no replay parsing."""

from sage_replay.build_orders import (
    BUILD_ORDER_CATEGORIES,
    BuildNode,
    BuildStep,
    build_sequence,
    build_tree,
    insert,
    new_root,
    openings,
    prune,
)
from sage_replay.stats import PlayerStats, StatEvent


def _stats(events: list[StatEvent]) -> PlayerStats:
    return PlayerStats(player="P", events=events)


def test_build_order_categories():
    assert BUILD_ORDER_CATEGORIES == {"buildings", "units", "heroes", "sciences"}


def test_build_sequence_filters_categories_and_preserves_order():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "powers", "SomePower"),  # dropped
        StatEvent(3.0, "units", "OrcHorde"),
        StatEvent(4.0, "upgrades", "Upgrade_Blades"),  # dropped
        StatEvent(5.0, "heroes", "Gothmog"),
        StatEvent(6.0, "other", "CPObject"),  # dropped
        StatEvent(7.0, "sciences", "SCIENCE_One"),
        StatEvent(8.0, "combines", "horde combine"),  # dropped
    ]
    steps = build_sequence(_stats(events))
    assert [(s.category, s.label) for s in steps] == [
        ("buildings", "Farm"),
        ("units", "OrcHorde"),
        ("heroes", "Gothmog"),
        ("sciences", "SCIENCE_One"),
    ]
    assert all(s.count == 1 for s in steps)


def test_build_sequence_open_step_counts_consecutive_orders():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Farm"),
        StatEvent(3.0, "buildings", "Farm"),
    ]
    steps = build_sequence(_stats(events))
    assert len(steps) == 1
    assert steps[0] == BuildStep("Farm", "buildings", 3, 1.0)


def test_build_sequence_late_repeat_is_filler_not_a_new_step():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Barracks"),
        StatEvent(3.0, "buildings", "Farm"),  # already introduced, no longer open: filler
    ]
    steps = build_sequence(_stats(events))
    assert [(s.label, s.count) for s in steps] == [("Farm", 1), ("Barracks", 1)]


def test_build_sequence_count_reads_introduction_to_next_step():
    # Farm, Farm, Barracks, Farm, Peasants -> Farm x2, Barracks x1, Peasants x1: the count is
    # the orders of a thing between its introduction and the next new step; the second farm
    # wave (event 4) neither re-appears as a step nor disturbs anything.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Farm"),
        StatEvent(3.0, "buildings", "Barracks"),
        StatEvent(4.0, "buildings", "Farm"),
        StatEvent(5.0, "units", "Peasants"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.label, s.count) for s in steps] == [("Farm", 2), ("Barracks", 1), ("Peasants", 1)]
    assert steps[0].seconds == 1.0


def test_build_sequence_filler_does_not_close_the_open_count_window():
    # An interleaved filler order is ignored entirely: the old Farm at event 3 must not stop
    # the still-open Peasants step from counting its second order at event 4.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "units", "Peasants"),
        StatEvent(3.0, "buildings", "Farm"),  # filler: Peasants stays open
        StatEvent(4.0, "units", "Peasants"),
        StatEvent(5.0, "units", "Archers"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.label, s.count) for s in steps] == [("Farm", 1), ("Peasants", 2), ("Archers", 1)]


def test_build_sequence_late_filler_repeat_shares_one_tree_path():
    base = [
        StatEvent(1.0, "buildings", "Barracks"),
        StatEvent(2.0, "heroes", "Gildor"),
        StatEvent(3.0, "buildings", "Farm"),
        StatEvent(4.0, "units", "BladeMasters"),
    ]
    with_refill = base + [StatEvent(5.0, "buildings", "Farm")]  # a second farm wave
    steps_a = build_sequence(_stats(base))
    steps_b = build_sequence(_stats(with_refill))
    assert steps_a == steps_b  # the filler repeat neither adds a step nor forks the branch

    root = new_root()
    insert(root, steps_a, "won")
    insert(root, steps_b, "lost")
    paths = openings(root)
    assert len(paths) == 1  # one shared path with both games on it
    assert paths[0][-1].games == 2


def test_build_sequence_relabels_fortress_hero_slots():
    events = [StatEvent(10.0, "fortress_hero_slots", 4)]
    steps = build_sequence(_stats(events))
    assert steps == [BuildStep("fortress hero (command slot 4)", "heroes", 1, 10.0)]


def test_build_sequence_depth_counts_introductions():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Farm"),  # bumps the open Farm step, not an introduction
        StatEvent(3.0, "buildings", "Barracks"),
        StatEvent(4.0, "units", "OrcHorde"),
    ]
    steps = build_sequence(_stats(events), depth=2)
    assert [(s.label, s.count) for s in steps] == [("Farm", 2), ("Barracks", 1)]


def test_build_sequence_depth_last_step_accumulates_until_next_introduction():
    # Extraction stops where the (depth+1)-th introduction would occur, so the depth-th step
    # keeps counting until then - including through filler - but not past the stop.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Barracks"),
        StatEvent(3.0, "buildings", "Barracks"),
        StatEvent(4.0, "buildings", "Farm"),  # filler: ignored, Barracks stays open
        StatEvent(5.0, "buildings", "Barracks"),
        StatEvent(6.0, "buildings", "Stables"),  # would-be third introduction: stop here
        StatEvent(7.0, "buildings", "Barracks"),  # past the stop: never counted
    ]
    steps = build_sequence(_stats(events), depth=2)
    assert [(s.label, s.count) for s in steps] == [("Farm", 1), ("Barracks", 3)]


def test_build_sequence_depth_zero_is_unlimited():
    events = [StatEvent(float(i), "buildings", f"Building{i}") for i in range(20)]
    steps = build_sequence(_stats(events), depth=0)
    assert len(steps) == 20


def test_build_sequence_pair_identity_independent_of_interleaving():
    # A build's identity is the pair (eco order, science order); when a game's building and
    # its science purchase swap which happened first, the extracted sequence is unaffected -
    # each event keeps its own clock, only their relative order in the timeline swaps.
    building_then_science = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "sciences", "SCIENCE_A"),
    ]
    science_then_building = [
        StatEvent(2.0, "sciences", "SCIENCE_A"),
        StatEvent(1.0, "buildings", "Farm"),
    ]
    steps_a = build_sequence(_stats(building_then_science))
    steps_b = build_sequence(_stats(science_then_building))
    assert steps_a == steps_b

    root = new_root()
    insert(root, steps_a, "won")
    insert(root, steps_b, "lost")
    paths = openings(root)
    assert len(paths) == 1  # one shared tree path, not two
    assert paths[0][-1].games == 2


def test_build_sequence_canonical_form_sciences_after_eco_regardless_of_clock():
    # The science fires first on the clock, but the canonical form is eco-then-sciences, not
    # chronological - identity, not chronology.
    events = [
        StatEvent(1.0, "sciences", "SCIENCE_A"),
        StatEvent(5.0, "buildings", "Farm"),
        StatEvent(10.0, "buildings", "Barracks"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.category, s.label) for s in steps] == [
        ("buildings", "Farm"),
        ("buildings", "Barracks"),
        ("sciences", "SCIENCE_A"),
    ]


def test_build_sequence_science_does_not_close_eco_window():
    # A science purchase never competed for the resource pool, so it never closes the Farm
    # step's counting window: Farm, SCIENCE, Farm reads Farm x2 then the science.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "sciences", "SCIENCE_A"),
        StatEvent(3.0, "buildings", "Farm"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.category, s.label, s.count) for s in steps] == [
        ("buildings", "Farm", 2),
        ("sciences", "SCIENCE_A", 1),
    ]


def test_build_sequence_science_amid_farm_run_reads_farm_x3():
    # The truer reading of the side benefit: with the streams split, Farm, Farm, SCIENCE, Farm
    # is Farm x3 - the science never competed for the resource pool that the Farm window tracks.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Farm"),
        StatEvent(3.0, "sciences", "SCIENCE_A"),
        StatEvent(4.0, "buildings", "Farm"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.category, s.label, s.count) for s in steps] == [
        ("buildings", "Farm", 3),
        ("sciences", "SCIENCE_A", 1),
    ]


def test_build_sequence_eco_does_not_close_science_window():
    # Symmetrically: an eco order between two of the same science leaves the science step's
    # window open. Whether a game can actually repeat-buy one science is beside the point - the
    # window rule applies mechanically to whatever the science stream sees.
    events = [
        StatEvent(1.0, "sciences", "SCIENCE_A"),
        StatEvent(2.0, "buildings", "Farm"),
        StatEvent(3.0, "sciences", "SCIENCE_A"),
    ]
    steps = build_sequence(_stats(events))
    assert [(s.category, s.label, s.count) for s in steps] == [
        ("buildings", "Farm", 1),
        ("sciences", "SCIENCE_A", 2),
    ]


def test_build_sequence_depth_caps_eco_introductions_only():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "buildings", "Barracks"),  # a second eco introduction: capped out
        StatEvent(3.0, "sciences", "SCIENCE_A"),
    ]
    steps = build_sequence(_stats(events), depth=1)
    assert [(s.category, s.label) for s in steps] == [
        ("buildings", "Farm"),
        ("sciences", "SCIENCE_A"),
    ]


def test_build_sequence_science_depth_caps_science_introductions_only():
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "sciences", "SCIENCE_A"),
        StatEvent(3.0, "sciences", "SCIENCE_B"),  # a second science introduction: capped out
    ]
    steps = build_sequence(_stats(events), science_depth=1)
    assert [(s.category, s.label) for s in steps] == [
        ("buildings", "Farm"),
        ("sciences", "SCIENCE_A"),
    ]


def test_build_sequence_depth_stop_accumulates_through_other_stream_events():
    # The eco stream's depth-stop rule holds exactly as in the single-stream case, just scoped to
    # its own events: the still-open Farm step keeps counting through an interleaved science
    # event, right up to eco's own next-would-be introduction (Barracks) - past which nothing
    # more is counted, in either stream's events.
    events = [
        StatEvent(1.0, "buildings", "Farm"),
        StatEvent(2.0, "sciences", "SCIENCE_A"),  # other stream: does not disturb Farm's window
        StatEvent(3.0, "buildings", "Farm"),  # still pre-stop: bumps the open Farm step
        StatEvent(4.0, "buildings", "Barracks"),  # would-be 2nd eco introduction: stop here
        StatEvent(5.0, "buildings", "Farm"),  # past the stop: never counted
    ]
    steps = build_sequence(_stats(events), depth=1)
    assert [(s.category, s.label, s.count) for s in steps] == [
        ("buildings", "Farm", 2),
        ("sciences", "SCIENCE_A", 1),
    ]


def test_build_sequence_depth_and_science_depth_zero_are_unlimited():
    events = [StatEvent(float(i), "buildings", f"Building{i}") for i in range(15)]
    events += [StatEvent(100.0 + i, "sciences", f"Science{i}") for i in range(6)]
    steps = build_sequence(_stats(events), depth=0, science_depth=0)
    assert len(steps) == 21


def test_insert_shared_prefix_then_diverging_and_root_counts_empty_game():
    root = new_root()
    farm = BuildStep("Farm", "buildings", 1, 10.0)
    barracks = BuildStep("Barracks", "buildings", 1, 20.0)
    stables = BuildStep("Stables", "buildings", 1, 25.0)

    insert(root, [farm, barracks], "won")
    insert(root, [farm, stables], "lost")
    insert(root, [], "won")  # empty sequence still counts at the root

    assert root.games == 3
    assert root.wins == 2
    assert root.losses == 1
    assert len(root.children) == 1

    farm_node = root.children[("buildings", "Farm")]
    assert farm_node.games == 2
    assert farm_node.wins == 1
    assert farm_node.losses == 1
    assert farm_node.counts == [1, 1]
    assert farm_node.times == [10.0, 10.0]
    assert len(farm_node.children) == 2

    barracks_node = farm_node.children[("buildings", "Barracks")]
    assert barracks_node.games == 1
    assert barracks_node.wins == 1
    assert barracks_node.losses == 0
    assert barracks_node.counts == [1]
    assert barracks_node.times == [20.0]

    stables_node = farm_node.children[("buildings", "Stables")]
    assert stables_node.games == 1
    assert stables_node.losses == 1


def test_insert_accumulates_counts_and_times_per_game():
    root = new_root()
    farm3 = BuildStep("Farm", "buildings", 3, 5.0)
    farm1 = BuildStep("Farm", "buildings", 1, 7.0)
    insert(root, [farm3], "won")
    insert(root, [farm1], "lost")
    farm_node = root.children[("buildings", "Farm")]
    assert farm_node.counts == [3, 1]
    assert farm_node.times == [5.0, 7.0]


def test_insert_ignores_undetermined_outcome():
    root = new_root()
    insert(root, [BuildStep("Farm", "buildings", 1, 1.0)], "undetermined")
    assert root.wins == 0
    assert root.losses == 0
    farm_node = root.children[("buildings", "Farm")]
    assert farm_node.wins == 0
    assert farm_node.losses == 0
    assert farm_node.games == 1


def _insert_many(root, steps: list[BuildStep], n: int, outcome: str = "won") -> None:
    for _ in range(n):
        insert(root, steps, outcome)


def test_prune_enforces_min_games_and_min_share():
    root = new_root()
    farm = BuildStep("Farm", "buildings", 1, 1.0)
    rare = BuildStep("Rare", "buildings", 1, 1.0)
    # 10 games total at the root. Farm: 5 games (share 0.5, passes both). Rare: 2 games
    # (below min_games=3 even though its own share 0.2 would pass min_share=0.10 alone).
    _insert_many(root, [farm], 5)
    _insert_many(root, [rare], 2)
    _insert_many(root, [], 3)  # padding games with an empty sequence

    prune(root, min_games=3, min_share=0.10)

    assert ("buildings", "Farm") in root.children
    assert ("buildings", "Rare") not in root.children


def test_prune_min_share_drops_a_child_above_min_games_but_below_share():
    root = new_root()
    small_share = BuildStep("SmallShare", "buildings", 1, 1.0)
    # 100 games total; 4 games passed through this child - above min_games=3, but its share
    # (0.04) is below min_share=0.10, so the effective threshold (max(3, 10)) drops it.
    _insert_many(root, [small_share], 4)
    _insert_many(root, [], 96)

    prune(root, min_games=3, min_share=0.10)

    assert ("buildings", "SmallShare") not in root.children


def test_prune_cascades_dropped_subtree_and_prunes_survivors_against_their_own_games():
    root = new_root()
    farm = BuildStep("Farm", "buildings", 1, 1.0)
    common_child = BuildStep("Barracks", "buildings", 1, 2.0)
    rare_grandchild = BuildStep("RareUnit", "units", 1, 3.0)
    rare_top = BuildStep("Rare", "buildings", 1, 1.0)
    rare_top_child = BuildStep("ShouldBeGone", "units", 1, 2.0)

    # Farm branch: 8 games total, all with Barracks; only 1 of those goes on to RareUnit
    # (share of Barracks's own 8 games is 0.125 < min_share*Barracks -> actually below
    # min_games=3, so RareUnit is pruned from under a surviving Barracks).
    for _ in range(7):
        insert(root, [farm, common_child], "won")
    insert(root, [farm, common_child, rare_grandchild], "won")

    # Rare branch: only 2 games total at the root - dropped outright, taking its child with it.
    _insert_many(root, [rare_top, rare_top_child], 2)

    prune(root, min_games=3, min_share=0.10)

    assert ("buildings", "Rare") not in root.children  # whole rare branch gone
    assert ("buildings", "Farm") in root.children
    farm_node = root.children[("buildings", "Farm")]
    assert ("buildings", "Barracks") in farm_node.children
    barracks_node = farm_node.children[("buildings", "Barracks")]
    # RareUnit had only 1 of Barracks's 8 games -> below min_games=3, pruned.
    assert ("units", "RareUnit") not in barracks_node.children


def test_openings_orders_by_games_desc_then_labels_and_respects_limit():
    root = new_root()
    a = BuildStep("A", "buildings", 1, 1.0)
    b = BuildStep("B", "buildings", 1, 1.0)
    c = BuildStep("C", "buildings", 1, 1.0)
    _insert_many(root, [a], 5)
    _insert_many(root, [b], 8)
    _insert_many(root, [c], 8)  # ties with b on games -> broken by label

    paths = openings(root, limit=10)
    labels = [[n.label for n in path] for path in paths]
    assert labels == [["B"], ["C"], ["A"]]

    limited = openings(root, limit=2)
    assert [[n.label for n in path] for path in limited] == [["B"], ["C"]]


def test_openings_returns_full_paths_excluding_root_and_leaves_only():
    root = new_root()
    farm = BuildStep("Farm", "buildings", 1, 1.0)
    barracks = BuildStep("Barracks", "buildings", 1, 2.0)
    _insert_many(root, [farm, barracks], 5)

    paths = openings(root)
    assert len(paths) == 1
    path = paths[0]
    assert [n.label for n in path] == ["Farm", "Barracks"]
    # A leaf is a node with no children; Barracks is the leaf here.
    assert path[-1].children == {}


def test_openings_empty_tree_returns_empty_list():
    assert openings(new_root()) == []


def test_to_dict_shape_children_list_and_none_medians():
    root = new_root()
    insert(root, [BuildStep("Farm", "buildings", 2, 30.0)], "won")
    payload = root.to_dict()
    assert payload["label"] == ""
    assert payload["category"] == ""
    assert isinstance(payload["children"], list)
    # The root itself never collects counts/times (only its children do along `insert`'s walk),
    # so its median is always undefined even though it has a decided win/loss record.
    assert payload["win_rate"] == 1.0
    assert payload["median_seconds"] is None

    undetermined_root = new_root()
    insert(undetermined_root, [], "undetermined")
    assert undetermined_root.to_dict()["win_rate"] is None  # undecided -> None

    farm_payload = payload["children"][0]
    assert farm_payload["label"] == "Farm"
    assert farm_payload["category"] == "buildings"
    assert farm_payload["games"] == 1
    assert farm_payload["wins"] == 1
    assert farm_payload["losses"] == 0
    assert farm_payload["win_rate"] == 1.0
    assert farm_payload["median_seconds"] == 30.0
    assert farm_payload["median_count"] == 2
    assert farm_payload["children"] == []
    # No science ever rode this game, so both annotations are empty lists (not missing keys).
    assert farm_payload["sciences_by_step"] == []
    assert farm_payload["sciences_taken"] == []


def test_win_rate_and_median_properties():
    root = new_root()
    step = BuildStep("Farm", "buildings", 1, 10.0)
    insert(root, [step], "won")
    insert(root, [step], "won")
    insert(root, [step], "lost")
    insert(root, [step], "undetermined")
    node = root.children[("buildings", "Farm")]
    assert node.decided == 3
    assert node.win_rate == 2 / 3
    assert node.median_seconds == 10.0
    assert node.median_count == 1

    empty = new_root()
    assert empty.win_rate is None
    assert empty.median_seconds is None
    assert empty.median_count is None


def test_build_tree_eco_only_prunes_and_counts_empty_games():
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    rare = BuildStep("Rare", "buildings", 1, 5.0)
    games: list[tuple[list[BuildStep], str]] = [([farm], "won") for _ in range(5)]
    games += [([rare], "won") for _ in range(2)]
    games += [([], "won") for _ in range(3)]  # empty eco (and no science) still counts at root

    tree = build_tree(games)
    assert tree.games == 10
    assert ("buildings", "Farm") in tree.children
    assert tree.children[("buildings", "Farm")].games == 5
    assert ("buildings", "Rare") not in tree.children  # 2 games < min_games=3


def test_build_tree_never_creates_science_category_nodes():
    # Even games carrying a long science chain never grow the tree a "sciences" node: identity
    # is the eco sequence alone, and every science rides as a per-node annotation instead.
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    barracks = BuildStep("Barracks", "buildings", 1, 10.0)
    heal = BuildStep("Heal", "sciences", 1, 20.0)
    draft = BuildStep("Draft", "sciences", 1, 40.0)
    games = [([farm, barracks, heal, draft], "won") for _ in range(5)]

    tree = build_tree(games)

    def _walk(node: BuildNode) -> None:
        for child in node.children.values():
            assert child.category != "sciences"
            _walk(child)

    _walk(tree)
    top = openings(tree)
    assert len(top) == 1
    assert [n.category for n in top[0]] == ["buildings", "buildings"]


def test_build_tree_science_by_step_only_when_bought_by_that_steps_own_clock():
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    barracks = BuildStep("Barracks", "buildings", 1, 30.0)
    heal = BuildStep("Heal", "sciences", 1, 20.0)  # bought after Farm's clock, before Barracks's
    games = [([farm, barracks, heal], "won") for _ in range(5)]

    tree = build_tree(games)
    farm_node = tree.children[("buildings", "Farm")]
    barracks_node = farm_node.children[("buildings", "Barracks")]

    # Heal (20.0) is "in hand" by Barracks's own clock (30.0) but not yet by Farm's (5.0).
    assert "Heal" not in farm_node.sciences_by_step
    assert barracks_node.sciences_by_step["Heal"] == [20.0] * 5

    # Both nodes still carry it, unconditionally, in the full science order.
    assert farm_node.sciences_taken["Heal"] == [20.0] * 5
    assert barracks_node.sciences_taken["Heal"] == [20.0] * 5


def test_build_tree_annotations_ride_only_surviving_nodes():
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    rare_tail = BuildStep("RareTail", "buildings", 1, 10.0)
    heal = BuildStep("Heal", "sciences", 1, 20.0)

    games = [([farm], "won") for _ in range(8)]  # common opening: no science
    games += [([farm, rare_tail, heal], "won") for _ in range(2)]  # rare tail: below min_games

    tree = build_tree(games)
    farm_node = tree.children[("buildings", "Farm")]
    assert ("buildings", "RareTail") not in farm_node.children  # 2 games < min_games=3

    # Heal rode along the pruned RareTail's own eco path, so every node that path visited -
    # including the surviving Farm - was annotated with it before the prune dropped RareTail.
    assert farm_node.sciences_taken["Heal"] == [20.0, 20.0]
    assert "Heal" not in farm_node.sciences_by_step  # 20.0 > Farm's own step clock (5.0)


def test_build_tree_science_annotation_medians_and_one_clock_per_game():
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    games = [
        ([farm, BuildStep("Heal", "sciences", 1, seconds)], "won") for seconds in (10.0, 20.0, 30.0)
    ]

    tree = build_tree(games)
    farm_node = tree.children[("buildings", "Farm")]
    assert sorted(farm_node.sciences_taken["Heal"]) == [10.0, 20.0, 30.0]  # one clock per game

    payload = farm_node.to_dict()
    heal_entry = next(e for e in payload["sciences_taken"] if e["label"] == "Heal")
    assert heal_entry == {"label": "Heal", "games": 3, "median_seconds": 20.0}


def test_build_tree_to_dict_sciences_sorted_by_median_clock_then_label():
    farm = BuildStep("Farm", "buildings", 1, 5.0)
    games = [([farm, BuildStep("Zeal", "sciences", 1, 30.0)], "won") for _ in range(3)]
    games += [([farm, BuildStep("Amity", "sciences", 1, 10.0)], "won") for _ in range(3)]

    tree = build_tree(games)
    farm_node = tree.children[("buildings", "Farm")]
    labels = [entry["label"] for entry in farm_node.to_dict()["sciences_taken"]]
    assert labels == ["Amity", "Zeal"]  # Amity's median (10.0) precedes Zeal's (30.0)


def test_build_tree_root_not_annotated_and_empty_eco_still_counts():
    heal = BuildStep("Heal", "sciences", 1, 10.0)
    games = [([heal], "won") for _ in range(5)]  # empty eco: only a science purchase

    tree = build_tree(games)
    assert tree.games == 5
    assert tree.children == {}  # no eco step, so nothing to walk and annotate
    assert tree.sciences_taken == {}
    assert tree.sciences_by_step == {}
