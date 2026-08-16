"""One palette vocabulary for every HTML surface the tools generate.

Each generated page keeps its own markup and its own component CSS; what they share is the
colour underneath it. A *skin* is that colour set. `steel` is the default - a gunmetal ground
with a polished-steel trim - and there is one skin per Edain faction besides, each sampled
from that faction's own emblem by `tools/build_faction_skins.py` (see its docstring for the
rules; the values it derives are pasted into the generated block at the foot of this module).

Faction-specific output takes its faction's skin, everything else takes `steel`:

    from sage_utils import webtheme

    skin = webtheme.skin_for_label("Dwarves (Ered Luin)") or webtheme.STEEL
    css = webtheme.aggregate_tokens(skin)

The surfaces name their tokens differently - `sage_replay.aggregate` says `--above`/`--below`
for the diverging win-rate mark, `tools/build_replay_site.py` says `--accent`/`--win`/`--loss`
- so a skin holds semantic fields and each surface gets an adapter that spells them the way
its own stylesheet already reads. Adding a surface means adding an adapter here, not another
palette.

Three things are deliberately *not* the faction's to recolour, because they mean the same
thing on every page: the categorical series palette `--s1`..`--s8`, the amber warning pair,
and the type stack. They are constants below and identical in every skin.

Every skin is dark. The generated pages used to carry a light column selected by
`prefers-color-scheme`; a skin replaces both columns, so a page with a skin renders the same
way whatever the reader's OS prefers. `light_tokens` is not something this module has - if the
light column comes back, it comes back as a second lightness ramp in the generator, not as a
hand-written second palette here.
"""

from __future__ import annotations

from typing import NamedTuple

__all__ = [
    "Skin",
    "SKINS",
    "STEEL",
    "aggregate_tokens",
    "mix",
    "site_tokens",
    "wiki_tokens",
    "skin_for_emblem",
    "skin_for_label",
]


class Skin(NamedTuple):
    """A ground, an ink ramp, two hairlines, a trim and the diverging pair.

    `trim` is the faction's own colour - the one thing that identifies the skin - and carries
    small text (links, side labels, the primary button), so it is held at 4.5:1 or better
    against `surface` by the generator. `link`/`mark` are the diverging pair, cool above the
    midpoint and warm below it; where a faction's trim lands in one of those two zones, the
    generator rotates that side away rather than let the faction paint over the meaning.
    """

    name: str
    plane: str  # the page ground
    surface: str  # panels, tiles, table backgrounds
    raise_: str  # a step above the surface: hovers, nested rows
    ink: str
    ink_2: str
    muted: str
    hair: str  # borders
    hair_2: str  # rules between rows, the quieter hairline
    trim: str
    trim_hi: str
    mark: str  # the negative side of the diverging pair
    link: str  # the positive side, and inline links
    good: str
    track: str  # the unfilled part of a bar


# The categorical series palette, in its fixed order: a validated CVD-safe ordering, stepped
# for a dark surface. A ninth series never gets a new hue, it reuses the cycle with a dash
# pattern as the distinguishing second channel.
SERIES = (
    "#3987e5",
    "#199e70",
    "#c98500",
    "#3f9e3f",
    "#9085e9",
    "#e66767",
    "#d55181",
    "#d95926",
)

# Warnings are semantics, not identity: the same ambers on every skin. `PART_INK` is the
# reference's third state - a block the engine only partly agrees with - and stays a step
# warmer than a plain warning.
WARN_INK = "#e7b95a"
WARN_BG = "#3a2f14"
PART_INK = "#e0b458"

SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
MONO = "ui-monospace, Consolas, monospace"


def _series_tokens() -> str:
    return " ".join(f"--s{i}: {hex_};" for i, hex_ in enumerate(SERIES, start=1))


