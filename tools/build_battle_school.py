"""Build the mod-side half of BFME1's Battle School for a ROTWK shell.

The engine half is [`sage_patch`'s `battle-school`](../sage_patch/docs/battle-school.md): ROTWK
still carries the `AptMainMenu::BattleSchool` command, and the patch gives it the way back out that
EA deleted. Nothing else survives. The parchment book of tutorial videos, its meshes and textures,
the videos themselves, the narration, the `Video` blocks and the `APT:` strings are all gone, and
all of them are still in a BFME1 install.

This assembles them. It reads a BFME1 install and a destination `MainMenu.apt`, merges the book -
character 304 of BFME1's `MainMenu`, 98 characters with its meshes' textures counted - into the
destination with `sage_apt.merge`, wires the ActionScript that opens and closes it, and writes a
tree that packs straight into a `.big`:

    MainMenu.apt / .const / .dat        the merged movie
    MainMenu_geometry/<id>.ru           its 25 renumbered meshes
    art/Textures/apt_MainMenu_<id>.tga  the 17 textures those meshes sample
    data/movies/*.vp6                   6 tutorials + 4 book animations
    data/audio/sounds/ubook*.wav        the page-turn sounds, whose AudioEvents ROTWK still has
    lang/english/data/audio/speech/     the 6 narration tracks
    data/ini/battleschool.inc           the Video and DialogEvent blocks
    data/battleschool.str               the 19 APT: strings
    BATTLE-SCHOOL.md                    what was built, and the one step left

**The step left is the button.** Opening the book is one call to `ShowBattleSchoolVideo()`, which
this writes into the destination's root frame; *where* that call comes from is the mod's own menu
layout, and guessing at it would be the one part of this that could quietly wreck a shell. The
generated `BATTLE-SCHOOL.md` says exactly what to add.

Dev-only, like `mount_game.py`: it reads two installs by absolute path and is not part of the
package.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from pyBIG import LargeArchive

from sage_apt import apt_to_xml, xml_to_apt
from sage_apt.merge import (
    character_index,
    constant_index,
    copy_functions,
    merge_character,
    rewrite_geometry,
)

__all__ = ["build", "main"]

#: BFME1's `MainMenu` character for the Battle School book - the parchment sprite the root places
#: as `movieContainer` on its `BattleSchool` frame.
BOOK_CHARACTER = 304

#: The root-level callbacks the book itself invokes. They only touch `movieContainer` and
#: `_root.CurrentTutorial` (which the book creates), so they port verbatim; the misspellings are
#: EA's and the book calls them by those exact names.
BOOK_CALLBACKS = (
    "TutortialOpenBookDone",
    "TutorialCloseBookDone",
    "TutorialPageFlipDone",
    "TurtorialMovieDone",
)

#: What the movie sends the engine. Must match
#: `sage_patch.patches.experimental.battle_school.{ENTER,EXIT}` - only the first character reaches
#: the callback, and the two have to differ in it.
ENTER_PARAMS = "enter"
LEAVE_PARAMS = "leave"

#: Functions a destination shell may already have for greying its menu out while a full-screen
#: movie plays. Called only when the destination's root frame actually defines them, so this stays
#: correct against a movie that names them something else - or nothing at all.
DISABLE_BUTTONS = "DisableAllButtons"
REVEAL_BUTTONS = "RevealAllButtons"

#: The frame label a shell returns to when a full-screen movie is done. ROTWK's own menus use
#: `_reshow`, whose frame clears the overlay depth and replays `_show`.
RETURN_LABEL = "_reshow"

#: The overlay depth ROTWK's `MainMenu` reserves for a full-screen movie: its credits frame places
#: `ShowCreditsMovie` there, and its `_reshow` frame removes it.
OVERLAY_DEPTH = 3

VIDEOS = (
    "tutorialworldmap",
    "tutorialmovesandattacks",
    "tutorialbasesandunits",
    "tutorialheroes",
    "tutorialveterancy",
    "tutorialspecialpowers",
    "bookopen",
    "bookclose",
    "bookflipforward",
    "bookflipback",
)

BOOK_SOUNDS = ("ubookopen", "ubookclose", "ubookpage", "ubookpageb")

NARRATION = tuple(f"tutorial{n}" for n in range(1, 7))

#: `Video` blocks, in BFME1's own order and wording. ROTWK's `video.ini` dropped every one of
#: them; Edain's still declares them, pointing at files that are not there.
VIDEO_INI = """\
;; Battle School - the tutorial book and the six videos it plays.
;; Restored from BFME1. See sage_patch/docs/battle-school.md.

