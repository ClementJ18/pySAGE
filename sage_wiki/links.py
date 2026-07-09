"""Best-guess internal wiki links for a page draft. The wiki names a unit/hero page after the
object's in-game display name, so a name resolves to a page when that title actually exists -
which is the validation this does, against the wiki's full article-title index (one bulk fetch).

A `PageLinker` covers the two places a draft can carry a link: a table cell that already holds
a known object's display name (`link`), and free prose that mentions one in passing (`linkify`,
longest-match so a phrase wins over a contained shorter name). Only validated names are linked,
so a draft never emits a red link; an offline caller builds no linker and the text stays plain.
"""

import re

from sage_utils.views import display_name_index

# Prose mentions shorter than this are not auto-linked: a two/three-letter name ("Men", "Orc")
# is too often an ordinary word to wrap blindly. A table cell still links it exactly via `link`.
_MIN_PROSE_LEN = 4


class PageLinker:
    """Resolves object display names to `[[wiki page]]` links, given the set of titles that
    actually exist. `candidates` maps a casefolded display name to its `(display_name, title)`;
    only names present in both the game and the wiki get in, so every link points somewhere."""

    def __init__(self, candidates: dict[str, tuple[str, str]]) -> None:
        self._candidates = candidates
        self._pattern = self._compile(candidates)

    @staticmethod
    def _compile(candidates: dict[str, tuple[str, str]]) -> re.Pattern[str] | None:
        """A case-insensitive alternation of the link-worthy display names, longest first so a
        match prefers the full phrase. Built only from names long enough to be safe in prose."""
        names = sorted(
            (shown for shown, _title in candidates.values() if len(shown) >= _MIN_PROSE_LEN),
            key=len,
            reverse=True,
        )
        if not names:
            return None
        alternation = "|".join(re.escape(name) for name in names)
        return re.compile(rf"(?<!\w)({alternation})(?!\w)", re.IGNORECASE)

    @staticmethod
    def _wrap(surface: str, title: str) -> str:
        """`[[title]]` when the surface text already is the title, else a piped `[[title|surface]]`
        so the prose reads as written while pointing at the canonical page."""
        return f"[[{title}]]" if surface == title else f"[[{title}|{surface}]]"

    def link(self, name: str) -> str:
        """`name` wrapped as a link when it names an existing page, else `name` unchanged. For a
        cell that already holds an object's exact display name."""
        match = self._candidates.get(name.casefold())
        return self._wrap(name, match[1]) if match is not None else name

    def linkify(self, text: str) -> str:
        """`text` (plain prose) with the first mention of each known object wrapped as a link.
        Later repeats of the same target are left plain (the wiki links a name once); unknown
        words are untouched."""
        if not text or self._pattern is None:
            return text
        return self._linkify_segment(text, set())

    def _linkify_segment(self, text: str, linked: set[str]) -> str:
        """Link the first un-linked mention of each known object in `text`. `linked` carries the
        names already linked earlier (and is updated), so the once-per-page rule holds."""
        if not text or self._pattern is None:
            return text

        def replace(match: re.Match[str]) -> str:
            surface = match.group(1)
            key = surface.casefold()
            entry = self._candidates.get(key)
            if entry is None or key in linked:
                return surface
            linked.add(key)
            return self._wrap(surface, entry[1])

        return self._pattern.sub(replace, text)


def build_linker(game, titles, object_names=None) -> PageLinker:
    """A `PageLinker` for `game` validated against `titles` (the wiki's existing article titles).
    Every object's display name that matches a title becomes a link target; `object_names` limits
    the candidates (e.g. one faction's objects), defaulting to the whole game."""
    by_title = {title.casefold(): title for title in titles}
    names = list(game.objects.keys()) if object_names is None else list(object_names)
    display_names, _index = display_name_index(game, names)
    candidates: dict[str, tuple[str, str]] = {}
    for shown in display_names:
        title = by_title.get(shown.casefold())
        if title is not None:
            candidates[shown.casefold()] = (shown, title)
    return PageLinker(candidates)
