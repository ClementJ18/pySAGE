"""The Create-a-Hero choices a game's ini data offers, read straight from the `.ini` tree: the
ordered hero classes and their sub-classes, the power `CommandButton`s each class may buy, and
the bling groups with their options. This is what turns the bare names and indices a `.cah`
stores into the choices the game's own Create-a-Hero screen shows - `class_index` 3 is whichever
`CreateAHeroClass` block the data declares fourth, and a `CreateAHero_Helmet` bling index counts
into the sub-class's own helmet list, not a global one.

Only the files that declare a `CommandButton` or the `CreateAHeroSystem` block are parsed - they
are found by a text scan of the tree first - so a scan costs a couple of seconds where a full
`sage_ini` game load costs a minute. Nothing here is resolved through a `Game`: the blocks are
read off the parse tree, so a class upgrade the scan never loaded is still reported by name
rather than dropped.
"""

import re
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from sage_ini.parser.ast import Attribute, Block, Node
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.io import read_text
from sage_ini.stats import ini_root
from sage_ini.strings import parse_str
from sage_utils.sources import LOAD_SUFFIXES, build_merged

__all__ = [
    "BlingGroup",
    "BlingOption",
    "CahGameData",
    "HeroClass",
    "HeroSubClass",
    "PowerOption",
    "load_cah_game_data",
    "scan_ini_root",
]

# The block headers worth parsing a file for: the CaH system block (one file, which pulls in the
# class/bling includes) and command buttons (the powers). Matched against the raw text so the
# scan skips the thousands of object/weapon/fx files a mod ships.
_WANTED_BLOCKS = re.compile(r"^[ \t]*(CommandButton|CreateAHeroSystem)\b", re.IGNORECASE | re.M)

_SCAN_SUFFIXES = frozenset({".ini", ".inc"})

# Field on a CommandButton marking it a Create-a-Hero power: the class upgrade(s) that may buy
# it. A button without one is an ordinary in-game button and never appears in a .cah power slot.
_ALLOWABLE_UPGRADES = "CreateAHeroUIAllowableUpgrades"


@dataclass(frozen=True)
class PowerOption:
    """One power a hero can be given: the `CommandButton` name a `.cah` power slot stores, the
    classes allowed to buy it, and the level it unlocks at."""

    command_button: str
    label: str  # localized TextLabel, "" when it declares none or the string isn't loaded
    class_upgrades: tuple[str, ...]  # CreateAHeroUIAllowableUpgrades, as written
    min_level: int | None
    prerequisite: str | None  # the CommandButton that must be bought first, if any

    @property
    def display(self) -> str:
        """The localized name, falling back to the raw button name."""
        return self.label or self.command_button


@dataclass(frozen=True)
class BlingOption:
    """One choice inside a bling group: the upgrade that applies it, and its localized name."""

    upgrade: str
    label: str

    @property
    def display(self) -> str:
        """The localized name, falling back to the raw upgrade name."""
        return self.label or self.upgrade


@dataclass(frozen=True)
class BlingGroup:
    """One bling group - a row of the Create-a-Hero customization screen. `options` are the
    group's choices in declaration order, which is the order an ATTRIBUTE group's stored index
    counts in (index 0 is value 1); an APPEARANCE group's index counts into the sub-class's own
    subset instead, see `CahGameData.bling_choices`."""

    group_name: str  # the name a .cah bling entry stores, e.g. "CreateAHero_Helmet"
    label: str
    kind: str  # "ATTRIBUTE", "APPEARANCE", or "" when no binder declares one
    ui_slot: int | None
    options: tuple[BlingOption, ...] = ()

    @property
    def is_attribute(self) -> bool:
        """True for a stat group (armor, damage, ...), whose index is a value minus one."""
        return self.kind.upper() == "ATTRIBUTE"

    @property
    def display(self) -> str:
        """The localized group name, falling back to the raw group name."""
        return self.label or self.group_name


