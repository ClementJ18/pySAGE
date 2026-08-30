"""Rework a ROTWK/Edain `MainMenu.apt` nav bar around the restored Battle School.

[`build_battle_school.py`](build_battle_school.py) merges BFME1's tutorial book into a shell and
wires `ShowBattleSchoolVideo()`, but deliberately stops short of the button that calls it, because
where that call comes from is the mod's own menu layout. This is that layout, for Edain's bar:

    before   SoloPlay▾   MultiPlay▾   Options▾      MyHeroes    Quit
    after    SoloPlay▾   MultiPlay▾   BattleSchool  Misc▾       Quit

`Options` was a three-entry dropdown and `MyHeroes` a plain button, so the two swap shapes: the
Battle School takes the plain-button role `MyHeroes` vacated, and a new four-entry `MiscNav` takes
the dropdown role, carrying `Options`' three entries plus Custom Hero.

**Four entries is real, shipped art.** `MenuExport` exports `NavFrame4` and `NavDropShadow_4`
beside the `NavFrame3` / `NavFrame5` that Edain's bar already uses, all three anchored on the same
`NavFrame_Bottom_Med` so they hang from one point and grow upward; the entry strips differ only in
height (165 / 200 / 236 px, one entry being 35.5). No Edain movie imports the four, but stock
`Skirmish.apt` does, and its nav sprite is this file's ground truth for the numbers that depend on
panel height.

Everything else is *derived, not guessed*. `SoloPlayNav` (five entries) and `Skirmish`'s nav (four)
run the same animation, frame for frame, at the same depths modulo a constant: delete the fifth
entry's records from `SoloPlayNav`, renumber the fixtures below it, and the reveal ramp, the mask
wipe and the close ramp come out equal to Skirmish's on every frame. Only two things actually know
how tall the panel is - the top cap's slide and the two light streaks that sweep the panel edges -
and those are lifted from Skirmish directly.

Dev-only, like `build_battle_school.py`: it edits one movie in place by absolute path and is not
part of the package.
"""

from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from sage_apt import apt_to_xml, xml_to_apt
from sage_apt.merge import character_index

__all__ = ["build", "main"]

#: The nav this file builds, and the plain button that takes the slot it vacates. Both names are
#: load-bearing: a placeobject named `X` is driven by a root function `XButton`, and
#: `DisableAllButtons` / `RevealAllButtons` / `ShowMainMenu` reach the bar by these names too.
MISC_NAV = "MiscNav"
BATTLE_SCHOOL = "BattleSchool"

#: What the nav replaces, and what the button replaces. The pairing is the reason the root
#: rewiring is only two string renames: a dropdown takes the dropdown's name slot and a button
#: takes the button's, so every existing call keeps sending the label its target understands
#: (`_disable` / `_hide` for a nav, `_disabled` / `_reveal` for a button).
OPTIONS_NAV = "OptionsNav"
MY_HEROES = "MyHeroes"

#: The five-entry nav the four-entry one is cut down from, and the two navs whose `_show` closes
#: the others by name.
SOLO_PLAY_NAV = "SoloPlayNav"
MULTI_PLAY_NAV = "MultiPlayNav"

#: `MenuExport`'s four-entry panel and its shadow - shipped, unused by Edain, and intact in
#: Edain's repainted `apt_MenuExport_3` / `_1` atlases.
NAV_FRAME_4 = "NavFrame4"
NAV_DROP_SHADOW_4 = "NavDropShadow_4"
NAV_FRAME_5 = "NavFrame5"
NAV_DROP_SHADOW_5 = "NavDropShadow_5"
MENU_EXPORT = "MenuExport"

#: The entries, top to bottom as they appear on screen. Each pairs the placeobject name the root
#: function hangs off with the `$`-prefixed string-table key the shell resolves for its caption.
#: `MyHeroes` keeps its name so stock's `MyHeroesButton` keeps driving it.
MISC_ENTRIES = (
    (MY_HEROES, "$MyHeroes"),
    ("Settings", "$Settings"),
    ("AdvancedSettings", "$AdvancedSettings"),
    ("Credits", "$Credits"),
)

#: The nav's own caption, and the button's. `$BattleSchool` is already in the table -
#: `build_battle_school.py` puts it there; `$Misc` is new and :func:`string_rows` emits it.
MISC_CAPTION = "$Misc"
BATTLE_SCHOOL_CAPTION = "$BattleSchool"

