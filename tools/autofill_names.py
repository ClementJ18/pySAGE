"""Autofill display names into a corpus localisation map.

The maps live under `downloads/names/`, one per mod, each pointed at by the `settings.json` of
the corpora that share it; `rebuild_aggregates.py` adds every rendered code name to its
corpus's map with a blank value to hand-translate. This fills the two kinds it can resolve
automatically against the live BFME2 + RotWK/Edain installs, leaving factions, upgrades, and
composed labels (`CPObject1`, `X (unpacks Y)`, `fortress hero (command slot N)`) for
hand-translation:

  objects   - a ThingTemplate's localized DisplayName. A child template with no DisplayName of
              its own inherits one up the `ChildObject` chain (its effective in-game name), so
              variants (`..._Upgraded`, `..._Loyal`, numbered buildings) get named too.

  sciences  - a science has no DisplayName; its player-facing name lives on the CommandButton
              that buys it. Each science is filled with the resolved `TextLabel` of the first
              CommandButton whose `Science` lists it (`SCIENCE_Avalanche` -> button
              `Command_PurchaseSpellAvalanche` -> `CONTROLBAR:Avalanche` -> "Avalanche").

A code name with no resolvable name (no DisplayName up the chain, no buying button) stays blank.

Non-destructive: only blank entries are filled (a hand-written value is never overwritten
unless --overwrite is given). Rerun after a rebuild surfaces new code names.

Everything resolves against whatever game is installed at the `--game` roots, so pass the
names file matching the installed mod - filling a mod's map from another mod's install would
bake in the wrong display names.

Run from anywhere:  python tools/autofill_names.py downloads/names/edain_names.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # allow running this file directly, not just as a module

from sage_ini.loader import load_game  # noqa: E402
from sage_utils.gameroot import resolve_game_roots  # noqa: E402

DEFAULT_GAME = [Path(r"C:\BFME2"), Path(r"C:\RotWK")]


def _rel(path: Path) -> Path:
    """`path` repo-relative for printing, or as-is when it lives outside the repo."""
    try:
        return path.relative_to(REPO)
    except ValueError:
        return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", type=Path, help="localisation map to fill")
    parser.add_argument(
        "--game",
        type=Path,
        action="append",
        default=None,
        help="game root (repeatable, base first); defaults to C:\\BFME2 then C:\\RotWK",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="also replace non-blank entries (default: fill blanks only)",
    )
    args = parser.parse_args(argv)

    roots = args.game or DEFAULT_GAME
    print(f"loading game from {', '.join(str(g) for g in roots)} ...")
    game = load_game(resolve_game_roots(roots, None)).game
    strings = {label.upper(): value for label, value in game.strings.items()}

    def resolve(label) -> str | None:
        """A string-table label ("CONTROLBAR:Avalanche") -> its localized value, or None."""
        if isinstance(label, list):  # TextLabel/DisplayName parse as single-element lists
            label = label[0] if label else None
        return strings.get(label.upper()) if isinstance(label, str) else None

    # An object's effective in-game name: its own DisplayName, else the nearest ancestor's up
    # the ChildObject chain (a top-level Object has no `.parent`, so the climb stops there).
    def object_display(key: str) -> str | None:
        obj = game.objects.get(key)
        while obj is not None:
            display = resolve(obj._fields.get("DisplayName"))
            if display:
                return display
            obj = getattr(obj, "parent", None)
        return None

    # Each science's name comes from the first CommandButton that buys it: map science code
    # name -> that button's resolved TextLabel. Buttons are visited in load order, so the
    # first one referencing a science wins.
    science_display: dict[str, str] = {}
    for button in game.commandbuttons.values():
        sciences = button._fields.get("Science")
        if not sciences:
            continue
        text = resolve(button._fields.get("TextLabel"))
        if not text:
            continue
        for science in sciences if isinstance(sciences, list) else [sciences]:
            science_display.setdefault(str(science), text)

    # utf-8-sig, not utf-8: the map is hand-edited, so a UTF-8 BOM (a Windows editor or
    # PowerShell redirect) must not crash the fill (it is rewritten below without one).
    names: dict[str, str] = json.loads(args.names.read_text(encoding="utf-8-sig"))
    is_object = {key: key in game.objects for key in names}
    is_science = {key: key in game.sciences for key in names}
    filled_objects = filled_sciences = 0
    for key, value in names.items():
        if not (is_object[key] or is_science[key]):
            continue
        if value and not args.overwrite:
            continue
        display = object_display(key) if is_object[key] else science_display.get(key)
        if display:
            names[key] = display
            if is_object[key]:
                filled_objects += 1
            else:
                filled_sciences += 1

    text = json.dumps(names, ensure_ascii=False, indent=2, sort_keys=True)
    args.names.write_text(text + "\n", encoding="utf-8")
    named_obj = sum(1 for k, o in is_object.items() if o and names[k])
    named_sci = sum(1 for k, s in is_science.items() if s and names[k])
    print(
        f"filled {filled_objects} object + {filled_sciences} science name(s); "
        f"{named_obj}/{sum(is_object.values())} objects, "
        f"{named_sci}/{sum(is_science.values())} sciences now named, "
        f"{len(names)} keys total -> {_rel(args.names.resolve())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