Video TutorialOpenBook
    Filename = BookOpen
    Comment = "Tutorial book open animation"
End

Video TutorialCloseBook
    Filename = BookClose
    Comment = "Tutorial book close animation"
End

Video TutorialNextPage
    Filename = BookFlipForward
    Comment = "Tutorial book flip to next page animation"
End

Video TutorialPrevPage
    Filename = BookFlipBack
    Comment = "Tutorial book flip to previous page animation"
End

Video TutorialWorldMap
    Filename = TutorialWorldMap
    Comment = "Tutorial movie for the living world map."
End

Video TutorialMovesAndAttacks
    Filename = TutorialMovesAndAttacks
    Comment = "Tutorial movie for moves and attacks."
End

Video TutorialBasesAndUnits
    Filename = TutorialBasesAndUnits
    Comment = "Tutorial movie for bases and units."
End

Video TutorialHeroes
    Filename = TutorialHeroes
    Comment = "Tutorial movie for heroes."
End

Video TutorialVeterancy
    Filename = TutorialVeterancy
    Comment = "Tutorial movie for veterancy."
End

Video TutorialSpecialPowers
    Filename = TutorialSpecialPowers
    Comment = "Tutorial movie for special powers."
End
"""

#: The narration, as BFME1 declares it. The `AudioEvent`s for the page-turn sounds are **not**
#: here: ROTWK's own `soundeffects.ini` still has `Gui_BookOpen`, `Gui_BookClose` and
#: `Gui_BookPageTurn`, and only the wave files behind them are missing.
SPEECH_INI = """\
;; The Battle School narration. The Gui_Book* AudioEvents these play alongside are still in
;; ROTWK's stock soundeffects.ini; only the UBook* waves had to come back.

DialogEvent TutorialWorldMap
  Filename = Tutorial1.mp3
  SubmixSlider = Movie
  Volume = 80
End

DialogEvent TutorialMovesAndAttacks
  Filename = Tutorial2.mp3
  SubmixSlider = Movie
  Volume = 80
End

DialogEvent TutorialBasesAndUnits
  Filename = Tutorial3.mp3
  SubmixSlider = Movie
  Volume = 80
End

DialogEvent TutorialHeroes
  Filename = Tutorial4.mp3
  SubmixSlider = Movie
  Volume = 80
End

DialogEvent TutorialVeterancy
  Filename = Tutorial5.mp3
  SubmixSlider = Movie
  Volume = 80
End

DialogEvent TutorialSpecialPowers
  Filename = Tutorial6.mp3
  SubmixSlider = Movie
  Volume = 80
End
"""

#: The `APT:` labels the book asks `TheGameText` for, with BFME1's English text. The `.apt` names
#: them with a leading `$`; the table keys them without one.
STRINGS = {
    "APT:BattleSchool": "BATTLE SCHOOL",
    "APT:BattleSchoolTitle": "Battle School",
    "APT:Tutorial": "TUTORIAL",
    "APT:ExitTutorial": "EXIT TUTORIAL",
    "APT:WorldMapTutorial": "WORLD MAP",
    "APT:WorldMapTitle": "World Map",
    "APT:Moves&AttacksTutorial": "MOVES & ATTACKS",
    "APT:Moves&AttacksTitle": "Moves & Attacks",
    "APT:Bases&UnitsTutorial": "BASES & UNITS",
    "APT:Bases&UnitsTitle": "Bases & Units",
    "APT:HeroesTutorial": "HEROES",
    "APT:HeroesTitle": "Heroes",
    "APT:VeterancyTutorial": "VETERANCY",
    "APT:VeterancyTitle": "Veterancy",
    "APT:SpecialPowersTutorial": "SPECIAL POWERS",
    "APT:SpecialPowersTitle": "Special Powers",
}


def _archive_files(archive: Path, wanted) -> dict[str, bytes]:
    """Read the entries of one `.big` whose lowercased name satisfies ``wanted``."""
    handle = LargeArchive(str(archive))
    return {entry: handle.read_file(entry) for entry in handle.file_list() if wanted(entry.lower())}


def _meshes(archive: Path, movie: str) -> dict[int, str]:
    """`geometry id -> .ru text` for a movie's `<Movie>_geometry` folder."""
    pattern = re.compile(rf"{re.escape(movie)}_geometry[\\/](\d+)\.ru$", re.I)
    found: dict[int, str] = {}
    for entry, blob in _archive_files(archive, lambda name: name.endswith(".ru")).items():
        match = pattern.match(entry)
        if match:
            found[int(match.group(1))] = blob.decode("latin-1")
    return found