#: The bar, in screen coordinates. Navs sit a touch higher than plain buttons because their art is
#: anchored differently; both values are the shell's own, not new ones.
NAV_TY = 711.15
BUTTON_TY = 711.84998
#: `Options`' slot, which the button takes, and `MyHeroes`', which the nav takes.
BUTTON_TX = 511.29999
NAV_TX = 715.15

#: Depths in the root frame. The nav keeps the depth a nav had and the button the depth a button
#: had, so `_reshow`'s removal list needs no edit and the bar's stacking order is unchanged.
NAV_DEPTH = 118
BUTTON_DEPTH = 25

#: Inside the nav: the entry depths, which are `SoloPlayNav`'s four lowest unchanged, and the
#: fifth, whose every record is dropped.
ENTRY_DEPTHS = (7, 21, 35, 49)
FIFTH_ENTRY_DEPTH = 63

#: The fixtures that sit above the entries, renumbered down by one entry's worth of depth (14).
#: Left of the arrow is `SoloPlayNav`'s, right is the four-entry nav's - which is Skirmish's
#: scheme less one, since Skirmish numbers its entries from 8 rather than 7.
FIXTURE_DEPTHS = {
    77: 63,  # the mask that wipes the panel open
    79: 65,  # the NavFrame itself
    85: 71,  # NavFrame_Top_Med, the cap
    88: 74,  # the right-edge light streak
    90: 76,  # the left-edge one
    92: 78,  # OpenButton
    108: 94,  # the closed-state hover button
}
#: The mask's clip range moves with it.
CLIP_DEPTHS = {83: 69}

#: One entry's height. The cap's whole slide is one entry higher on a five-entry panel than on a
#: four-entry one, so shifting its `ty` by this reproduces Skirmish's cap exactly - checked frame
#: by frame against it.
ENTRY_HEIGHT = 35.0

#: The click-outside catcher, parked so its 1030.8 x 775.15 bounds cover the 1024 x 768 screen from
#: the nav's new position. Local, so it is the screen point minus :data:`NAV_TX`.
CATCHER_TX = -498.15

#: The two light streaks, from Skirmish's four-entry nav: per frame, the streak's length (`rotm01`)
#: and how far along the panel edge it has swept (`ty`). These are the one part of the animation
#: that does not fall out of deleting an entry - they travel the panel's full height, so a
#: five-entry sweep is visibly too long. `tx` and the alphas are left as Edain has them.
GLOW_RIGHT = {
    15: (0.14718628, -68.349998),
    16: (0.20654297, -78.400002),
    17: (0.38465881, -108.65),
    18: (0.37963867, -125.05),
    19: (0.37538147, -138.89999),
    20: (0.37190247, -150.25),
    21: (0.36921692, -159.10001),
    22: (0.36726379, -165.39999),
}
GLOW_LEFT = {
    15: (0.15611267, -179.95),
    16: (0.15611267, -169.95),
    17: (0.37466431, -140.05),
    18: (0.37466431, -123.85),
    19: (0.37466431, -110.15),
    20: (0.37466431, -98.900002),
    21: (0.37466431, -90.150002),
    22: (0.37466431, -83.900002),
}

#: The frame the nav's entries are placed and named on.
SHOW_FRAME = 9

#: The `.csv` row `$Misc` needs. Two columns of text because Edain's table is German then English;
#: the caption is a nav header, so it is upper case like `$Options`' was.
MISC_STRING_ROW = "APT:misc;VERSCHIEDENES;MISC"


class BuildError(RuntimeError):
    """A precondition the rewiring depends on is not true of this movie."""


def _root_action(root: ET.Element) -> ET.Element:
    """The movieclip's frame-0 action block - where every root function and constant lives."""
    movieclip = root.find("movieclip")
    if movieclip is None:
        raise BuildError("no <movieclip>")
    frames = movieclip.find("frames")
    if frames is None or len(frames) == 0:
        raise BuildError("movieclip has no frames")
    action = frames[0].find("action")
    if action is None:
        raise BuildError("root frame 0 has no action block")
    return action


def _root_frame(root: ET.Element, index: int) -> ET.Element:
    movieclip = root.find("movieclip")
    frames = movieclip.find("frames")
    for frame in frames:
        if frame.get("id") == str(index):
            return frame
    raise BuildError(f"root has no frame {index}")


