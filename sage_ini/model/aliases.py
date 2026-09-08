"""Descriptive aliases on upgrade references: `Upgrade_TestBuilding@SmithyLevel2`.

Object upgrades are a scarce global bit space (`sage_patch/docs/upgrade-mask-limit.md`), so a
handful of generic upgrades get reused as object-local flags for unrelated purposes and their
names say nothing about what any single use means. An alias suffixes the *reference* with the
intent it carries there, leaving the name the engine resolves untouched.

The separator is `@`, and it only separates *inside* a token. A leading `@` is already taken:
the create-a-hero `BlingUpgrades` lists mark their default option with one (`BlingUpgrades =
@Upgrade_NoHelmet Upgrade_..._CHH01 ...`), so `@Name` is that marker and not an alias with an
empty name. Requiring a name before the separator keeps the two apart with no ambiguity, and it
is the only other use of the character in the data - every remaining `@` in the base game sits
inside a comment, where no parser sees it. `@` is not one of the lexer's comment markers (`;`,
`//`, `--`), so an interior one reaches the value intact.

Truncation at an interior `@` is what the engine does once the upgrade-alias hook over
`UpgradeCenter::findUpgrade` is applied, and what a build for a stock binary strips out of the
shipped text. Either way the alias never reaches a name lookup, so this module is the one
definition of where a reference name ends and its annotation begins. The leading-`@` carve-out
is load-bearing for the hook too: truncating a bare `@Upgrade_NoHelmet` at position zero would
resolve the empty string and break every create-a-hero default.

Only the tables in `ALIASED_TABLES` split, mirroring the hook: it sits on the upgrade lookup
alone, so an `@` in an object or weapon name is an ordinary character in an ordinary name and
stays part of it.
"""

import re

__all__ = [
    "ALIASED_TABLES",
    "ALIAS_SEPARATOR",
    "is_well_formed",
    "resolve_alias",
    "split_alias",
    "strip_alias",
]

ALIAS_SEPARATOR = "@"

# The reference tables an alias may annotate - the tables whose lookup the engine hook truncates.
ALIASED_TABLES = frozenset({"upgrades"})

# An alias names an intent, so it is spelled like an identifier. Anything else is a typo or a
# stray separator rather than an annotation, and the lint rules say so.
_WELL_FORMED = re.compile(r"[A-Za-z0-9_]+\Z")


def split_alias(key: str | None, value):
    """`(name, alias)` for one raw reference token in table `key`.

    `alias` is None when the token carries no separator, and the (possibly empty) remainder
    after the first interior `@` when it does - empty and malformed aliases survive the split so
    a rule can report them rather than being silently swallowed here. A non-string value, a
    table that does not take aliases, a class with no table of its own (`key` is None) and a
    token whose `@` is leading (the create-a-hero default-bling marker) all pass through
    untouched."""
    if key not in ALIASED_TABLES or not isinstance(value, str):
        return value, None
    name, separator, alias = value.partition(ALIAS_SEPARATOR)
    return (name, alias) if separator and name else (value, None)


def strip_alias(key: str | None, value):
    """`value` with any alias removed - the name the engine actually looks up."""
    return split_alias(key, value)[0]


def resolve_alias(game, key: str, value):
    """`(name, alias)` for a raw reference value, macros expanded.

    An alias can be written on the reference (`MACRO@Alias`) or come out of the `#define` body
    (`MACRO` expanding to `Upgrade_X@Alias`), and neither spelling is wrong, so the split runs on
    both sides of the expansion. A separator written at the reference wins: it is the more local
    statement of intent."""
    name, alias = split_alias(key, value)
    name, expanded_alias = split_alias(key, game.get_macro(name))
    return name, alias if alias is not None else expanded_alias


def is_well_formed(alias: str) -> bool:
    """Whether `alias` is spelled like the identifier an intent name should be."""
    return bool(_WELL_FORMED.match(alias))