def aggregate_tokens(skin: Skin) -> str:
    """`:root` for `sage_replay.aggregate`'s stylesheet, in the names it already reads."""
    return (
        ":root {\n"
        f"  --plane: {skin.plane}; --surface: {skin.surface}; "
        f"--ink: {skin.ink}; --ink-2: {skin.ink_2};\n"
        f"  --muted: {skin.muted}; --grid: {skin.hair_2}; --ring: {skin.hair};\n"
        f"  --track: {skin.track}; --above: {skin.link}; --below: {skin.mark};\n"
        f"  --trim: {skin.trim}; --trim-hi: {skin.trim_hi}; --raise: {skin.raise_};\n"
        f"  --warn-ink: {WARN_INK}; --warn-bg: {WARN_BG};\n"
        f"  {_series_tokens()}\n"
        "}\n"
    )


def site_tokens(skin: Skin) -> str:
    """`:root` for the replay browser and the bucket index, in the names they already read."""
    return (
        ":root {\n"
        f"  --bg: {skin.plane}; --fg: {skin.ink}; --muted: {skin.muted}; "
        f"--line: {skin.hair_2};\n"
        f"  --panel: {skin.surface}; --accent: {skin.trim}; "
        f"--win: {skin.good}; --loss: {skin.mark};\n"
        f"  --mono: {MONO};\n"
        f"  --sans: {SANS};\n"
        "}\n"
    )


def wiki_tokens(skin: Skin) -> str:
    """`:root` for the engine reference, in the names it already reads.

    The reference carries two things the other surfaces do not: *soft* tints, a wash of a
    colour over the panel behind it (a hovered nav row, a failed field), and a code ground
    that has to read against the page *and* against a panel, so it steps up rather than down.
    """
    return (
        ":root {\n"
        f"  --bg: {skin.plane}; --fg: {skin.ink}; --muted: {skin.muted}; "
        f"--line: {skin.hair_2};\n"
        f"  --panel: {skin.surface}; --code: {skin.raise_};\n"
        f"  --accent: {skin.trim}; --accent-hi: {skin.trim_hi}; "
        f"--accent-soft: {mix(skin.trim, skin.surface, 0.18)};\n"
        f"  --ok: {skin.good}; --warn: {WARN_INK}; --part: {PART_INK};\n"
        f"  --bad: {skin.mark}; --bad-soft: {mix(skin.mark, skin.surface, 0.16)};\n"
        f"  --mono: {MONO};\n"
        f"  --sans: {SANS};\n"
        "}\n"
    )