def _sprite(root: ET.Element, character: int) -> ET.Element:
    for element in root:
        if element.tag == "sprite" and element.get("id") == str(character):
            return element
    raise BuildError(f"character {character} is not a sprite")


def _placed(frame: ET.Element, name: str) -> ET.Element:
    for element in frame.findall("placeobject"):
        poname = element.find("poname")
        if poname is not None and poname.get("name") == name:
            return element
    raise BuildError(f"no placeobject named {name!r}")


def _constant(action: ET.Element, value: str) -> ET.Element:
    """The `<constant>` in `action`'s pool holding `value`, which must be unique there.

    A pool index is a position, not the advisory `id`, so renaming in place is safe: every
    `pushconstant` / `getnamedmember` that reached the old string reaches the new one.
    """
    pool = action.find("constantpool")
    if pool is None:
        raise BuildError("action block has no constant pool")
    found = [c for c in pool if c.get("string") == value]
    if len(found) != 1:
        raise BuildError(f"expected exactly one {value!r} in the pool, found {len(found)}")
    return found[0]


def _function(action: ET.Element, name: str) -> ET.Element:
    for element in action.iter("definefunction"):
        if element.get("name") == name:
            return element
    raise BuildError(f"no function named {name!r}")


def _has_function(action: ET.Element, name: str) -> bool:
    return any(e.get("name") == name for e in action.iter("definefunction"))


def _frames_of(sprite: ET.Element) -> list[ET.Element]:
    frames = sprite.find("frames")
    if frames is None:
        raise BuildError("sprite has no frames")
    return list(frames)


def _records(sprite: ET.Element, depth: int) -> list[tuple[int, ET.Element]]:
    """Every record touching `depth`, as (frame index, element)."""
    out = []
    for index, frame in enumerate(_frames_of(sprite)):
        for element in frame:
            if element.tag in ("placeobject", "removeobject"):
                if element.get("depth") == str(depth):
                    out.append((index, element))
    return out


def add_import(root: ET.Element, name: str, movie: str) -> int:
    """Claim a fresh character slot for an imported symbol, and return its index.

    Characters are positional - the compiler reads them in document order and ignores the `id`
    attribute - so an import is an `<empty>` appended at the end plus an import-table row pointing
    at it. Nothing renumbers, which is the whole reason this is safe to run on a movie that has
    already had BFME1's tutorial book merged into it.
    """
    movieclip = root.find("movieclip")
    imports = movieclip.find("imports")
    if imports is None:
        raise BuildError("movie has no imports element")
    for existing in imports:
        if existing.get("movie") == movie and existing.get("name") == name:
            raise BuildError(f"{movie}:{name} is already imported as {existing.get('character')}")

    index = len(character_index(root))
    slot = ET.SubElement(root, "empty")
    slot.set("id", str(index))
    row = ET.SubElement(imports, "import")
    row.set("name", name)
    row.set("movie", movie)
    row.set("character", str(index))
    return index


def _imported_as(root: ET.Element, name: str, movie: str) -> int:
    movieclip = root.find("movieclip")
    for row in movieclip.find("imports"):
        if row.get("movie") == movie and row.get("name") == name:
            return int(row.get("character"))
    raise BuildError(f"{movie}:{name} is not imported")


def _drop_fifth_entry(sprite: ET.Element) -> None:
    """Delete every record for the fifth entry, and the entry itself from the removal lists."""
    for frame in _frames_of(sprite):
        for element in list(frame):
            if element.tag in ("placeobject", "removeobject") and element.get("depth") == str(
                FIFTH_ENTRY_DEPTH
            ):
                frame.remove(element)


def _renumber_depths(sprite: ET.Element) -> None:
    for frame in _frames_of(sprite):
        for element in frame:
            if element.tag not in ("placeobject", "removeobject"):
                continue
            depth = int(element.get("depth"))
            if depth in FIXTURE_DEPTHS:
                element.set("depth", str(FIXTURE_DEPTHS[depth]))
            clip = element.get("clipdepth")
            if clip is not None and int(clip) in CLIP_DEPTHS:
                element.set("clipdepth", str(CLIP_DEPTHS[int(clip)]))


def _repoint_panel_art(sprite: ET.Element, mapping: dict[int, int]) -> None:
    for frame in _frames_of(sprite):
        for element in frame.findall("placeobject"):
            character = int(element.get("character"))
            if character in mapping:
                element.set("character", str(mapping[character]))