def _textures(archive: Path, movie: str) -> dict[int, bytes]:
    """`texture id -> .tga bytes` for a movie's `art/Textures/apt_<Movie>_<id>.tga`."""
    pattern = re.compile(rf"apt_{re.escape(movie)}_(\d+)\.tga$", re.I)
    found: dict[int, bytes] = {}
    for entry, blob in _archive_files(archive, lambda name: name.endswith(".tga")).items():
        match = pattern.search(entry)
        if match:
            found[int(match.group(1))] = blob
    return found


def _rects(text: str) -> dict[int, str]:
    """The crop-rectangle rows of a `.dat` image map, as `image id -> "x y w h"`."""
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"(?m)^\s*(\d+)=(.+)$", text)}


def _root_action(root: ET.Element) -> ET.Element:
    """The `<action>` on a movie's root frame 0 - where a shell keeps its functions."""
    frames = root.find("movieclip").find("frames")  # type: ignore[union-attr]
    action = frames[0].find("action")
    if action is None:
        raise SystemExit("the destination's root frame 0 carries no <action> to add functions to")
    return action


def _defines(action: ET.Element) -> set[str]:
    return {
        node.get("name", "") for node in action if node.tag in ("definefunction", "definefunction2")
    }


def _call(action: ET.Element, body: ET.Element, name: str) -> None:
    """`name()` - a plain call to a root function, no arguments."""
    ET.SubElement(body, "pushzero")
    ET.SubElement(body, "callnamedfuncpop", {"val": str(constant_index(action, name))})


def _game_code(action: ET.Element, body: ET.Element, command: str, params: str) -> None:
    """`_root.GameCode(command, params)` - arguments push in reverse, then the count, then the
    object, which is the calling convention every button in these movies uses."""
    ET.SubElement(body, "pushconstant", {"val": str(constant_index(action, params))})
    ET.SubElement(body, "pushconstant", {"val": str(constant_index(action, command))})
    ET.SubElement(body, "pushbyte", {"val": "2"})
    ET.SubElement(body, "pushvalue", {"val": str(constant_index(action, "_root"))})
    ET.SubElement(body, "callnamedmethodpop", {"val": str(constant_index(action, "GameCode"))})


def _method(action: ET.Element, body: ET.Element, obj: str, method: str) -> None:
    """`obj.method()` on a root-scope object."""
    ET.SubElement(body, "pushzero")
    ET.SubElement(body, "pushvalue", {"val": str(constant_index(action, obj))})
    ET.SubElement(body, "callnamedmethodpop", {"val": str(constant_index(action, method))})


def _function(action: ET.Element, name: str) -> ET.Element:
    """Append a `definefunction` to the block, before its trailing `<end/>`, and return its body."""
    element = ET.Element("definefunction", {"name": name, "size": "0"})
    ET.SubElement(element, "body")
    end = action.find("end")
    if end is None:
        action.append(element)
    else:
        action.insert(list(action).index(end), element)
    constant_index(action, name)
    return element.find("body")  # type: ignore[return-value]


