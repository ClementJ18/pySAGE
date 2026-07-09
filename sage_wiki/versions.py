"""Reading and updating the Edain wiki's version templates (VER_LATEST, VER_STANDALONE,
VER_UPCOMING). Each is a one-value template whose transcluded version is its
`<includeonly>` body, or - lacking the tags - the content outside any `<noinclude>`
block. `replace_version` swaps the value while leaving the wrappers untouched.
"""

import re

# Template page title -> the human label shown beside its box, in display order.
VERSION_TEMPLATES: dict[str, str] = {
    "Template:VER_LATEST": "Current version",
    "Template:VER_STANDALONE": "Installer version",
    "Template:VER_UPCOMING": "Next version",
}

_INCLUDEONLY = re.compile(r"(<includeonly>)(.*?)(</includeonly>)", re.DOTALL | re.IGNORECASE)
_NOINCLUDE = re.compile(r"<noinclude>.*?</noinclude>", re.DOTALL | re.IGNORECASE)


def extract_version(wikitext: str) -> str:
    """The version string a template transcludes: its includeonly/non-noinclude body."""
    match = _INCLUDEONLY.search(wikitext)
    if match:
        return match.group(2).strip()
    return _NOINCLUDE.sub("", wikitext).strip()


def replace_version(wikitext: str, value: str) -> str:
    """`wikitext` with its transcluded version set to `value`, wrappers preserved: an
    `<includeonly>` body is rewritten in place, else the value replaces the bare content
    and any `<noinclude>` documentation is kept after it."""
    if _INCLUDEONLY.search(wikitext):
        return _INCLUDEONLY.sub(lambda m: m.group(1) + value + m.group(3), wikitext, count=1)
    trailer = "".join(_NOINCLUDE.findall(wikitext))
    return value + trailer