def _raise_cap(sprite: ET.Element) -> None:
    """Shorten the top cap's slide by one entry - the whole of its panel-height dependence."""
    for _, element in _records(sprite, FIXTURE_DEPTHS[85]):
        if element.tag != "placeobject":
            continue
        ty = element.get("ty")
        if ty is not None and float(ty) != 0.0:
            element.set("ty", _fmt(float(ty) + ENTRY_HEIGHT))


def _retime_glows(sprite: ET.Element) -> None:
    """Replace the two edge streaks' sweep with the four-entry one Skirmish ships."""
    for depth, table in ((FIXTURE_DEPTHS[88], GLOW_RIGHT), (FIXTURE_DEPTHS[90], GLOW_LEFT)):
        for frame_index, element in _records(sprite, depth):
            if element.tag != "placeobject" or frame_index not in table:
                continue
            length, ty = table[frame_index]
            element.set("rotm01", _fmt(length))
            element.set("ty", _fmt(ty))


def _fmt(value: float) -> str:
    """Match the decompiler's float spelling so a round-trip stays stable."""
    text = f"{value:.8g}"
    return text


def _name_entries(sprite: ET.Element) -> None:
    """Rename the four surviving entries, bottom-most depth first.

    :data:`MISC_ENTRIES` reads top to bottom as the panel does, but the depths run the other way -
    the lowest depth sits nearest the button, at the bottom - so the pairing is reversed.
    """
    show = _frames_of(sprite)[SHOW_FRAME]
    bottom_up = list(reversed(MISC_ENTRIES))
    for depth, (name, _caption) in zip(ENTRY_DEPTHS, bottom_up, strict=False):
        placed = [e for e in show.findall("placeobject") if e.get("depth") == str(depth)]
        if len(placed) != 1:
            raise BuildError(f"expected one placement at entry depth {depth}, found {len(placed)}")
        poname = placed[0].find("poname")
        if poname is None:
            raise BuildError(f"entry at depth {depth} is unnamed")
        poname.set("name", name)


def _park_catcher(sprite: ET.Element) -> None:
    """Move the click-outside catcher so it still covers the screen from the nav's new position."""
    placed = [
        e for e in _frames_of(sprite)[SHOW_FRAME].findall("placeobject") if e.get("depth") == "1"
    ]
    if len(placed) != 1:
        raise BuildError(f"expected one catcher placement, found {len(placed)}")
    placed[0].set("tx", _fmt(CATCHER_TX))


def _set_caption(sprite: ET.Element, caption: str) -> None:
    """Retitle the nav by renaming the caption in its frame-0 pool.

    Frame 0 sets `OpenButton.buttonName` from the pool and then either reveals or parks the button
    depending on `Init`; only the caption differs between the shell's navs.
    """
    action = _frames_of(sprite)[0].find("action")
    if action is None:
        raise BuildError("nav frame 0 has no action")
    pool = action.find("constantpool")
    captions = [c for c in pool if (c.get("string") or "").startswith("$")]
    if len(captions) != 1:
        raise BuildError(f"expected one caption in the nav's frame-0 pool, found {len(captions)}")
    captions[0].set("string", caption)