def _write_glue(action: ET.Element, frame: int, has_return_label: bool) -> None:
    """The three functions that open and close the book.

    `ShowBattleSchoolVideo` is what a menu button calls; the other two are what the book calls back
    into. They are written fresh rather than copied from BFME1, whose versions drive four root
    objects (`DebugMenu`, `Image`, `ExitMenu`, `MainMenu`) that no ROTWK shell has - copying those
    would produce calls into nothing, which ActionScript performs silently.
    """
    have = _defines(action)

    body = _function(action, "ShowBattleSchoolVideo")
    if DISABLE_BUTTONS in have:
        _call(action, body, DISABLE_BUTTONS)
    _game_code(action, body, "BattleSchool", ENTER_PARAMS)
    ET.SubElement(body, "gotoframe", {"frame": str(frame)})
    ET.SubElement(body, "noarg", {"action": "6"})  # play

    body = _function(action, "HideBattleSchoolVideo")
    _method(action, body, "movieContainer", "Close")

    body = _function(action, "AfterBattleSchoolVideoOut")
    if REVEAL_BUTTONS in have:
        _call(action, body, REVEAL_BUTTONS)
    _game_code(action, body, "BattleSchool", LEAVE_PARAMS)
    if has_return_label:
        ET.SubElement(body, "gotolabel", {"label": RETURN_LABEL})
    else:
        ET.SubElement(body, "gotoframe", {"frame": "0"})
    ET.SubElement(body, "noarg", {"action": "6"})  # play


def _add_frame(root: ET.Element, character: int) -> int:
    """Append the root frame that puts the book on screen, and return its index."""
    frames = root.find("movieclip").find("frames")  # type: ignore[union-attr]
    index = len(frames)
    frame = ET.SubElement(frames, "frame", {"id": str(index)})
    ET.SubElement(frame, "removeobject", {"depth": str(OVERLAY_DEPTH)})
    action = ET.SubElement(frame, "action")
    ET.SubElement(action, "noarg", {"action": "7"})  # stop
    ET.SubElement(action, "end")
    ET.SubElement(frame, "framelabel", {"label": "BattleSchool", "frame": str(index)})
    place = ET.SubElement(
        frame,
        "placeobject",
        {
            "depth": str(OVERLAY_DEPTH),
            "character": str(character),
            "rotm00": "1",
            "rotm01": "0",
            "rotm10": "0",
            "rotm11": "1",
            "tx": "512",
            "ty": "384",
            "red": "255",
            "green": "255",
            "blue": "255",
            "alpha": "255",
            "ratio": "0",
            "clipdepth": "-1",
            "unknown": "0",
        },
    )
    ET.SubElement(place, "poflags", {"value": "HasCharacter|HasMatrix|HasName|HasRatio"})
    ET.SubElement(place, "poname", {"name": "movieContainer"})
    return index


def _labels(root: ET.Element) -> set[str]:
    frames = root.find("movieclip").find("frames")  # type: ignore[union-attr]
    return {label.get("label", "") for frame in frames for label in frame.findall("framelabel")}