@dataclass(frozen=True)
class HeroSubClass:
    """One sub-class of a hero class (`sub_class_index` counts these in declaration order).
    `bling_upgrades` is every upgrade its `BlingUpgrades` lines offer, in order and across all
    groups - `CahGameData.bling_choices` splits them per group."""

    name: str
    upgrade: str
    bling_upgrades: tuple[str, ...]


@dataclass(frozen=True)
class HeroClass:
    """One hero class (`class_index` counts these in declaration order). `upgrade` is the class
    upgrade a power's `CreateAHeroUIAllowableUpgrades` names to offer itself here."""

    name: str
    upgrade: str
    sub_classes: tuple[HeroSubClass, ...]


@dataclass(frozen=True)
class CahGameData:
    """Everything a `.cah` editor can learn from a game's data: the classes in the order
    `class_index` counts them, the power buttons, and the bling groups."""

    classes: tuple[HeroClass, ...]
    powers: tuple[PowerOption, ...]
    bling_groups: tuple[BlingGroup, ...]

    def hero_class(self, class_index: int) -> HeroClass | None:
        """The class at `class_index`, or None when the data declares no such class."""
        if 0 <= class_index < len(self.classes):
            return self.classes[class_index]
        return None

    def sub_class(self, class_index: int, sub_class_index: int) -> HeroSubClass | None:
        """The sub-class at `sub_class_index` of the class at `class_index`, or None."""
        hero_class = self.hero_class(class_index)
        if hero_class is None or not 0 <= sub_class_index < len(hero_class.sub_classes):
            return None
        return hero_class.sub_classes[sub_class_index]

    def group(self, group_name: str) -> BlingGroup | None:
        """The bling group named `group_name`, matched case-insensitively, or None."""
        needle = group_name.lower()
        for group in self.bling_groups:
            if group.group_name.lower() == needle:
                return group
        return None

    def powers_for(self, class_index: int) -> tuple[PowerOption, ...]:
        """The powers the class at `class_index` may buy - those naming its class upgrade in
        `CreateAHeroUIAllowableUpgrades`. Empty when the class is unknown or nothing names it,
        which a caller reads as "no filter available" and falls back to `powers`."""
        hero_class = self.hero_class(class_index)
        if hero_class is None:
            return ()
        upgrade = hero_class.upgrade.lower()
        return tuple(
            power
            for power in self.powers
            if any(name.lower() == upgrade for name in power.class_upgrades)
        )

    def bling_choices(
        self, group_name: str, class_index: int, sub_class_index: int
    ) -> tuple[BlingOption, ...]:
        """The choices a stored bling index counts into for `group_name`, for one sub-class.

        An APPEARANCE group's index counts into the sub-class's own `BlingUpgrades` for that
        group (a helmet index of 1 means a different helmet for each sub-class); an ATTRIBUTE
        group's counts into the group's full option list, where index 0 is in-game value 1.
        Empty when the group is unknown, or when an appearance group's sub-class is."""
        group = self.group(group_name)
        if group is None:
            return ()
        if group.is_attribute:
            return group.options
        sub_class = self.sub_class(class_index, sub_class_index)
        if sub_class is None:
            return ()
        in_group = {option.upgrade.lower(): option for option in group.options}
        return tuple(
            in_group[name.lower()] for name in sub_class.bling_upgrades if name.lower() in in_group
        )


def _blocks(nodes: Sequence[Node], name: str) -> Iterator[Block]:
    """The direct child blocks of `nodes` whose header names `name` (case-insensitively)."""
    needle = name.lower()
    for node in nodes:
        if isinstance(node, Block) and node.name.lower() == needle:
            yield node


def _attr(block: Block, key: str) -> str | None:
    """The value `key` is assigned directly in `block` - the last one when it repeats, which is
    what the engine keeps - or None when it is never assigned."""
    needle = key.lower()
    value = None
    for node in block.children:
        if isinstance(node, Attribute) and node.key.lower() == needle:
            value = node.value
    return value


