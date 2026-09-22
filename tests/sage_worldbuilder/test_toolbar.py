"""The toolbar catalogue: item integrity and `normalise`."""

from sage_worldbuilder.toolbar import CATALOGUE, DEFAULT_ITEMS, ITEMS_BY_ID, normalise


def test_catalogue_ids_are_unique():
    ids = [item.id for item in CATALOGUE]
    assert len(ids) == len(set(ids))


def test_catalogue_items_have_a_label_and_a_group():
    for item in CATALOGUE:
        assert item.label.strip()
        assert item.group.strip()
        assert "&" not in item.label


def test_items_by_id_matches_the_catalogue():
    assert ITEMS_BY_ID == {item.id: item for item in CATALOGUE}
    for item in CATALOGUE:
        assert ITEMS_BY_ID[item.id] is item


def test_default_items_all_resolve_and_have_no_duplicates():
    assert len(DEFAULT_ITEMS) == len(set(DEFAULT_ITEMS))
    for item_id in DEFAULT_ITEMS:
        assert item_id in ITEMS_BY_ID


def test_normalise_drops_unknown_ids():
    assert normalise(["open", "not-a-real-id", "save"]) == ("open", "save")


def test_normalise_drops_duplicates_keeping_the_first():
    assert normalise(["open", "save", "open", "undo", "save"]) == ("open", "save", "undo")


def test_normalise_keeps_order():
    reversed_default = tuple(reversed(DEFAULT_ITEMS))
    assert normalise(reversed_default) == reversed_default


def test_normalise_of_nothing_is_empty():
    assert normalise([]) == ()
    assert normalise(iter(())) == ()
