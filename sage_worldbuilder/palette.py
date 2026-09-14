"""The Place Object palette: the game's objects grouped by side, and under each side by
WorldBuilder's editor categories.

WorldBuilder files each object under its template's `Side` and `EditorSorting`. A template that
names neither is filed where the engine reads it: on the Civilian side, under None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage_utils.views.base import safe

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "CATEGORY_LABELS",
    "CIVILIAN",
    "NO_SORTING",
    "Palette",
    "filter_palette",
    "names_under",
    "object_palette",
]

# EditorSorting name -> the palette heading, in the order the palette lists them.
CATEGORY_LABELS = {
    "STRUCTURE": "Structures",
    "UNIT": "Units",
    "MISC_MAN_MADE": "Man-made props",
    "MISC_NATURAL": "Natural props",
    "SHRUBBERY": "Shrubbery",
    "DEBRIS": "Debris",
    "AUDIO": "Audio",
    "EMITTERS": "Emitters",
    "SELECTABLE": "Selectable",
    "SYSTEM": "System",
    "OBSOLETE": "Obsolete",
}
# The heading for a template that names no EditorSorting: the engine's default, NONE.
NO_SORTING = "None"
# The side of a template that names no Side: the engine's default.
CIVILIAN = "Civilian"

# Side -> heading -> object names.
Palette = dict[str, dict[str, list[str]]]


def _category(template: object) -> str:
    for sorting in getattr(template, "EditorSorting", None) or []:
        label = CATEGORY_LABELS.get(getattr(sorting, "name", str(sorting)).upper())
        if label is not None:
            return label
    return NO_SORTING


def _side(template: object) -> str:
    side = safe(lambda: getattr(template, "Side", None))
    name = str(side).strip() if side is not None else ""
    return name or CIVILIAN


def object_palette(game: Game) -> Palette:
    """Side -> heading -> object names (sorted, ignoring case). Sides come in alphabetical order,
    headings in `CATEGORY_LABELS` order with None last; empty sides and headings are left out."""
    sides: Palette = {}
    for name, template in game.objects.items():
        sides.setdefault(_side(template), {}).setdefault(_category(template), []).append(name)
    order = [*CATEGORY_LABELS.values(), NO_SORTING]
    palette: Palette = {}
    for side in sorted(sides, key=str.casefold):
        groups = sides[side]
        palette[side] = {
            label: sorted(groups[label], key=str.casefold) for label in order if label in groups
        }
    return palette


def filter_palette(groups: Palette, needle: str) -> Palette:
    """The names containing `needle` (ignoring case), keeping the sides and headings that still
    have any."""
    folded = needle.strip().casefold()
    if not folded:
        return groups
    kept: Palette = {}
    for side, categories in groups.items():
        matches = {
            label: [name for name in names if folded in name.casefold()]
            for label, names in categories.items()
        }
        matches = {label: names for label, names in matches.items() if names}
        if matches:
            kept[side] = matches
    return kept


def names_under(groups: Palette, *labels: str) -> list[str]:
    """Every object filed under these headings, whatever side it belongs to; sorted, ignoring
    case, and without the duplicates a name on several sides would give."""
    names = {
        name
        for categories in groups.values()
        for label in labels
        for name in categories.get(label, ())
    }
    return sorted(names, key=str.casefold)