def _attr_values(block: Block, key: str) -> list[str]:
    """Every value `key` is assigned directly in `block`, in order. `BlingUpgrades` is written
    as one line per group, so its lists have to be read as a sequence rather than last-wins."""
    needle = key.lower()
    return [
        node.value
        for node in block.children
        if isinstance(node, Attribute) and node.key.lower() == needle
    ]


def _tokens(value: str | None) -> tuple[str, ...]:
    """The whitespace-separated names in an ini list value, with the `@` a sub-class marks its
    default choice with stripped off."""
    if not value:
        return ()
    return tuple(token.lstrip("@") for token in value.split() if token.strip("@"))


def _first(value: str | None) -> str:
    """The first whitespace-separated token of an ini value, or "" when it has none. The engine
    reads a scalar reference's leading token and ignores the rest, so this is what it sees."""
    return value.split()[0] if value and value.split() else ""


def _int(value: str | None) -> int | None:
    """`value` as an int, or None when it is absent or not a plain number (a macro, say)."""
    if value is None:
        return None
    try:
        return int(value.split()[0])
    except (IndexError, ValueError):
        return None


def _localize(strings: Mapping[str, str], label: str | None) -> str:
    """A string-table label resolved to its display text, or "" when it names no loaded string.
    Labels and the ini references naming them disagree on case, so `strings` is keyed folded."""
    if not label:
        return ""
    first = label.split()[0]
    return strings.get(first.lower(), "")


def _power_option(block: Block, strings: Mapping[str, str]) -> PowerOption | None:
    """One CommandButton block as a `PowerOption`, or None when it is not a CaH power."""
    upgrades = _tokens(_attr(block, _ALLOWABLE_UPGRADES))
    if not upgrades or block.label is None:
        return None
    prerequisite = _first(_attr(block, "CreateAHeroUIPrerequisiteButtonName"))
    return PowerOption(
        command_button=_first(block.label),
        label=_localize(strings, _attr(block, "TextLabel")),
        class_upgrades=upgrades,
        min_level=_int(_attr(block, "CreateAHeroUIMinimumLevel")),
        prerequisite=None if prerequisite.lower() in ("", "none") else prerequisite,
    )


def _sub_class(block: Block, strings: Mapping[str, str]) -> HeroSubClass:
    """One `SubClass` block: its name, its upgrade, and every bling upgrade it offers."""
    upgrades: list[str] = []
    for value in _attr_values(block, "BlingUpgrades"):
        upgrades.extend(_tokens(value))
    name_tag = _attr(block, "NameTag") or ""
    return HeroSubClass(
        name=_localize(strings, name_tag) or name_tag,
        upgrade=_first(_attr(block, "UpgradeName")),
        bling_upgrades=tuple(upgrades),
    )


def _hero_class(block: Block, strings: Mapping[str, str]) -> HeroClass:
    """One `CreateAHeroClass` block: its name, its class upgrade, and its sub-classes in order."""
    name_tag = _attr(block, "NameTag") or ""
    return HeroClass(
        name=_localize(strings, name_tag) or name_tag,
        upgrade=_first(_attr(block, "UpgradeName")),
        sub_classes=tuple(_sub_class(sub, strings) for sub in _blocks(block.children, "SubClass")),
    )


def _bling_groups(block: Block, strings: Mapping[str, str]) -> tuple[BlingGroup, ...]:
    """The bling groups of one `CreateAHeroSystem` block: a `CreateAHeroBlingBinder` names and
    types each group, and the `CreateAHeroBling` entries fill it in declaration order. A group
    whose entries exist without a binder still comes through, typed "" - the game data drives
    the editor, so an unbound group is shown rather than swallowed."""
    binders: dict[str, BlingGroup] = {}
    for binder in _blocks(block.children, "CreateAHeroBlingBinder"):
        group_name = _first(_attr(binder, "GroupName"))
        if not group_name:
            continue
        binders[group_name.lower()] = BlingGroup(
            group_name=group_name,
            label=_localize(strings, _attr(binder, "LabelTag")),
            kind=_first(_attr(binder, "BlingType")),
            ui_slot=_int(_attr(binder, "UISlot")),
        )

    options: dict[str, dict[str, BlingOption]] = {}
    for bling in _blocks(block.children, "CreateAHeroBling"):
        group_name = _first(_attr(bling, "GroupName"))
        upgrade = _first(_attr(bling, "BlingUpgradeName"))
        if not group_name or not upgrade:
            continue
        key = group_name.lower()
        if key not in binders:
            binders[key] = BlingGroup(group_name=group_name, label="", kind="", ui_slot=None)
        # Keyed by upgrade so a choice declared twice keeps one entry, while dict insertion
        # order preserves the order the game counts indices in.
        options.setdefault(key, {})[upgrade] = BlingOption(
            upgrade=upgrade, label=_localize(strings, _attr(bling, "NameTag"))
        )

    return tuple(
        replace(group, options=tuple(options.get(key, {}).values()))
        for key, group in binders.items()
    )


