"""Reading and editing a wiki page's primary infobox (a `{{Infobox unit |cost = 300 …}}`
template). Values are written back in place - the rest of the page and the spacing around
each parameter are preserved - for the smallest diff. Parsing is delegated to
`mwparserfromhell`; callers work only with `Infobox`.
"""

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode

# Parameter names that mark a template as a unit/object infobox, used to pick the primary
# one when no template is literally named "Infobox…". Includes the Hero infobox's variants
# (`object`, attack-type-suffixed combat stats) so hero pages are recognized too.
INFOBOX_HINT_PARAMS = frozenset(
    {
        "object_name",
        "object",
        "cost",
        "command_points",
        "health",
        "damage",
        "damage_melee",
        "damage_ranged",
        "armor",
        "armor_melee",
        "armor_ranged",
        "faction",
        "unit_type",
        "range",
        "range_melee",
        "range_ranged",
        "speed",
        "speed_melee",
        "speed_ranged",
        "health1",
        "resources1",
        "interval1",
    }
)


class Infobox:
    """One page's primary infobox. Edits mutate the template within the parsed page, so
    `render` returns the entire page wikitext with only the changed parameters touched."""

    def __init__(self, page: Wikicode, template: Template) -> None:
        self._page = page
        self._template = template

    @property
    def name(self) -> str:
        """The template name, e.g. ``"Infobox unit"`` (trimmed)."""
        return str(self._template.name).strip()

    def has(self, param: str) -> bool:
        return self._template.has(param)

    def get(self, param: str) -> str | None:
        """The trimmed value of `param`, or None when the infobox has no such param."""
        if not self._template.has(param):
            return None
        return str(self._template.get(param).value).strip()

    def fields(self) -> dict[str, str]:
        """Every parameter as ``name -> trimmed value``, in document order."""
        return {str(p.name).strip(): str(p.value).strip() for p in self._template.params}

    def set(self, param: str, value: str) -> None:
        """Set `param` to `value`, preserving spacing; updates it if present, else appends it."""
        self._template.add(param, value, preserve_spacing=True)

    def render(self) -> str:
        """The full page wikitext with the infobox's edits applied."""
        return str(self._page)


def _is_named_infobox(template: Template) -> bool:
    return "infobox" in str(template.name).strip().lower()


def _hint_score(template: Template) -> int:
    names = {str(p.name).strip().lower() for p in template.params}
    return len(names & INFOBOX_HINT_PARAMS)


def _names_object(template: Template) -> bool:
    """Whether the template carries an object-id parameter (`object_name`/`object`) - the
    field naming the game object an infobox describes (and so the one we can update)."""
    return any(str(p.name).strip().lower() in ("object_name", "object") for p in template.params)


def parse_infobox(wikitext: str) -> Infobox | None:
    """The page's primary infobox, or None. The first template named `Infobox…`; failing
    that, the one carrying the most known infobox parameters."""
    page = mwparserfromhell.parse(wikitext)
    templates = page.filter_templates()

    for template in templates:
        if _is_named_infobox(template):
            return Infobox(page, template)

    best: Template | None = None
    best_score = 0
    for template in templates:
        score = _hint_score(template)
        if score > best_score:
            best, best_score = template, score

    return Infobox(page, best) if best is not None else None


def parse_infoboxes(wikitext: str) -> list[Infobox]:
    """Every unit/hero/building infobox on the page, in document order. A template qualifies
    when it names an object to update (an `object_name`/`object` parameter) and looks like an
    infobox - named `Infobox…`, or carrying at least two known infobox parameters (the object
    id plus a real stat), so an `{{Ability}}` or navbox that happens to mention an object is
    not mistaken for one. Every returned infobox wraps the same parsed page, so edits to any
    of them render together through `Infobox.render`."""
    page = mwparserfromhell.parse(wikitext)
    return [
        Infobox(page, template)
        for template in page.filter_templates()
        if _names_object(template) and (_is_named_infobox(template) or _hint_score(template) >= 2)
    ]
