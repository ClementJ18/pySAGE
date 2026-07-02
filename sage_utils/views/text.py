"""Localization and display-name views: string-table lookups (case-insensitive fallback),
flattening in-game `\\n` markers, and friendly labels for objects and upgrade toggles."""

from collections import Counter

from sage_utils.views.base import safe


def _strings_ci(game) -> dict[str, str]:
    """A case-insensitive view of the string table, cached per game and rebuilt when its
    size changes. `.str` labels and the ini references that name them disagree on case,
    so a direct lookup misses; this keys every string by its lower-cased label."""
    cache = getattr(game, "_strings_ci_cache", None)
    if cache is None or cache[0] != len(game.strings):
        index = {key.lower(): value for key, value in game.strings.items()}
        cache = (len(game.strings), index)
        game._strings_ci_cache = cache
    return cache[1]


def clean_text(text: str | None) -> str | None:
    """Flatten a localized string's literal `\\n` line breaks into flowing prose: each
    becomes a space, with a period inserted when the preceding text ends in a letter or
    digit so stacked lines read as sentences. Text without `\\n` (and None) passes through."""
    if not text or "\\n" not in text:
        return text
    segments = [seg.strip() for seg in text.split("\\n")]
    segments = [seg for seg in segments if seg]
    for i, seg in enumerate(segments[:-1]):
        if seg[-1].isalnum():
            segments[i] = seg + "."
    return " ".join(segments)


def localize(game, label) -> str:
    """A string-table label resolved to its display text (the raw label if absent). Only
    the first of a toggle button's several labels is used; resolution falls back to a
    case-insensitive lookup. Returns raw text — a display caller flattens it via `clean_text`."""
    if isinstance(label, list):
        label = label[0] if label else None
    if not label:
        return ""
    first = str(label).split()[0]
    value = game.strings.get(first)
    if value is None:
        value = _strings_ci(game).get(first.lower())
    return first if value is None else value


def _resolve_label(game, label) -> str | None:
    """Like `localize`, but a label naming no loaded string yields None (not the raw
    label), so callers can fall back to a template name of their own."""
    if isinstance(label, list):
        label = label[0] if label else None
    if not label:
        return None
    first = str(label).split()[0]
    return game.strings.get(first) or _strings_ci(game).get(first.lower())


def display_name(game, obj) -> str | None:
    """An object's localized `DisplayName`, or None when it declares none or the label
    isn't in the string table."""
    return _resolve_label(game, safe(lambda: obj.DisplayName))


def description(game, obj) -> str | None:
    """An object's localized `Description` (the flavour/help text shown in-game), falling
    back to its `RecruitText` when it declares no description. None when neither resolves to
    a loaded string."""
    return _resolve_label(game, safe(lambda: obj.Description)) or _resolve_label(
        game, safe(lambda: obj.RecruitText)
    )


def display_name_index(game, names) -> tuple[list[str], dict[str, str]]:
    """Returns `(display_names, index)`: a sorted list of the distinct display names and
    a case-insensitive dict from display name back to raw object name. Objects without a
    display name are skipped; when several share one, the first in `names` order wins."""
    index: dict[str, str] = {}
    labels: dict[str, str] = {}
    for name in names:
        obj = game.objects.get(name)
        shown = display_name(game, obj) if obj is not None else None
        if shown:
            key = shown.casefold()
            if key not in index:
                index[key] = name
                labels[key] = shown
    return sorted(labels.values()), index


def upgrade_label(game, name: str) -> str:
    """An upgrade's localized DisplayName, or its raw template name when it declares none or
    isn't loaded — the friendly label for an upgrade/ability toggle ("Fire Arrows", not
    `Upgrade_FireArrows`)."""
    upgrade = game.upgrades.get(name)
    if upgrade is None:
        return name
    return display_name(game, upgrade) or name


def upgrade_toggle_labels(game, names) -> dict[str, str]:
    """Map each upgrade name to its display label for a toggle list, keyed by the raw name the
    UI still drives the upgrade with. A label shared by more than one upgrade in `names` keeps
    the raw template name in parentheses ("Fire Arrows (Upgrade_FireArrows)") so the duplicates
    stay distinguishable; a name with no localized label is left as-is."""
    labels = {name: upgrade_label(game, name) for name in names}
    counts = Counter(labels.values())
    return {
        name: (f"{label} ({name})" if counts[label] > 1 and label != name else label)
        for name, label in labels.items()
    }
