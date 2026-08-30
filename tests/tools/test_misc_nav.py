"""Reworking the main-menu nav bar (`tools/build_misc_nav.py`).

The rewiring is index arithmetic over a movie whose every reference is a number: a depth, a
character slot, a constant-pool position. All three renumber here - the four-entry nav is the
five-entry one with an entry deleted and the fixtures above it moved down - and an off-by-one in
any of them produces a movie that still compiles, still round-trips, and is wrong only once the
game draws it. So these are invariant tests: after a build, no record mentions the deleted entry,
every surviving fixture moved by exactly the amount its neighbours did, and the bookkeeping that
reaches the bar by name still addresses something of the right *kind* - a dropdown where a
dropdown's labels are sent, a button where a button's are.

The movie is hand-written and just large enough to have the shape the tool requires. The real one
is what `build()` is run against by hand; `tests/sage_apt/test_corpus.py` is what exercises real
movies through the converter.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_misc_nav import (  # noqa: E402
    BATTLE_SCHOOL,
    BUTTON_DEPTH,
    ENTRY_DEPTHS,
    FIFTH_ENTRY_DEPTH,
    FIXTURE_DEPTHS,
    MISC_ENTRIES,
    MISC_NAV,
    NAV_DEPTH,
    BuildError,
    add_import,
    build_misc_nav,
    rewire_functions,
    rewire_root,
)

#: Strings the root pool must carry for the rewiring to have anything to rename or call.
ROOT_POOL = (
    "_root",
    "GameCode",
    "DisableAllButtons",
    "CreateAHero",
    "ShowBattleSchoolVideo",
    "SoloPlayNav",
    "MultiPlayNav",
    "OptionsNav",
    "MyHeroes",
)

#: The five entries of the nav the four-entry one is cut from, bottom-most depth first, with the
#: `ty` the shell actually uses - the fifth is the one that has to disappear without trace.
SOURCE_ENTRIES = (
    (7, -73.800003, "LoadGame"),
    (21, -109.3, "BonusCampaign"),
    (35, -144.8, "Expansion1Campaign"),
    (49, -180.3, "WarOfTheRing"),
    (FIFTH_ENTRY_DEPTH, -215.8, "Skirmish"),
)


def _pool(*strings: str) -> str:
    rows = "\n".join(
        f'<constant id="{i}" string="{s}"/>' for i, s in enumerate(strings)
    )
    return f"<constantpool>{rows}</constantpool>"


def _po(depth, character, name=None, tx=0.0, ty=0.0, clipdepth=-1, rotm11=1.0):
    parts = [
        f'<placeobject depth="{depth}" character="{character}" rotm00="1" rotm01="0"',
        f'rotm10="0" rotm11="{rotm11}" tx="{tx}" ty="{ty}" red="255" green="255"',
        f'blue="255" alpha="255" ratio="0" clipdepth="{clipdepth}" unknown="0">',
    ]
    body = '<poflags value="HasCharacter|HasMatrix"/>'
    if name is not None:
        body += f'<poname name="{name}"/>'
    return " ".join(parts) + body + "</placeobject>"


def _nav_sprite(character: int, caption: str, entries, fixtures=True) -> str:
    """A nav dropdown with the frames and depths the tool reaches into."""
    frames = [
        f'<frame id="0"><action>{_pool("OpenButton", "buttonName", caption)}<end/></action>'
        f'<framelabel label="_hide" frame="0"/>'
        + _po(FIXTURE_DEPTHS[92], 3, "OpenButton")
        + _po(FIXTURE_DEPTHS[108], 21)
        + "</frame>"
    ]
    frames += [f'<frame id="{i}"/>' for i in range(1, 9)]

    show = [f'<action>{_pool("closeParent", "OptionsNav")}<end/></action>']
    show.append(_po(1, 22, tx=95.6, ty=-150.0))  # the click-outside catcher
    show += [_po(depth, 10, name, tx=-1.15, ty=ty) for depth, ty, name in entries]
    if fixtures:
        show.append(_po(77, 12, tx=-105.1, ty=-30.6, clipdepth=83))  # the wipe mask
        show.append(_po(79, 23, tx=-90.1, ty=-337.05))  # NavFrame5
    frames.append(f'<frame id="9"><framelabel label="_show" frame="9"/>{"".join(show)}</frame>')

    frames += [f'<frame id="{i}"/>' for i in range(10, 13)]
    # The cap slides in from frame 13, the two edge streaks sweep from frame 15.
    frames.append(f'<frame id="13">{_po(85, 14, ty=-264.0)}</frame>')
    frames.append(f'<frame id="14">{_po(5, 24, ty=5.25)}{_po(85, -1, ty=-256.8)}</frame>')
    for index in range(15, 23):
        frames.append(
            f'<frame id="{index}">'
            + _po(88, 16 if index == 15 else -1, tx=77.25, ty=-70.55 - index)
            + _po(90, 16 if index == 15 else -1, tx=-80.55, ty=-223.45 + index)
            + _po(85, -1, ty=-251.2)
            + "</frame>"
        )
    frames += [f'<frame id="{i}"/>' for i in range(23, 44)]
    frames.append(
        f'<frame id="44"><removeobject depth="{FIXTURE_DEPTHS[92]}"/>'
        f'<framelabel label="_hidden" frame="44"/></frame>'
    )
    return f'<sprite id="{character}"><frames>{"".join(frames)}</frames></sprite>'


def movie() -> ET.Element:
    """A shell with the bar the tool reworks, and the battle-school glue it requires."""
    functions = (
        '<definefunction name="ShowBattleSchoolVideo" size="1"><body><pushzero/></body>'
        "</definefunction>"
        '<definefunction name="MyHeroesButton" size="3"><body><pushzero/>'
        '<callnamedfuncpop val="4"/></body></definefunction>'
        '<definefunction name="ExitTutorialButton" size="3"><body><pushzero/></body>'
        "</definefunction>"
    )
    bar = (
        _po(199, 25, "SoloPlayNav", tx=109.5, ty=711.15)
        + _po(37, 17, "MultiPlayNav", tx=310.45, ty=711.15)
        + _po(NAV_DEPTH, 20, "OptionsNav", tx=511.3, ty=711.15)
        + _po(BUTTON_DEPTH, 2, "MyHeroes", tx=715.15, ty=711.85)
    )
    # The button's caption rides in a clip action, the way the shell's plain buttons carry theirs.
    bar = bar.replace(
        '<poname name="MyHeroes"/>',
        '<poname name="MyHeroes"/><clipactions><clipaction flags="1" flags2="0">'
        '<pushstring str="buttonName"/><setstringvar str="$MyHeroes"/><end/>'
        "</clipaction></clipactions>",
    )
    xml = f"""<aptdata>
  <movieclip>
    <imports>
      <import name="NavFrame5" movie="MenuExport" character="23"/>
      <import name="NavDropShadow_5" movie="MenuExport" character="24"/>
    </imports>
    <exports/>
    <frames>
      <frame id="0"><action>{_pool(*ROOT_POOL)}{functions}<end/></action>{bar}</frame>
    </frames>
  </movieclip>
  {"".join(f'<empty id="{i}"/>' for i in range(17))}
  {_nav_sprite(17, "$MultiPlay", SOURCE_ENTRIES[:3])}
  {"".join(f'<empty id="{i}"/>' for i in range(18, 20))}
  {_nav_sprite(20, "$Options", SOURCE_ENTRIES[:3])}
  {"".join(f'<empty id="{i}"/>' for i in range(21, 25))}
  {_nav_sprite(25, "$SoloPlay", SOURCE_ENTRIES)}