def mix(top: str, base: str, amount: float) -> str:
    """`top` laid over `base` at `amount`, as a flat hex.

    Resolved here rather than left to `color-mix()`: these pages are opened straight off a
    filesystem, sometimes from a copy someone was handed, and a flat hex cannot fail.
    """
    pair = [
        (int(top[i : i + 2], 16) * amount + int(base[i : i + 2], 16) * (1 - amount))
        for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{round(channel):02x}" for channel in pair)


def faction_accents(selector: str = ".fac") -> str:
    """One rule per faction: `selector[data-fac="<slug>"]` in that faction's trim.

    For surfaces that stay on one skin but still name factions inline - a replay row listing
    who played what - so the faction reads by colour without the whole page changing under it.
    """
    return "\n".join(
        f'{selector}[data-fac="{slug}"] {{ color: {skin.trim}; }}'
        for slug, skin in sorted(SKINS.items())
        if slug != "steel"
    )


def label_slugs() -> dict[str, str]:
    """Normalised faction label -> skin slug, for a page that has to resolve labels itself.

    The replay browser filters and renders client-side, so it embeds this map and normalises
    the same way `skin_for_label` does: lowercase, drop everything that is not a letter or
    digit (`Dwarves (Ered Luin)` -> `dwarveseredluin`).
    """
    return dict(_LABEL_SKINS)


def skin_for_emblem(filename: str | None) -> Skin | None:
    """The skin sampled from that emblem file, e.g. `Ered-Luin_frontpage.webp`.

    The join every caller already has: a corpus that shows faction emblems knows each
    faction's emblem filename, and that file is what the palette was sampled from.
    """
    if not filename:
        return None
    return SKINS.get(_EMBLEM_SKINS.get(filename, ""))


def skin_for_label(label: str | None) -> Skin | None:
    """The skin for an aggregation label - `FactionWild`, `Dwarves (Ered Luin)`, `Rohan`.

    Matches the mod's own faction labels and the display names a corpus shows for them; an
    unknown label (a non-Edain corpus, an unattributed slot) returns None, and the caller
    falls back to `STEEL`.
    """
    if not label:
        return None
    return SKINS.get(_LABEL_SKINS.get(_normalise(label), ""))


def _normalise(label: str) -> str:
    return "".join(c for c in label.lower() if c.isalnum())


# --- generated by tools/build_faction_skins.py - do not edit below this line ---
# fmt: off

SKINS: dict[str, Skin] = {
    "steel": Skin(
        name="Steel & azure",
        plane="#0d1219", surface="#161e28", raise_="#1e2835",
        ink="#dce5f0", ink_2="#b0bfd0", muted="#8393a6",
        hair="#33445a", hair_2="#263444",
        trim="#7ea9d6", trim_hi="#cde3fb",
        mark="#e2705e", link="#58bcd8", good="#63bb95", track="#1a2430",
    ),

    "gondor": Skin(
        name="Gondor",
        plane="#0d0e0f", surface="#151718", raise_="#1e2123",
        ink="#e2e6e9", ink_2="#bac1c7", muted="#89949e",
        hair="#3b3f42", hair_2="#292c2e",
        trim="#75a0c7", trim_hi="#b9cddf",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#181a1c",
    ),

    "arnor": Skin(
        name="Arnor",
        plane="#0d0e0f", surface="#151618", raise_="#1e2023",
        ink="#e2e5e9", ink_2="#babfc7", muted="#89919e",
        hair="#3b3e42", hair_2="#292b2e",
        trim="#7596c7", trim_hi="#b9c8df",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#181a1c",
    ),

    "belfalas": Skin(
        name="Belfalas",
        plane="#0b0b11", surface="#12131b", raise_="#1b1c26",
        ink="#e2e2e9", ink_2="#babac7", muted="#898a9e",
        hair="#353648", hair_2="#252632",
        trim="#7b78c8", trim_hi="#bab9df",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#15161f",
    ),

    "rohan": Skin(
        name="Rohan",
        plane="#0a1309", surface="#111e0f", raise_="#192a17",
        ink="#e3e9e2", ink_2="#bbc7ba", muted="#8b9e89",
        hair="#31502d", hair_2="#233720",
        trim="#ddcf4b", trim_hi="#ebe5ad",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#142212",
    ),

    "imladris": Skin(
        name="Imladris",
        plane="#090b13", surface="#0f121e", raise_="#171b2a",
        ink="#e2e3e9", ink_2="#babcc7", muted="#898d9e",
        hair="#2d3450", hair_2="#202537",
        trim="#7589c7", trim_hi="#b9c2df",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#121522",
    ),

    "lothlorien": Skin(
        name="Lothlorien",
        plane="#0c1309", surface="#131e0f", raise_="#1c2a17",
        ink="#e4e9e2", ink_2="#bdc7ba", muted="#8e9e89",
        hair="#36502d", hair_2="#273721",
        trim="#70cf65", trim_hi="#b9e4b4",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#162212",
    ),

    "erebor": Skin(
        name="Erebor",
        plane="#130d09", surface="#1e150f", raise_="#2a1e17",
        ink="#e9e5e2", ink_2="#c7bfba", muted="#9e9189",
        hair="#503a2d", hair_2="#372920",
        trim="#dcbf60", trim_hi="#e9dbaf",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#221812",
    ),

    "eredluin": Skin(
        name="Ered Luin",
        plane="#090e13", surface="#0f161e", raise_="#17202a",
        ink="#e2e5e9", ink_2="#bac0c7", muted="#89939e",
        hair="#2d3d50", hair_2="#202b37",
        trim="#d8c74a", trim_hi="#eae3ae",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#121922",
    ),

    "ironhills": Skin(
        name="Iron Hills",
        plane="#13090b", surface="#1e0f13", raise_="#2a171c",
        ink="#e9e2e4", ink_2="#c7babd", muted="#9e898e",
        hair="#502d36", hair_2="#372026",
        trim="#d46d4b", trim_hi="#e8beb0",
        mark="#e09b5c", link="#4dc79b", good="#60be6f", track="#221216",
    ),

    "isengard": Skin(
        name="Isengard",
        plane="#0f0f0d", surface="#181715", raise_="#23221e",
        ink="#e9e7e2", ink_2="#c7c4ba", muted="#9e9989",
        hair="#42403b", hair_2="#2e2d29",
        trim="#d8af30", trim_hi="#ebdcad",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#1c1b18",
    ),

    "mordor": Skin(
        name="Mordor",
        plane="#130909", surface="#1e100f", raise_="#2a1817",
        ink="#e9e2e2", ink_2="#c7baba", muted="#9e8989",
        hair="#502e2d", hair_2="#372120",
        trim="#d25553", trim_hi="#e7b2b1",
        mark="#e09b5c", link="#4dc79b", good="#60be6f", track="#221212",
    ),

    "misty": Skin(
        name="Misty Mountains",
        plane="#120c0a", surface="#1b1411", raise_="#271d1a",
        ink="#e9e4e2", ink_2="#c7bdba", muted="#9e8e89",
        hair="#4a3833", hair_2="#342824",
        trim="#d88442", trim_hi="#eac8ae",
        mark="#e09b5c", link="#4dc79b", good="#60be6f", track="#201714",
    ),

    "angmar": Skin(
        name="Angmar",
        plane="#091213", surface="#0f1c1e", raise_="#17282a",
        ink="#e2e8e9", ink_2="#bac6c7", muted="#899c9e",
        hair="#2d4c50", hair_2="#203537",
        trim="#55cddb", trim_hi="#aee4ea",
        mark="#dd5d4b", link="#4dc79b", good="#60be6f", track="#122122",
    ),

}

STEEL = SKINS["steel"]

# Which emblem each palette was sampled from.
_EMBLEM_SKINS = {
    "Gondor_frontpage.webp": "gondor",
    "Arnor_frontpage.webp": "arnor",
    "Belfalas_frontpage.webp": "belfalas",
    "Rohan_frontpage.webp": "rohan",
    "Imladris_frontpage.webp": "imladris",
    "Lothlorien_frontpage.webp": "lothlorien",
    "Erebor_frontpage.webp": "erebor",
    "Ered-Luin_frontpage.webp": "eredluin",
    "Iron_Hills_frontpage.webp": "ironhills",
    "Isengard_frontpage.webp": "isengard",
    "Mordor_frontpage.webp": "mordor",
    "Misty_Mountains_frontpage.webp": "misty",
    "Angmar_frontpage.webp": "angmar",
}

# Aggregation labels and display names, normalised, to the skin they name.
_LABEL_SKINS = {
    "angmar": "angmar",  # Angmar
    "factionangmar": "angmar",  # FactionAngmar
    "arnor": "arnor",  # Arnor
    "belfalas": "belfalas",  # Belfalas
    "dwarveserebor": "erebor",  # Dwarves (Erebor)
    "erebor": "erebor",  # Erebor
    "dwarveseredluin": "eredluin",  # Dwarves (Ered Luin)
    "eredluin": "eredluin",  # Ered Luin
    "gondor": "gondor",  # Gondor
    "factionimladris": "imladris",  # FactionImladris
    "imladris": "imladris",  # Imladris
    "dwarvesironhills": "ironhills",  # Dwarves (Iron Hills)
    "ironhills": "ironhills",  # Iron Hills
    "factionisengard": "isengard",  # FactionIsengard
    "isengard": "isengard",  # Isengard
    "factionelves": "lothlorien",  # FactionElves
    "lothlorien": "lothlorien",  # Lothlorien
    "factionwild": "misty",  # FactionWild
    "mistymountains": "misty",  # Misty Mountains
    "factionmordor": "mordor",  # FactionMordor
    "mordor": "mordor",  # Mordor
    "factionrohan": "rohan",  # FactionRohan
    "rohan": "rohan",  # Rohan
}
# fmt: on