def _candidate_files(root: Path) -> list[Path]:
    """The ini/inc files under `root` that declare a CommandButton or the CreateAHeroSystem
    block, sorted so a scan of the same tree always reads them in the same order."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if _WANTED_BLOCKS.search(read_text(path)):
            found.append(path)
    return found


def _string_table(root: Path) -> dict[str, str]:
    """Every `.str` table under `root`, merged and keyed by case-folded label."""
    strings: dict[str, str] = {}
    for path in sorted(root.rglob("*.str")):
        if path.is_file():
            for label, value in parse_str(read_text(path)).items():
                strings[label.lower()] = value
    return strings


def scan_ini_root(root: str | Path, progress: Callable[[str], None] | None = None) -> CahGameData:
    """Read the Create-a-Hero data out of one already-merged game tree (a folder holding
    `data/ini`, or an ini root directly). `progress`, if given, gets status strings as work
    proceeds. A tree with no Create-a-Hero data yields empty tuples rather than raising - the
    editor then simply offers no completions."""
    root = Path(root)
    ini = ini_root(root)
    if progress is not None:
        progress("Loading string tables…")
    strings = _string_table(root)

    if progress is not None:
        progress("Finding Create-a-Hero data…")
    files = _candidate_files(ini)

    powers: dict[str, PowerOption] = {}
    classes: tuple[HeroClass, ...] = ()
    bling_groups: tuple[BlingGroup, ...] = ()
    for index, path in enumerate(files, start=1):
        if progress is not None:
            progress(f"Reading {path.name} ({index}/{len(files)})…")
        document = parse_file(path, resolve_includes=True, include_layers=(ini,)).document
        for block in _blocks(document.children, "CommandButton"):
            power = _power_option(block, strings)
            if power is not None:
                powers[power.command_button.lower()] = power
        # A tree holds one CreateAHeroSystem; should an overlay declare a second, the last read
        # replaces it wholesale rather than merging - the way the engine treats a re-definition.
        for block in _blocks(document.children, "CreateAHeroSystem"):
            classes = tuple(
                _hero_class(child, strings) for child in _blocks(block.children, "CreateAHeroClass")
            )
            bling_groups = _bling_groups(block, strings)

    return CahGameData(
        classes=classes,
        powers=tuple(sorted(powers.values(), key=lambda power: power.command_button.lower())),
        bling_groups=bling_groups,
    )


def load_cah_game_data(
    sources: Sequence[tuple[str, str]], progress: Callable[[str], None] | None = None
) -> CahGameData:
    """Scan an ordered list of `(kind, path)` data sources - `("folder", path)` or
    `("big", path)` - for their Create-a-Hero data. The sources are merged into one tree first
    (later ones overriding earlier, `.big` archives extracted), so a mod loaded on top of the
    base game is read the way the engine reads it; the temporary tree is removed afterwards.

    A `.big` source needs pyBIG (installed with the `cah-ui` extra); plain folders do not."""
    workdir = Path(tempfile.mkdtemp(prefix="sage_cah_sources_"))
    try:
        merged = build_merged(list(sources), workdir, progress=progress, suffixes=LOAD_SUFFIXES)
        return scan_ini_root(merged, progress=progress)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