</aptdata>"""
    return ET.fromstring(xml)


def built() -> ET.Element:
    """A movie with the whole rework applied."""
    root = movie()
    nav_frame = add_import(root, "NavFrame4", "MenuExport")
    drop_shadow = add_import(root, "NavDropShadow_4", "MenuExport")
    sprite = build_misc_nav(root, nav_frame, drop_shadow)
    rewire_root(root, int(sprite.get("id")))
    rewire_functions(root)
    return root


def misc_nav(root: ET.Element) -> ET.Element:
    character = int(placed(root, MISC_NAV).get("character"))
    return next(e for e in root if e.tag == "sprite" and e.get("id") == str(character))


def placed(root: ET.Element, name: str) -> ET.Element:
    frame = root.find("movieclip").find("frames")[0]
    for element in frame.findall("placeobject"):
        poname = element.find("poname")
        if poname is not None and poname.get("name") == name:
            return element
    raise AssertionError(f"nothing named {name!r} on the root frame")


def root_pool(root: ET.Element) -> list[str]:
    action = root.find("movieclip").find("frames")[0].find("action")
    return [c.get("string") for c in action.find("constantpool")]


def depths(sprite: ET.Element) -> set[int]:
    return {
        int(e.get("depth"))
        for frame in sprite.find("frames")
        for e in frame
        if e.tag in ("placeobject", "removeobject")
    }


class TestTheFourthEntry:
    """The nav is the five-entry one with its top entry deleted."""

    def test_the_fifth_entry_is_gone_from_every_frame(self):
        # Not "depth 63 is unused" - the mask renumbers *onto* it, one entry-step above the top
        # entry, which is exactly where the shipped four-entry nav puts its own. What has to be
        # gone is the entry: nothing may still place the entry character up there.
        sprite = misc_nav(built())
        entries = [
            e
            for frame in sprite.find("frames")
            for e in frame.findall("placeobject")
            if e.get("character") == "10"
        ]
        assert len(entries) == len(ENTRY_DEPTHS)
        assert not [e for e in entries if int(e.get("depth")) == FIFTH_ENTRY_DEPTH]

    def test_the_deleted_entrys_name_survives_nowhere(self):
        gone = SOURCE_ENTRIES[4][2]
        assert gone not in [
            p.get("name") for p in misc_nav(built()).iter("poname")
        ]

    def test_the_four_that_remain_keep_their_positions(self):
        show = list(misc_nav(built()).find("frames"))[9]
        found = {
            int(e.get("depth")): float(e.get("ty"))
            for e in show.findall("placeobject")
            if int(e.get("depth")) in ENTRY_DEPTHS
        }
        assert found == {depth: ty for depth, ty, _ in SOURCE_ENTRIES[:4]}

    def test_the_entries_are_named_top_of_screen_first(self):
        show = list(misc_nav(built()).find("frames"))[9]
        by_height = sorted(

                (float(e.get("ty")), e.find("poname").get("name"))
                for e in show.findall("placeobject")
                if int(e.get("depth")) in ENTRY_DEPTHS

        )
        assert [name for _, name in by_height] == [name for name, _ in MISC_ENTRIES]

    def test_custom_hero_keeps_the_name_its_root_callback_hangs_off(self):
        # MyHeroesButton is stock's, and it only fires for a placeobject still called MyHeroes.
        assert "MyHeroes" in [name for name, _ in MISC_ENTRIES]

    def test_no_move_record_is_left_without_the_object_it_moves(self):
        """The crash this whole edit could cause, and the reason the entry goes before the renumber.

        A `placeobject` carrying `Move` and `character="-1"` does not place anything - it updates
        whatever already sits at its depth, and a fade is dozens of them in a row. Deleting an
        entry's *placement* while leaving its Move records behind therefore leaves the animation
        driving an empty depth, which kills the game the moment the open animation reaches it. It
        is not hypothetical: it is how the tutorial book's first merge crashed.

        The hazard is sharper here than usual, because the mask renumbers straight onto the depth
        the deleted entry vacated - so a stray Move would find not nothing but the mask, and quietly
        drive the wrong object.
        """
        live: set[str] = set()
        orphans = []
        for index, frame in enumerate(misc_nav(built()).find("frames")):
            for element in frame:
                if element.tag == "removeobject":
                    live.discard(element.get("depth"))
                elif element.tag == "placeobject":
                    depth = element.get("depth")
                    if "HasCharacter" in element.find("poflags").get("value"):
                        live.add(depth)
                    elif depth not in live:
                        orphans.append((index, depth))
        assert orphans == []


class TestTheFixturesAbove:
    """Everything above the entries moves down by exactly one entry's worth of depth."""

    def test_every_fixture_is_renumbered(self):
        found = depths(misc_nav(built()))
        assert not found & set(FIXTURE_DEPTHS)
        assert set(FIXTURE_DEPTHS.values()) <= found

    def test_the_masks_clip_range_follows_the_mask(self):
        show = list(misc_nav(built()).find("frames"))[9]
        mask = next(
            e
            for e in show.findall("placeobject")
            if int(e.get("depth")) == FIXTURE_DEPTHS[77]
        )
        # The mask must still clip the NavFrame that sits just above it.
        assert int(mask.get("clipdepth")) > FIXTURE_DEPTHS[79]

    def test_the_cap_slides_one_entry_less_far(self):
        source = next(e for e in movie() if e.get("id") == "25")
        before = float(
            next(
                e
                for frame in source.find("frames")
                for e in frame.findall("placeobject")
                if e.get("depth") == "85"
            ).get("ty")
        )
        after = float(
            next(
                e
                for frame in misc_nav(built()).find("frames")
                for e in frame.findall("placeobject")
                if e.get("depth") == str(FIXTURE_DEPTHS[85])
            ).get("ty")
        )
        assert after > before  # closer to the button, because the panel is shorter


