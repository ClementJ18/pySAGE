"""Rendering and updating the wiki's `Armor Sets/*` subpages from parsed armors.

The wiki keeps each armor set's damage-type table on a per-initial subpage, as a
collapsible wikitable section keyed by its lower-cased name. Porting is merge, not
overwrite: armor order is hand-curated, so `merge_page` refreshes each existing section
in place and only appends armors the page lacks, for the smallest diff.
"""

import re

from sage_utils.views import percent

PAGE_PREFIX = "Armor Sets/"
_ROW_ATTRS = 'class="mw-collapsible mw-collapsed"'
_HEADER = re.compile(r"^=== (?P<slug>.+?) ===[ \t]*$", re.MULTILINE)


def _page_letter(name: str) -> str:
    """The subpage letter an armor belongs on: its upper-cased initial (else `#`)."""
    first = name[0].upper()
    return first if first.isalpha() else "#"


def render_section(armor) -> str:
    """One armor's collapsible wikitable section, matching the wiki's layout."""
    name = armor.name
    slug = name.lower()
    rows = list(armor.damage_scalars().items())
    if armor.FlankedPenalty:
        rows.append(("FlankedPenalty", armor.FlankedPenalty))

    lines = [
        f"=== {slug} ===",
        f"<section begin={slug} />",
        '{| class="wikitable"',
        f'! colspan="2" |  <span class="mw-customtoggle-{name} wikia-menu-button" '
        f'style="float:left">[+/-]</span>{name}',
    ]
    for damage_type, value in rows:
        lines.append(f'|- id="mw-customcollapsible-{name}" {_ROW_ATTRS}')
        # The wiki pads the FlankedPenalty row with an extra space; match it so an
        # already-correct page is left untouched rather than reflowed.
        separator = "||  " if damage_type == "FlankedPenalty" else "|| "
        lines.append(f"| {damage_type} {separator}{percent(value)}")
    lines.append("|}")
    lines.append(f"<section end={slug} />")
    return "\n".join(lines)


def armor_sections_by_page(game) -> dict[str, tuple[dict[str, str], list[str]]]:
    """`{page title -> ({slug: section text}, [slug in data order])}`. Every named armor is
    rendered and filed under its initial; a page appears only for a letter with an armor."""
    pages: dict[str, tuple[dict[str, str], list[str]]] = {}
    for armor in game.armorsets.values():
        if not getattr(armor, "name", None):
            continue
        title = PAGE_PREFIX + _page_letter(armor.name)
        sections, order = pages.setdefault(title, ({}, []))
        slug = armor.name.lower()
        if slug not in sections:
            order.append(slug)
        sections[slug] = render_section(armor)
    return pages


def _split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A page's preamble and its `=== slug ===` sections (each body keeps its header)."""
    headers = list(_HEADER.finditer(text))
    if not headers:
        return text, []
    preamble = text[: headers[0].start()]
    sections = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        sections.append((match.group("slug").strip().lower(), text[match.start() : end]))
    return preamble, sections


def merge_page(existing: str, sections: dict[str, str], order: list[str]) -> str:
    """The page text with each known armor's section refreshed in place and new ones appended
    in data order. A page with no recognizable sections starts from `__NOTOC__`."""
    preamble, existing_sections = _split_sections(existing)
    seen: set[str] = set()
    bodies: list[str] = []
    for slug, body in existing_sections:
        bodies.append(sections[slug] if slug in sections else body.strip())
        seen.add(slug)
    for slug in order:
        if slug not in seen:
            bodies.append(sections[slug])
            seen.add(slug)

    head = preamble.strip() or "__NOTOC__"
    return head + "\n" + "\n\n".join(bodies)