def _show_action() -> ET.Element:
    """The nav's `_show` action: caption every entry, mark them closing, open, close the siblings.

    `closeParent` is what makes a click on an entry collapse the panel; `MenuExport`'s shared
    `OnButtonClick` reads it off the entry it was clicked on. The two `gotoAndStop("_hide")` calls
    are how Edain's navs stay mutually exclusive - this one closes the two that remain.
    """
    names = [name for name, _ in MISC_ENTRIES]
    captions = [caption for _, caption in MISC_ENTRIES]

    pool = [
        "buttonName",
        "closeParent",
        "_over",
        "OpenButton",
        "gotoAndPlay",
        "_hide",
        "_parent",
        "gotoAndStop",
        SOLO_PLAY_NAV,
        MULTI_PLAY_NAV,
    ]
    pool = names + captions + pool
    index = {value: position for position, value in enumerate(pool)}

    action = ET.Element("action")
    pool_element = ET.SubElement(action, "constantpool")
    for position, value in enumerate(pool):
        constant = ET.SubElement(pool_element, "constant")
        constant.set("id", str(position))
        constant.set("string", value)

    def emit(tag: str, **attributes: str) -> None:
        element = ET.SubElement(action, tag)
        for key, value in attributes.items():
            element.set(key, value)

    for name, caption in MISC_ENTRIES:
        emit("pushvalue", val=str(index[name]))
        emit("pushconstant", val=str(index["buttonName"]))
        emit("pushconstant", val=str(index[caption]))
        emit("setmember")
    for name, _caption in MISC_ENTRIES:
        emit("pushvalue", val=str(index[name]))
        emit("pushconstant", val=str(index["closeParent"]))
        emit("pushtrue")
        emit("setmember")

    emit("pushconstant", val=str(index["_over"]))
    emit("pushone")
    emit("pushvalue", val=str(index["OpenButton"]))
    emit("callnamedmethodpop", val=str(index["gotoAndPlay"]))

    for sibling in (SOLO_PLAY_NAV, MULTI_PLAY_NAV):
        emit("pushconstant", val=str(index["_hide"]))
        emit("pushone")
        emit("pushvalue", val=str(index["_parent"]))
        emit("getnamedmember", val=str(index[sibling]))
        emit("callnamedmethodpop", val=str(index["gotoAndStop"]))

    emit("end")
    return action


def build_misc_nav(root: ET.Element, nav_frame: int, drop_shadow: int) -> ET.Element:
    """Cut a four-entry nav out of the five-entry `SoloPlayNav`, and append it as a character."""
    source_character = int(_placed(_root_frame(root, 0), SOLO_PLAY_NAV).get("character"))
    sprite = copy.deepcopy(_sprite(root, source_character))

    _drop_fifth_entry(sprite)
    _renumber_depths(sprite)
    _repoint_panel_art(
        sprite,
        {
            _imported_as(root, NAV_FRAME_5, MENU_EXPORT): nav_frame,
            _imported_as(root, NAV_DROP_SHADOW_5, MENU_EXPORT): drop_shadow,
        },
    )
    _raise_cap(sprite)
    _retime_glows(sprite)
    _name_entries(sprite)
    _park_catcher(sprite)
    _set_caption(sprite, MISC_CAPTION)

    show = _frames_of(sprite)[SHOW_FRAME]
    for stale in show.findall("action"):
        show.remove(stale)
    show.append(_show_action())

    index = len(character_index(root))
    sprite.set("id", str(index))
    root.append(sprite)
    return sprite


def rewire_root(root: ET.Element, misc_nav: int) -> None:
    """Swap the two bar entries, and point the shell's bookkeeping at their new names.

    The rename is the whole of the bookkeeping. `DisableAllButtons`, `RevealAllButtons`,
    `ShowMainMenu`, the startup block and `ShowBattleSchoolVideo` all reach the bar through the
    root pool, and each sends a nav `_disable` / `_hide` and a button `_disabled` / `_reveal`.
    Because the new nav takes the old nav's pool slot and the new button the old button's, every
    one of those calls still addresses something that understands what it is being sent.
    """
    action = _root_action(root)
    _constant(action, OPTIONS_NAV).set("string", MISC_NAV)
    _constant(action, MY_HEROES).set("string", BATTLE_SCHOOL)

    frame = _root_frame(root, 0)

    nav = _placed(frame, OPTIONS_NAV)
    nav.set("character", str(misc_nav))
    nav.set("tx", _fmt(NAV_TX))
    nav.set("ty", _fmt(NAV_TY))
    nav.find("poname").set("name", MISC_NAV)

    button = _placed(frame, MY_HEROES)
    button.set("tx", _fmt(BUTTON_TX))
    button.set("ty", _fmt(BUTTON_TY))
    button.find("poname").set("name", BATTLE_SCHOOL)
    for clipaction in button.iter("clipaction"):
        for element in clipaction:
            if element.tag == "setstringvar" and element.get("str") == "$" + MY_HEROES:
                element.set("str", BATTLE_SCHOOL_CAPTION)

    if nav.get("depth") != str(NAV_DEPTH) or button.get("depth") != str(BUTTON_DEPTH):
        raise BuildError(
            f"expected the nav at depth {NAV_DEPTH} and the button at {BUTTON_DEPTH}, "
            f"found {nav.get('depth')} and {button.get('depth')}"
        )

    # The two sibling navs close this one by name when they open.
    for sibling in (SOLO_PLAY_NAV, MULTI_PLAY_NAV):
        character = int(_placed(frame, sibling).get("character"))
        sibling_show = _frames_of(_sprite(root, character))[SHOW_FRAME]
        sibling_action = sibling_show.find("action")
        if sibling_action is None:
            raise BuildError(f"{sibling} has no _show action")
        _constant(sibling_action, OPTIONS_NAV).set("string", MISC_NAV)