def build(bfme1: Path, main_menu: Path, out: Path, movie: str = "MainMenu") -> dict[str, object]:
    """Assemble the payload. Returns a summary the CLI prints and the README repeats."""
    out.mkdir(parents=True, exist_ok=True)
    apt_archive = bfme1 / "apt" / "mainmenu.big"
    for needed in (apt_archive, bfme1 / "audio.big", bfme1 / "data" / "movies"):
        if not needed.exists():
            raise SystemExit(f"{needed} is missing - is {bfme1} a BFME1 install?")

    # --- the source movie, and everything its shapes reach ---
    source_dir = out / ".bfme1"
    source_dir.mkdir(exist_ok=True)
    for entry, blob in _archive_files(
        apt_archive, lambda name: name.endswith((".apt", ".const", ".dat"))
    ).items():
        (source_dir / Path(entry).name).write_bytes(blob)
    source_xml = apt_to_xml(source_dir / "MainMenu.apt")
    source = ET.parse(source_xml).getroot()
    meshes = _meshes(apt_archive, "MainMenu")
    textures = _textures(apt_archive, "MainMenu")
    source_rects = _rects((source_dir / "MainMenu.dat").read_text(encoding="latin-1"))

    # --- the destination ---
    work = out / ".work"
    work.mkdir(exist_ok=True)
    for suffix in (".apt", ".const"):
        source_file = main_menu.with_suffix(suffix)
        if not source_file.exists():
            raise SystemExit(f"{source_file} is missing")
        shutil.copy(source_file, work / f"{movie}{suffix}")
    destination_dat = main_menu.with_suffix(".dat")
    dat_text = destination_dat.read_text(encoding="latin-1") if destination_dat.exists() else ""
    destination_xml = apt_to_xml(work / f"{movie}.apt")
    tree = ET.parse(destination_xml)
    destination = tree.getroot()
    before = len(character_index(destination))

    # --- merge the book, then wire it ---
    plan = merge_character(destination, source, BOOK_CHARACTER, meshes)
    action = _root_action(destination)
    copied = copy_functions(action, _root_action(source), BOOK_CALLBACKS)
    frame = _add_frame(destination, plan.character)
    _write_glue(action, frame, RETURN_LABEL in _labels(destination))

    merged_xml = out / f"{movie}.xml"
    tree.write(merged_xml, encoding="utf-8", xml_declaration=True)
    apt, const = xml_to_apt(merged_xml)
    for produced in (apt, const):
        shutil.move(str(produced), out / produced.name)

    # --- the assets those new characters name ---
    geometry_dir = out / f"{movie}_geometry"
    geometry_dir.mkdir(exist_ok=True)
    for old, new in sorted(plan.geometry.items()):
        (geometry_dir / f"{new}.ru").write_text(
            rewrite_geometry(meshes[old], plan), encoding="latin-1"
        )
    texture_dir = out / "art" / "Textures"
    texture_dir.mkdir(parents=True, exist_ok=True)
    missing_textures = [old for old in plan.textures if old not in textures]
    for old, new in sorted(plan.textures.items()):
        if old in textures:
            (texture_dir / f"apt_{movie}_{new}.tga").write_bytes(textures[old])

    # The image map: whatever the destination already said, plus a crop rectangle per copied
    # image - and **only** that. A rectangle row implies a texture of the image's own name, which
    # is how every rect row in either game is written; `<n>-><n>` for n != 1 appears in no shipped
    # movie, and writing it "to leave nothing to infer" is inventing a form the engine may not
    # read. Every `->` row in the corpus points at 1, the shared atlas.
    rows = [dat_text.rstrip("\n"), "", ";; Battle School"]
    for old, new in sorted(plan.textures.items()):
        if old in source_rects:
            rows.append(f"{new}={source_rects[old]}")
    (out / f"{movie}.dat").write_text("\n".join(rows).lstrip("\n") + "\n", encoding="latin-1")

    # --- videos, sounds, narration ---
    movies_out = out / "data" / "movies"
    movies_out.mkdir(parents=True, exist_ok=True)
    found_videos = []
    for name in VIDEOS:
        candidate = bfme1 / "data" / "movies" / f"{name}.vp6"
        if candidate.exists():
            shutil.copy(candidate, movies_out / candidate.name)
            found_videos.append(name)

    sounds_out = out / "data" / "audio" / "sounds"
    sounds_out.mkdir(parents=True, exist_ok=True)
    audio = _archive_files(
        bfme1 / "audio.big",
        lambda name: any(f"{sound}.wav" in name for sound in BOOK_SOUNDS),
    )
    for entry, blob in audio.items():
        (sounds_out / Path(entry).name).write_bytes(blob)

    speech_out = out / "lang" / "english" / "data" / "audio" / "speech"
    speech_out.mkdir(parents=True, exist_ok=True)
    narration = _archive_files(
        bfme1 / "lang" / "englishaudio.big",
        lambda name: any(f"{n}.mp3" in name for n in NARRATION),
    )
    for entry, blob in narration.items():
        (speech_out / Path(entry).name).write_bytes(blob)

    # --- ini and strings ---
    ini_out = out / "data" / "ini"
    ini_out.mkdir(parents=True, exist_ok=True)
    (ini_out / "battleschool.inc").write_text(VIDEO_INI + "\n" + SPEECH_INI, encoding="latin-1")
    # CRLF, because that is what the shipped `lotr.str` uses and a string table is not the place
    # to find out whether the parser minds.
    table = "".join(f'{key}\r\n"{value}"\r\nEND\r\n\r\n' for key, value in STRINGS.items())
    # `newline=""` so the CRLFs above survive: on Windows the default would translate each one
    # into `\r\r\n`.
    (out / "data" / "battleschool.str").write_text(table, encoding="latin-1", newline="")

    shutil.rmtree(source_dir, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

    summary: dict[str, object] = {
        "movie": movie,
        "characters": f"{before} -> {len(character_index(destination))}",
        "book_character": plan.character,
        "frame": frame,
        "geometry": len(plan.geometry),
        "textures": len(plan.textures),
        "missing_textures": sorted(missing_textures),
        "imports_added": plan.imports,
        "callbacks": sorted(copied),
        "videos": found_videos,
        "sounds": sorted(Path(e).name for e in audio),
        "narration": sorted(Path(e).name for e in narration),
    }
    (out / "BATTLE-SCHOOL.md").write_text(_readme(summary), encoding="utf-8")
    return summary


def _readme(summary: dict[str, object]) -> str:
    movie = summary["movie"]
    callbacks = ", ".join(f"`{name}`" for name in summary["callbacks"])  # type: ignore[union-attr]
    return f"""\
# Battle School - the mod-side payload

Built by `tools/build_battle_school.py` from a BFME1 install. The engine half is `sage-patch apply
battle-school`; without it the menu goes permanently silent when you leave the book, because the
`MainMenuToBattleSchool` transition is a `SOUNDFADE` with `LeaveSilent = Yes` and nothing in a
stock ROTWK reverses it.

## What is here

| | |
|---|---|
| `{movie}.apt` / `.const` | the merged movie - characters {summary["characters"]} |
| the book | character **{summary["book_character"]}**, on root frame **{summary["frame"]}** |
| `{movie}_geometry/` | {summary["geometry"]} renumbered meshes |
| `art/Textures/` | {summary["textures"]} textures |
| `{movie}.dat` | the destination's image map plus one `->` and one `=` row per copied image |
| `data/movies/` | {len(summary["videos"])} videos |
| `data/audio/sounds/` | {len(summary["sounds"])} page-turn waves |
| `lang/english/data/audio/speech/` | {len(summary["narration"])} narration tracks |
| `data/ini/battleschool.inc` | the `Video` and `DialogEvent` blocks |
| `data/battleschool.str` | {len(STRINGS)} `APT:` strings |
| `{movie}.xml` | the merged movie's editable source - `sage-apt to-apt` recompiles it |

Root functions written into frame 0:

- `ShowBattleSchoolVideo` - opens the book. **This is the one a menu button has to call.**
- `HideBattleSchoolVideo` - closes it early.
- `AfterBattleSchoolVideoOut` - tells the engine to un-fade, and returns to the menu.
- BFME1's own {callbacks} - the book's own callbacks, copied verbatim. The misspellings are EA's
  and the book calls them by those exact names.

## Packing it

Everything here except `{movie}.xml` goes into one `.big` that mounts ahead of the stock archives -
the same leading-underscore trick every mod uses. `data/ini/battleschool.inc` has to be `#include`d
from the mod's `video.ini` and `speech.ini`, or its blocks pasted into them;
`data/battleschool.str` merges into the mod's `lotr.str`.

Note that ROTWK's stock `soundeffects.ini` **already has** `Gui_BookOpen`, `Gui_BookClose` and
`Gui_BookPageTurn` - only the waves under them were missing, which is why there is no
`soundeffects` fragment here.

## The one step left: the button

Nothing calls `ShowBattleSchoolVideo()` yet. Where it is called from is the mod's own menu layout,
which is why this tool does not guess. Add a button to the shell's nav that does:

    _root.ShowBattleSchoolVideo()

and, if you want BFME1's blinking-until-seen behaviour, read
`_root.getExtern("BlinkBattleSchoolOff")` on the frame that places it - the engine still answers
that, from the `FlashTutorial` preference, and still clears it by itself after five launches.

The button's caption is `$BattleSchool`.

## What it will look like wrong

- **Silent menu after leaving** - the `battle-school` patch is not applied, or the movie is sending
  something other than `"{LEAVE_PARAMS}"`.
- **Untextured black shapes** - the `art/Textures` files or the `.dat` rows did not make it into
  the mounted archive.
- **The book opens on a blank page** - the `.vp6` files are missing, or `battleschool.inc` is not
  being included.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bfme1", type=Path, required=True, help="a BFME1 install folder")
    parser.add_argument(
        "--main-menu",
        type=Path,
        required=True,
        help="the destination MainMenu.apt (its .const and .dat are read beside it)",
    )
    parser.add_argument("--out", type=Path, required=True, help="where to write the payload")
    parser.add_argument(
        "--movie", default="MainMenu", help="the destination movie's name (default: MainMenu)"
    )
    args = parser.parse_args(argv)

    summary = build(args.bfme1, args.main_menu, args.out, args.movie)
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        print(f"  {key:{width}}  {value}")
    print(f"\nwrote {args.out}  -  read {args.out / 'BATTLE-SCHOOL.md'} for what is left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