class TestThePanelArt:
    """The four-entry frame and shadow replace the five-entry ones, and nothing else moves."""

    def test_the_new_imports_take_fresh_slots(self):
        root = movie()
        before = len([e for e in root if e.tag in ("empty", "sprite", "button", "shape")])
        first = add_import(root, "NavFrame4", "MenuExport")
        second = add_import(root, "NavDropShadow_4", "MenuExport")
        assert (first, second) == (before, before + 1)

    def test_an_import_that_is_already_there_is_refused(self):
        with pytest.raises(BuildError, match="already imported"):
            add_import(movie(), "NavFrame5", "MenuExport")

    def test_the_nav_draws_the_four_entry_frame(self):
        root = built()
        imports = {
            i.get("name"): int(i.get("character"))
            for i in root.find("movieclip").find("imports")
        }
        drawn = {
            int(e.get("character"))
            for frame in misc_nav(root).find("frames")
            for e in frame.findall("placeobject")
        }
        assert imports["NavFrame4"] in drawn
        assert imports["NavDropShadow_4"] in drawn
        assert imports["NavFrame5"] not in drawn
        assert imports["NavDropShadow_5"] not in drawn


class TestTheBar:
    """The nav and the button swap places, and keep each other's depths."""

    def test_the_dropdown_takes_the_dropdowns_slot(self):
        nav = placed(built(), MISC_NAV)
        assert int(nav.get("depth")) == NAV_DEPTH
        assert float(nav.get("tx")) == pytest.approx(715.15)

    def test_the_button_takes_the_buttons_slot(self):
        button = placed(built(), BATTLE_SCHOOL)
        assert int(button.get("depth")) == BUTTON_DEPTH
        assert float(button.get("tx")) == pytest.approx(511.3)

    def test_the_button_gets_its_own_caption(self):
        button = placed(built(), BATTLE_SCHOOL)
        captions = [e.get("str") for e in button.iter("setstringvar")]
        assert captions == ["$BattleSchool"]

    def test_the_old_names_are_gone_from_the_bar(self):
        root = built()
        for gone in ("OptionsNav", "MyHeroes"):
            with pytest.raises(AssertionError):
                placed(root, gone)