def rewire_functions(root: ET.Element) -> None:
    """Give the button its callback, and give Custom Hero its stock one back.

    `build_battle_school.py` leaves nothing calling `ShowBattleSchoolVideo`; a shell that wants to
    try the book before its button exists tends to borrow `MyHeroesButton`, so this restores that
    to `GameCode("CreateAHero")` whether or not it was borrowed, and puts the call on
    `BattleSchoolButton`, which the new placeobject's name reaches.
    """
    action = _root_action(root)

    if _has_function(action, BATTLE_SCHOOL + "Button"):
        raise BuildError(f"{BATTLE_SCHOOL}Button already exists")

    pool = action.find("constantpool")
    strings = [c.get("string") for c in pool]

    def slot(value: str) -> str:
        if value not in strings:
            raise BuildError(f"the root pool has no {value!r}")
        return str(strings.index(value))

    my_heroes = _function(action, MY_HEROES + "Button")
    body = my_heroes.find("body")
    if body is None:
        body = ET.SubElement(my_heroes, "body")
    for stale in list(body):
        body.remove(stale)
    for tag, attributes in (
        ("pushzero", {}),
        ("callnamedfuncpop", {"val": slot("DisableAllButtons")}),
        ("pushconstant", {"val": slot("CreateAHero")}),
        ("pushone", {}),
        ("pushvalue", {"val": slot("_root")}),
        ("callnamedmethodpop", {"val": slot("GameCode")}),
    ):
        element = ET.SubElement(body, tag)
        for key, value in attributes.items():
            element.set(key, value)

    function = ET.Element("definefunction")
    function.set("name", BATTLE_SCHOOL + "Button")
    function.set("size", "3")
    function_body = ET.SubElement(function, "body")
    ET.SubElement(function_body, "pushzero")
    ET.SubElement(function_body, "callnamedfuncpop").set("val", slot("ShowBattleSchoolVideo"))

    children = list(action)
    anchor = children.index(_function(action, "ExitTutorialButton"))
    action.insert(anchor + 1, function)


def string_rows() -> str:
    """The one caption this adds that the shell's table does not already have."""
    return (
        "; The Misc nav's header. $BattleSchool is already in the table - "
        "build_battle_school.py puts it there.\n" + MISC_STRING_ROW + "\n"
    )


def build(main_menu: Path, out_dir: Path) -> Path:
    """Rewire `main_menu` and write the result, plus its string row, into `out_dir`."""
    xml_path = main_menu if main_menu.suffix == ".xml" else apt_to_xml(main_menu)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    action = _root_action(root)
    if not _has_function(action, "ShowBattleSchoolVideo"):
        raise BuildError(
            "this movie has no ShowBattleSchoolVideo - run tools/build_battle_school.py first"
        )

    nav_frame = add_import(root, NAV_FRAME_4, MENU_EXPORT)
    drop_shadow = add_import(root, NAV_DROP_SHADOW_4, MENU_EXPORT)
    misc_nav = build_misc_nav(root, nav_frame, drop_shadow)
    rewire_root(root, int(misc_nav.get("id")))
    rewire_functions(root)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_xml = out_dir / "MainMenu.xml"
    tree.write(out_xml, encoding="utf-8", xml_declaration=True)
    xml_to_apt(out_xml)
    (out_dir / "misc-nav.csv").write_text(string_rows(), encoding="utf-8")

    print(f"characters {len(character_index(root))} (MiscNav is {misc_nav.get('id')})")
    print(f"imports    {NAV_FRAME_4}={nav_frame} {NAV_DROP_SHADOW_4}={drop_shadow}")
    print(f"wrote      {out_dir}")
    return out_xml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--main-menu",
        required=True,
        type=Path,
        help="the destination MainMenu.apt or .xml, after build_battle_school.py has run",
    )
    parser.add_argument("--out", required=True, type=Path, help="directory to write into")
    args = parser.parse_args(argv)

    try:
        build(args.main_menu, args.out)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