class TestTheBookkeeping:
    """Everything that reaches the bar by name still addresses the right kind of thing."""

    def test_the_pool_renames_in_place(self):
        before, after = root_pool(movie()), root_pool(built())
        # A rename, not an insertion: the pool must be the same length, because every index into
        # it elsewhere in the movie is a position that nothing recomputes.
        assert len(before) == len(after)
        changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
        assert changed == [("OptionsNav", MISC_NAV), ("MyHeroes", BATTLE_SCHOOL)]

    def test_the_dropdowns_slot_still_holds_a_dropdown(self):
        # It is the slot's *kind* that matters: callers send it _disable / _hide, which only a
        # nav sprite understands. Swapping a button in here would fail silently in the game.
        assert root_pool(built()).index(MISC_NAV) == root_pool(movie()).index("OptionsNav")

    def test_the_buttons_slot_still_holds_a_button(self):
        assert root_pool(built()).index(BATTLE_SCHOOL) == root_pool(movie()).index("MyHeroes")

    def test_the_sibling_navs_close_the_new_one(self):
        root = built()
        for sibling in ("SoloPlayNav", "MultiPlayNav"):
            character = int(placed(root, sibling).get("character"))
            sprite = next(e for e in root if e.tag == "sprite" and e.get("id") == str(character))
            pool = [
                c.get("string")
                for c in list(sprite.find("frames"))[9].find("action").find("constantpool")
            ]
            assert MISC_NAV in pool
            assert "OptionsNav" not in pool


class TestTheCallbacks:
    def test_the_button_opens_the_book(self):
        root = built()
        action = root.find("movieclip").find("frames")[0].find("action")
        function = next(
            e for e in action.iter("definefunction") if e.get("name") == "BattleSchoolButton"
        )
        called = [e.get("val") for e in function.iter("callnamedfuncpop")]
        assert [root_pool(root)[int(v)] for v in called] == ["ShowBattleSchoolVideo"]

    def test_custom_hero_gets_its_stock_callback_back(self):
        root = built()
        action = root.find("movieclip").find("frames")[0].find("action")
        function = next(
            e for e in action.iter("definefunction") if e.get("name") == "MyHeroesButton"
        )
        pool = root_pool(root)
        reached = [pool[int(e.get("val"))] for e in function.find("body") if e.get("val")]
        assert "CreateAHero" in reached
        assert "ShowBattleSchoolVideo" not in reached

    def test_a_second_run_is_refused(self):
        root = built()
        with pytest.raises(BuildError, match="already exists"):
            rewire_functions(root)
