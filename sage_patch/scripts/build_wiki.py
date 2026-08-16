"""Render the engine module reference as a browsable static HTML site.

Reads what `module_defaults.py` recovered from `game.dat` - modules, fields, types,
defaults, enum name arrays and sub-block schemas - and writes a page per module plus
the type, enum and coverage pages that give a field's type a meaning. `sage_ini`
supplies the second opinion: its enums are matched against the engine's own name
arrays so each list can say whether the two sources agree.

The site is self-contained and opens from the filesystem: no server, no CDN, and the
search index ships as a script rather than as data fetched at runtime. It is a build
artefact, not part of the repository: it lands in `build/wiki/` and is regenerated from
the JSON in `sage_patch/docs/`.

Usage:
    python build_wiki.py [--out build/wiki]
"""
from __future__ import annotations

import argparse
import html
import inspect
import json
import os
import shutil
from typing import Any, Optional

import sage_ini.model.enums as sage_enums
import sage_ini.model.types as sage_types
from sage_ini.model.objects import REGISTRY as SAGE_REGISTRY
from sage_utils import webtheme

__all__ = ["build", "TYPE_DOCS", "CATEGORIES"]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
DOCS = os.path.join(HERE, os.pardir, "docs")
MODULE_JSON = os.path.join(DOCS, "module-reference.json")
TYPE_JSON = os.path.join(DOCS, "ini-types.json")
DEFAULT_OUT = os.path.join(REPO, "build", "wiki")

ENGINE_BUILD = "2.01.2614.37001"

# Modules are grouped by the interface their name ends in, which is also the INI
# keyword that takes them: `Behavior = ...`, `Draw = ...`, `Body = ...`.
CATEGORIES = [
    ("Update", "Update", "Per-frame logic: production, movement, abilities, spawning."),
    ("Behavior", "Behavior", "Behaviours attached with `Behavior =`, the largest catch-all group."),
    ("SpecialPower", "Special power", "The modules behind a `SpecialPower` template."),
    ("Upgrade", "Upgrade", "Modules that fire when an upgrade is granted."),
    ("Draw", "Draw", "Draw modules: what the object looks like and how it animates."),
    ("Contain", "Contain", "Containers: garrisons, transports, hordes."),
    ("Die", "Die", "What happens when the object dies."),
    ("Body", "Body", "Health, armour and damage state."),
    ("Collide", "Collide", "Reactions to bumping into another object."),
    ("Create", "Create", "One-shot logic at creation time."),
    ("", "Other", "Modules whose name does not end in an interface suffix."),
]

# What a type means to someone writing INI: what you write, and what the engine
# stores once it has parsed it. Engine-side facts (scaling, range checks, the name
# array a token is resolved against) come from the parse function itself.
TYPE_DOCS: dict[str, tuple[str, str, str]] = {
    "Bool": ("Scalar", "`Yes` or `No`",
             "A single byte. Anything the parser does not recognise is a parse error, "
             "not a silent `No`."),
    "Int": ("Scalar", "a whole number",
            "Signed 32-bit. The parser accepts the INI math operators and macros, so "
            "`#ADD(2 3)` is as valid as `5`."),
    "Int8": ("Scalar", "a whole number, -128 to 127",
             "Stored in one byte. A value outside the range is rejected and the field "
             "keeps its default."),
    "UInt8": ("Scalar", "a whole number, 0 to 255",
              "Stored in one byte. A value outside the range is rejected and the field "
              "keeps its default."),
    "UInt16": ("Scalar", "a whole number, 0 to 65535",
               "Stored in two bytes. A value outside the range is rejected and the "
               "field keeps its default."),
    "Real": ("Scalar", "a decimal number",
             "A 32-bit float, stored exactly as written."),
    "PositiveReal": ("Scalar", "a decimal number greater than zero",
                     "The parser range-checks it and logs `invalid Real value ... "
                     "expected > 0` for anything else."),
    "NonNegativeReal": ("Scalar", "a decimal number, zero or greater",
                        "The parser range-checks it and logs `invalid Real value ... "
                        "expected >= 0` for anything else."),
    "NonPositiveReal": ("Scalar", "a decimal number, zero or less",
                        "The parser range-checks it and logs `invalid Real value ... "
                        "expected <= 0` for anything else."),
    "Percent": ("Scalar", "a percentage, `50` meaning half",
                "Divided by 100 on the way in, so the stored value is a fraction. "
                "A default shown as `0.5` is `50%` in INI."),
    "AngleReal": ("Scalar", "an angle in degrees",
                  "Multiplied by pi/180, so the engine stores radians. A default of "
                  "`1.5708` is a right angle."),
    "Duration": ("Scalar", "a duration in milliseconds",
                 "Converted to whole logic frames and stored as an integer, so sub-frame "
                 "precision is lost. Defaults are shown in frames."),
    "DurationReal": ("Scalar", "a duration in milliseconds",
                     "Converted to logic frames and kept fractional. Defaults are shown "
                     "in frames."),
    "VelocityReal": ("Scalar", "a speed in world units per second",
                     "Converted to units per logic frame, so the stored default is the "
                     "per-frame figure."),
    "AngularVelocityReal": ("Scalar", "a turn rate in degrees per second",
                            "Converted to radians per logic frame."),
    "IntRange": ("Scalar", "two whole numbers, low then high", "Stored as a pair."),
    "Coord3D": ("Scalar", "`X:<real> Y:<real> Z:<real>`",
                "Three floats. Omitted components stay zero."),
    "RGBColor": ("Scalar", "`R:<0-255> G:<0-255> B:<0-255>`",
                 "Each channel is divided by 255 and stored as a float."),
    "RGBAColor": ("Scalar", "`R:<0-255> G:<0-255> B:<0-255> A:<0-255>`",
                  "Each channel is divided by 255 and stored as a float."),
    "AsciiString": ("Text", "one token, or a quoted string",
                    "Stored verbatim. What the name has to match depends on the field - "
                    "a bone, a subobject, an object name."),
    "AsciiStringList": ("Text", "any number of tokens on the line",
                        "Stored as a list of strings."),
    "Enum": ("Enumeration", "one token from a fixed list",
             "The token's position in the list is what gets stored. The list lives in "
             "the field's own parse table, so each field names its own."),
    "LookupList": ("Enumeration", "one token from a fixed list",
                   "Like `Enum`, but each name carries an explicit value rather than "
                   "its position."),
    "BitFlags": ("Flag set", "any number of tokens on one line",
                 "Each token turns on one bit. The list lives in the field's own parse "
                 "table, so each field names its own."),
    "KindOfFlags": ("Flag set", "any number of `KindOf` tokens",
                    "Turns on one bit each in the object's KindOf mask."),
    "KindOfFilter": ("Flag set", "`KindOf` tokens, `+` to require and `-` to exclude",
                     "A test against another object's KindOf mask rather than a value of "
                     "its own."),
    "ObjectStatusFlags": ("Flag set", "any number of `ObjectStatus` tokens",
                          "Runtime status bits, the same set the engine sets and clears "
                          "as an object plays."),
    "ModelConditionFlags": ("Flag set", "any number of `ModelCondition` tokens",
                            "The condition set a draw module matches its art against."),
    "ModelConditionFlag": ("Enumeration", "one `ModelCondition` token",
                           "A single condition, not a set."),
    "WeaponSetFlags": ("Flag set", "any number of weapon-set tokens",
                       "Selects which `WeaponSet` block applies."),
    "DamageTypeFlags": ("Flag set", "`DamageType` tokens, or `ALL` / `NONE`",
                        "`ALL` and `NONE` set and clear every bit."),
    "DeathTypeFlags": ("Flag set", "`DeathType` tokens, or `ALL` / `NONE`",
                       "`ALL` and `NONE` set and clear every bit."),
    "SpecialPowerFlags": ("Flag set", "any number of trigger tokens",
                          "How a special power may be aimed and what it needs first."),
    "SpecialPowerAIType": ("Enumeration", "one `AI_SPECIAL_POWER_*` token",
                           "Tells the AI how to use the power."),
    "EmotionType": ("Enumeration", "one emotion token",
                    "One of the engine's fixed emotion reactions."),
    "WeatherType": ("Enumeration", "one weather token", "Global weather state."),
    "UpgradeMask": ("Reference", "any number of `Upgrade` names",
                    "Stored as a bit per upgrade in a fixed-width mask, which is why "
                    "the number of upgrades a build supports is capped."),
    "WeaponTemplate": ("Reference", "a `Weapon` name",
                       "Resolved against Weapon.ini when the object is loaded."),
    "UpgradeTemplate": ("Reference", "an `Upgrade` name", "Resolved against Upgrade.ini."),
    "SpecialPowerTemplate": ("Reference", "a `SpecialPower` name",
                             "Resolved against SpecialPower.ini."),
    "ScienceType": ("Reference", "a `Science` name", "Resolved against Science.ini."),
    "ObjectCreationList": ("Reference", "an `ObjectCreationList` name",
                           "`None` clears the field."),
    "ParticleSystem": ("Reference", "an `FXParticleSystem` name",
                       "`None` clears the field."),
    "FXList": ("Reference", "an `FXList` name",
               "`None` clears the field. An unknown name is reported with its line "
               "number at load time."),
    "AudioEventRTS": ("Reference", "a sound or voice event name",
                      "Resolved against the audio INI. `NoSound` clears it."),
    "EvaEvent": ("Reference", "an EVA event name", "Resolved against Eva.ini."),
    "MomentFXList": ("Reference", "a moment token, then an `FXList` name",
                     "One line per moment, so a module can play something different at "
                     "each stage. Which moments are on offer depends on the module."),
    "MomentOCL": ("Reference", "a moment token, then an `ObjectCreationList` name",
                  "One line per moment. Which moments are on offer depends on the "
                  "module."),
    "MomentSound": ("Reference", "a moment token, then a sound name",
                    "One line per moment."),
    "MomentWeapon": ("Reference", "a moment token, then a `Weapon` name",
                     "One line per moment."),
    "AngleFXList": ("Reference", "an angle in degrees, then an `FXList` name",
                    "Picks the effect by the angle of impact."),
    "DisabledTypeFlags": ("Flag set", "any number of disabled-state tokens",
                          "The states an object can be disabled in - held, paralysed, "
                          "unmanned and the rest."),
    "ModelConditionFlagRange": ("Flag set", "exactly two `ModelCondition` tokens",
                                "The pair names the ends of a range; the engine "
                                "complains if you give it anything but two."),
    "MeleeBehavior": ("Enumeration", "one melee-behaviour token",
                      "How a horde's members close on their target."),
    "Module": ("Reference", "a module name, then a tag of your own",
               "Attaches a module and opens its block. The tag only has to be unique "
               "within the object, and is what an override or a `RemoveModule` refers "
               "to later."),
    "GeometryType": ("Enumeration", "one geometry token",
                     "The primitive the object's collision shape is built from."),
}

CATEGORY_ORDER = ["Scalar", "Text", "Enumeration", "Flag set", "Reference",
                  "Sub-block", "Unidentified"]

# How a typed-in value is checked. Types not listed here take their kind from their
# category, so every enum checks its tokens and every reference checks nothing.
VALUE_KINDS = {
    "Bool": "bool",
    "Int": "int",
    "Int8": "int8",
    "UInt8": "uint8",
    "UInt16": "uint16",
    "Real": "real",
    "Percent": "real",
    "Duration": "real",
    "DurationReal": "real",
    "AngleReal": "real",
    "VelocityReal": "real",
    "AngularVelocityReal": "real",
    "PositiveReal": "positive",
    "NonNegativeReal": "nonneg",
    "NonPositiveReal": "nonpos",
    "IntRange": "intrange",
    "Coord3D": "coord3",
    "RGBColor": "rgb",
    "RGBAColor": "rgba",
    "ModelConditionFlagRange": "pair",
    "AngleFXList": "text",
    "Module": "module",
}

# Token lists the binary does not name and `sage_ini` does not model, named here after
# what the module that reads them calls them.
ENUM_NAMES = {
    "0x00db0e7c": "StructureCollapsePhase",
    "0x00db0ed0": "RubbleRisePhase",
    "0x00db0f20": "StructureTopplePhase",
    "0x00d9e6bc": "LodLevel",
}



def annotation_target(annotation: Any, depth: int = 0) -> Optional[str]:
    """The table a `sage_ini` annotation points at, through whatever wraps it.

    The model says what the engine's parse function cannot: that this string names an
    upgrade, or that one names an object. It says it in several shapes - a `Reference`
    marker, the model class itself, or either of those inside a list, a nullable or a
    union - and all of them lead back to one table key.
    """
    if annotation is None or depth > 5:
        return None
    for meta in getattr(annotation, "__metadata__", ()):
        if isinstance(meta, sage_types.Reference):
            return meta.key
    key = getattr(annotation, "key", None)
    if isinstance(key, str):
        return key
    for attr in ("element", "inner"):
        found = annotation_target(getattr(annotation, attr, None), depth + 1)
        if found:
            return found
    for attr in ("types", "element_types", "values"):
        options = getattr(annotation, attr, None)
        if not isinstance(options, (list, tuple)):
            continue      # a class's own `values` is a method, not a set of alternatives
        for option in options:
            found = annotation_target(option, depth + 1)
            if found:
                return found
    return None


def sage_annotations(name: str) -> dict[str, Any]:
    """Every field `sage_ini` models for a block or module, base classes included."""
    cls = SAGE_REGISTRY.get(name)
    if cls is None:
        return {}
    merged: dict[str, Any] = {}
    for base in reversed(getattr(cls, "__mro__", ())):
        merged.update(getattr(base, "__annotations__", {}))
    return merged


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def prose(text: str) -> str:
    """Escape a written description, turning its `backticks` into code spans."""
    parts = esc(text).split("`")
    return "".join(p if i % 2 == 0 else f"<code>{p}</code>" for i, p in enumerate(parts))


def slug(name: str) -> str:
    """A filename-safe, case-insensitive-unique key for a module name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)


class Reference:
    """The extracted data, with everything the pages ask of it worked out once."""

    def __init__(self, modules: list[dict], types: dict) -> None:
        self.modules = [m for m in modules if m.get("name")]
        self.name_tables: dict[str, list[str]] = types["name_tables"]
        self.lookup_tables: dict[str, list] = types["lookup_tables"]
        self.blocks: dict[str, dict] = types["blocks"]
        self.ini_blocks: dict[str, dict] = types.get("ini_blocks", {})
        self.type_tables: dict[str, str] = types["types"]
        self.engine_enums: dict[str, str] = types["enums"]
        self.sage_enums = self._sage_enums()
        self.enums = self._name_enums()
        self.field_types = self._field_types()
        self.targets = self._sage_targets()

    @staticmethod
    def _sage_enums() -> dict[str, tuple[list[str], Optional[str]]]:
        """`sage_ini`'s enums: members and docstring, for cross-checking the engine's.

        Only a docstring written on the class itself counts - inherited ones describe
        `Enum`, not the list.
        """
        out = {}
        for name, cls in vars(sage_enums).items():
            if (isinstance(cls, type) and issubclass(cls, sage_enums.BFMEEnum)
                    and cls.__members__ and not name.startswith("_")
                    and name not in ("BFMEEnum", "CaseInsensitiveEnum", "FakeEnum")):
                doc = cls.__dict__.get("__doc__")
                out[name] = (list(cls.__members__), inspect.cleandoc(doc) if doc else None)
        return out

    def _match_sage_enum(self, members: list[str]) -> Optional[str]:
        """The `sage_ini` enum that models the same list, by how far the two overlap.

        Overlap rather than position: the two agree on what the list holds far more
        often than on the order, and where they disagree on order the engine's is the
        one that counts.
        """
        mine = {m.upper() for m in members}
        best, score = None, 0.0
        for name, (theirs, _doc) in self.sage_enums.items():
            if len(theirs) < 2:
                continue
            other = {t.upper() for t in theirs}
            ratio = len(mine & other) / len(mine | other)
            if ratio > score:
                best, score = name, ratio
        return best if score >= 0.7 else None

    def _name_enums(self) -> dict[str, dict]:
        """Every name array, keyed by the name this site gives it.

        The engine's own flag types name themselves. A list that a field's parse table
        points at has no name in the binary, so it takes the matching `sage_ini` enum's
        name, or failing that the field that uses it. The same list is often compiled
        into several arrays; those are one enum here, listed under every address it
        was found at.
        """
        by_table: dict[str, str] = {va: name for name, va in self.engine_enums.items()}
        users: dict[str, list[tuple[str, str, str]]] = {}
        from_type: dict[str, str] = {}
        owned = ([("m", m["name"], m["fields"]) for m in self.modules]
                 + [("b", n, blk["fields"]) for n, blk in self.ini_blocks.items()])
        for page_dir, owner, fields in owned:
            for f in fields:
                if f.get("userdata"):
                    users.setdefault(f["userdata"], []).append((page_dir, owner, f["name"]))
                    kind = TYPE_DOCS.get(f["type"], ("", "", ""))[0]
                    if f["type"].endswith("Flags") and f["type"] != "BitFlags":
                        from_type.setdefault(f["userdata"], f["type"][:-len("Flags")])
                    elif kind == "Enumeration" and f["type"] not in ("Enum", "LookupList"):
                        from_type.setdefault(f["userdata"], f["type"])
        enums: dict[str, dict] = {}
        by_members: dict[tuple[str, ...], str] = {}
        for va, members in sorted(self.name_tables.items(),
                                  key=lambda kv: (kv[0] not in by_table, kv[0])):
            key = tuple(members)
            if key in by_members:
                enum = enums[by_members[key]]
                enum["tables"].append(va)
                enum["users"] = sorted(set(enum["users"]) | set(users.get(va, [])))
                continue
            name = by_table.get(va)
            matched = self._match_sage_enum(members)
            if not name:
                name = (matched or ENUM_NAMES.get(va) or from_type.get(va)
                        or users.get(va, [("", "", "Unnamed")])[0][2] + "Values")
            while name in enums:
                name += "'"
            doc = self.sage_enums.get(matched or name, ([], None))[1]
            by_members[key] = name
            enums[name] = {
                "members": members,
                "table": va,
                "tables": [va],
                "kind": "index",
                "sage_ini": matched,
                "doc": doc,
                "users": sorted(users.get(va, [])),
                "engine_named": va in by_table,
            }
        for va, pairs in sorted(self.lookup_tables.items()):
            members = [p[0] for p in pairs]
            matched = self._match_sage_enum(members)
            name = matched or (users.get(va, [("", "", "Unnamed")])[0][2] + "Values")
            enums[name] = {
                "members": members,
                "values": [p[1] for p in pairs],
                "table": va,
                "tables": [va],
                "kind": "lookup",
                "sage_ini": matched,
                "doc": self.sage_enums.get(matched or name, ([], None))[1],
                "users": sorted(users.get(va, [])),
                "engine_named": False,
            }
        return enums

    def enum_for_type(self, type_name: str) -> Optional[str]:
        """The enum page a type's tokens come from, if the type owns a fixed list."""
        va = self.type_tables.get(type_name)
        if not va:
            return None
        for name, enum in self.enums.items():
            if enum["table"] == va and enum["engine_named"]:
                return name
        return None

    def enum_for_field(self, field: dict) -> Optional[str]:
        """The enum page a field's own token list lives on."""
        va = field.get("userdata")
        if not va:
            return self.enum_for_type(field["type"])
        for name, enum in self.enums.items():
            if va in enum["tables"]:
                return name
        return None

    def _field_types(self) -> dict[str, list[tuple[str, str, str]]]:
        """type name -> the (page, owner, field) triples that use it."""
        out: dict[str, list[tuple[str, str, str]]] = {}
        for m in self.modules:
            for f in m["fields"]:
                out.setdefault(f["type"], []).append(("m", m["name"], f["name"]))
        for name, blk in self.ini_blocks.items():
            for f in blk["fields"]:
                out.setdefault(f["type"], []).append(("b", name, f["name"]))
        return out


    def _sage_targets(self) -> dict[str, dict[str, tuple[str, bool]]]:
        """owner -> field -> (the block its value names, whether that block has a page).

        Straight from `sage_ini`'s model rather than from the binary: the engine parses
        these fields as plain strings and never says what the string has to match.
        """
        by_key: dict[str, list[str]] = {}
        for keyword, cls in SAGE_REGISTRY.items():
            key = getattr(cls, "key", None)
            if isinstance(key, str) and not keyword.startswith("_"):
                by_key.setdefault(key, []).append(keyword)
        named: dict[str, str] = {}
        for key, keywords in by_key.items():
            here = [k for k in keywords if k in self.ini_blocks]
            named[key] = min(here or keywords, key=lambda k: (len(k), k))

        out: dict[str, dict[str, tuple[str, bool]]] = {}
        owners = [m["name"] for m in self.modules] + list(self.ini_blocks)
        for owner in owners:
            for field, annotation in sage_annotations(owner).items():
                key = annotation_target(annotation)
                block = named.get(key or "")
                if block:
                    out.setdefault(owner, {})[field] = (block, block in self.ini_blocks)
        return out

    def target_of(self, owner: str, field: dict) -> Optional[tuple[str, bool]]:
        """What a field's value names, where the engine's own type does not say."""
        if self.type_category(field["type"]) not in ("Text", "Unidentified"):
            return None
        return self.targets.get(owner, {}).get(field["name"])

    def category(self, module: str) -> str:
        for suffix, label, _blurb in CATEGORIES:
            if suffix and module.endswith(suffix):
                return label
        return "Other"

    def type_category(self, type_name: str) -> str:
        if type_name in TYPE_DOCS:
            return TYPE_DOCS[type_name][0]
        if type_name in self.blocks:
            return "Sub-block"
        return "Unidentified"


def page(ref: Reference, title: str, body: str, base: str = "",
         subtitle: str = "", active: str = "", extra: str = "") -> str:
    """The shell every page shares: head, sidebar mount point, content."""
    return f"""<!DOCTYPE html>
<html lang="en" data-base="{base}" data-active="{esc(active)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - SAGE module reference</title>
<link rel="stylesheet" href="{base}assets/wiki.css">
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<button id="menu" aria-label="Toggle navigation">Menu</button>
<nav id="sidebar" aria-label="Site">
  <a class="brand" href="{base}index.html">SAGE<span>module reference</span></a>
  <div class="searchbox">
    <input id="q" type="search" placeholder="Search modules, fields, types" autocomplete="off"
           aria-label="Search" spellcheck="false">
    <kbd>/</kbd>
  </div>
  <div id="results" hidden></div>
  <div id="nav"></div>
</nav>
<main id="content">
<header class="pagehead">
  <h1>{esc(title)}</h1>
  {f'<p class="sub">{subtitle}</p>' if subtitle else ''}
</header>
{body}
<footer>
  Generated from <code>game.dat</code> build {ENGINE_BUILD} by
  <code>sage_patch/scripts/build_wiki.py</code>. Field names, offsets, types and
  defaults are read out of the binary, not transcribed from another reference.
</footer>
</main>
<script src="{base}assets/data.js"></script>
{f'<script src="{base}assets/{extra}"></script>' if extra else ''}
<script src="{base}assets/wiki.js"></script>
</body>
</html>
"""


def type_tip(ref: Reference, type_name: str) -> str:
    """The one-line explanation that hangs off a type wherever it is mentioned."""
    if type_name.startswith("0x"):
        return ("Parse function not identified, so neither the syntax nor the stored "
                "form is known.")
    if type_name in TYPE_DOCS:
        _cat, writes, detail = TYPE_DOCS[type_name]
        return f"You write {writes.replace('`', '')}. {detail}".replace("`", "")
    block = ref.blocks.get(type_name)
    if block:
        words = block["keywords"]
        listed = ", ".join(words[:8]) + (", ..." if len(words) > 8 else "")
        return ("A nested block ended by End."
                + (f" Keywords: {listed}." if words else ""))
    return type_name


def type_link(ref: Reference, type_name: str, base: str) -> str:
    """A type cell: the type, linked to whatever page explains it, tip in tow."""
    tip = esc(type_tip(ref, type_name))
    if type_name.startswith("0x"):
        return (f'<a class="t t-unknown" href="{base}types.html#unidentified" '
                f'data-tip="{tip}" aria-label="{tip}">{esc(type_name)}</a>')
    cat = ref.type_category(type_name)
    cls = "t-" + cat.split()[0].lower()
    return (f'<a class="t {cls}" href="{base}types.html#{esc(slug(type_name))}" '
            f'data-tip="{tip}" aria-label="{tip}">{esc(type_name)}</a>')


def field_kind(ref: Reference, type_name: str) -> str:
    """The shape a value has to have, which is all the page checks a typed value against.

    Coarser than the type: every duration, angle and speed is a number to the field that
    takes it, and the checks worth making from a browser are the ones the engine's own
    parser makes - is it a number, is it in range, is that token a member of the list.
    """
    if type_name in VALUE_KINDS:
        return VALUE_KINDS[type_name]
    if type_name.startswith("Moment"):
        return "keyed"
    cat = ref.type_category(type_name)
    if cat == "Enumeration":
        return "enum"
    if cat == "Flag set":
        return "flags"
    if cat == "Sub-block":
        return "block"
    return "text"


def value_control(ref: Reference, field: dict, enum: Optional[str], kind: str,
                  default: str) -> str:
    """The control the value column offers for a field.

    A type with a short, closed answer gets picked rather than typed: a bool is one of
    two words, and a KindOf set is any number of names from a list the engine fixes.
    The KindOf options are filled in from the shipped member list rather than written
    into every page, since there are 222 of them.
    """
    common = (f' data-field="{esc(field["name"])}" data-kind="{kind}"'
              f' data-default="{esc(default)}"'
              + (f' data-enum="{esc(enum)}"' if enum else ""))
    label = f' aria-label="Value for {esc(field["name"])}"'
    if kind == "bool":
        shown = default or "unset"
        return (f'<select class="fieldval"{label}{common}>'
                f'<option value="">default: {esc(shown)}</option>'
                f'<option>Yes</option><option>No</option></select>')
    if field["type"] in ("KindOfFlags", "KindOfFilter"):
        # a filter tests a mask rather than setting one, so its tokens carry a sign
        sign = "+" if field["type"] == "KindOfFilter" else ""
        return (f'<select class="fieldval" multiple size="4"{label}{common}'
                f' data-members="KindOf" data-sign="{sign}"></select>')
    return (f'<input class="fieldval" type="text" spellcheck="false"{label}'
            f' placeholder="{esc(default)}"{common}>')


def target_link(ref: Reference, owner: str, field: dict, base: str) -> str:
    """What the value names, where the engine's type only says "string"."""
    found = ref.target_of(owner, field)
    if not found:
        return ""
    block, has_page = found
    tip = esc(f"sage_ini models this as naming a {block}; the engine parses it as a "
              f"plain string and does not say what it has to match")
    if has_page:
        return (f' <a class="reflink" href="{base}b/{esc(slug(block))}.html" '
                f'data-tip="{tip}">&rarr; {esc(block)}</a>')
    return f' <span class="reflink" data-tip="{tip}">&rarr; {esc(block)}</span>'


def field_rows(ref: Reference, owner: str, fields: list[dict], base: str) -> str:
    rows = []
    for f in fields:
        enum = ref.enum_for_field(f)
        extra = ""
        if enum:
            extra = (f' <a class="enumref" href="{base}enums.html#{esc(slug(enum))}">'
                     f'{esc(enum)}</a>')
        extra += target_link(ref, owner, f, base)
        default = (f'<code>{esc(f["default"])}</code>' if f["default"] is not None
                   else '<span class="none" title="not recoverable by constant tracking; '
                        'in practice an empty container or string">-</span>')
        kind = field_kind(ref, f["type"])
        control = value_control(ref, f, enum, kind, f["default"] or "")
        rows.append(
            f'<tr id="{esc(slug(f["name"]))}">'
            f'<td class="fname"><code>{esc(f["name"])}</code></td>'
            f'<td>{type_link(ref, f["type"], base)}{extra}</td>'
            f'<td class="num">{default}</td>'
            f'<td class="val">{control}<span class="why"></span></td></tr>')
    return "\n".join(rows)


def ini_skeleton(header: str, fields: list[dict]) -> str:
    """The block with every keyword at the value it holds when left out.

    A keyword whose default could not be recovered is left out rather than written
    blank, since a blank line is not something you could paste.
    """
    written = [f for f in fields if f["default"] is not None]
    width = max((len(f["name"]) for f in written), default=0)
    lines = [header]
    lines += [f'  {f["name"]:<{width}} = {f["default"]}' for f in written]
    lines.append("End")
    return esc("\n".join(lines))


def schema_page(ref: Reference, name: str, fields: list[dict], header: str,
                lead: str, base: str, facts: str = "") -> str:
    """The page shared by a module and an INI block: its fields, and a block to paste."""
    unknown = [f for f in fields if f["type"].startswith("0x")]
    warn = ""
    if unknown:
        names = ", ".join(f'<code>{esc(f["name"])}</code>' for f in unknown)
        verb = "uses" if len(unknown) == 1 else "use"
        warn = (f'<p class="note">{len(unknown)} field'
                f'{"" if len(unknown) == 1 else "s"} here {verb} a parse function that '
                f'has not been identified, so the type column shows its address: '
                f'{names}.</p>')
    body = f"""
{facts}
{warn}
<table class="fields sortable" data-module="{esc(header)}">
<thead><tr><th>Field</th><th>Type</th><th>Default</th><th>Value</th></tr></thead>
<tbody>
{field_rows(ref, name, fields, base)}
</tbody>
</table>
<div class="inirow">
<details class="skeleton">
<summary>INI block, every keyword at its default</summary>
<p class="note">The engine writes these values before it reads the block, so a keyword
you leave out behaves exactly as if you had written the line below. Fill in the value
column above and the line follows. Keywords whose default could not be recovered are
left out until you give them a value. {lead}</p>
<pre><code id="ini">{ini_skeleton(header, fields)}</code></pre>
</details>
<button class="copyini" type="button">Copy INI</button>
</div>
"""
    return page(ref, name, body, base=base, active=name)


def module_page(ref: Reference, module: dict) -> str:
    mask = module.get("interface_mask") or ""
    facts = ""
    if mask.startswith("0x") or mask.isdigit():
        facts = (f'<dl class="facts"><div><dt>Interface mask</dt>'
                 f'<dd><code>{esc(mask)}</code></dd></div></dl>')
    lead = ("The leading keyword (<code>Behavior</code>, <code>Draw</code>, "
            "<code>Body</code>, ...) depends on which interface you are attaching.")
    return schema_page(ref, module["name"], module["fields"],
                       f'{module["name"]} ModuleTag_01', lead, "../", facts)


def block_page(ref: Reference, name: str, block: dict) -> str:
    shared = sorted(n for n, other in ref.ini_blocks.items()
                    if other["parse_fn"] == block["parse_fn"] and n != name)
    facts = ""
    if shared:
        links = ", ".join(f'<a href="{esc(slug(n))}.html"><code>{esc(n)}</code></a>'
                          for n in shared)
        facts = (f'<p class="note">The same schema is read for {links}.</p>')
    lead = ("A named block takes its name after the keyword "
            f"(<code>{esc(name)} SomeName</code>); the settings blocks that exist once "
            "take none.")
    return schema_page(ref, name, block["fields"], name, lead, "../", facts)


def modules_page(ref: Reference) -> str:
    parts = []
    for _suffix, label, blurb in CATEGORIES:
        group = [m for m in ref.modules if ref.category(m["name"]) == label]
        if not group:
            continue
        items = "\n".join(
            f'<li><a href="m/{esc(slug(m["name"]))}.html">{esc(m["name"])}</a>'
            f'<span class="count">{len(m["fields"])}</span></li>' for m in group)
        parts.append(f'<section id="{esc(slug(label))}"><h2>{esc(label)} '
                     f'<span class="count">{len(group)}</span></h2>'
                     f'<p class="note">{blurb}</p><ul class="modgrid">{items}</ul></section>')
    return page(ref, "All modules", "\n".join(parts),
                subtitle=f"{len(ref.modules)} modules registered by the engine, "
                         f"grouped by the interface they attach to", active="modules")


def blocks_page(ref: Reference) -> str:
    items = "\n".join(
        f'<li><a href="b/{esc(slug(name))}.html">{esc(name)}</a>'
        f'<span class="count">{len(blk["fields"])}</span></li>'
        for name, blk in sorted(ref.ini_blocks.items(), key=lambda kv: kv[0].lower()))
    fields = sum(len(b["fields"]) for b in ref.ini_blocks.values())
    body = f"""<p class="lead">The block types the INI loader dispatches on, each read
through a field table of its own - the same machinery a module's data goes through.
`Object`, `Weapon`, `Locomotor`, `GameData` and the rest live here, alongside the
nested blocks that only appear inside another.</p>
<ul class="modgrid">{items}</ul>"""
    return page(ref, "All blocks", body.replace("`", ""),
                subtitle=f"{len(ref.ini_blocks)} block types, {fields} fields",
                active="blocks")


def types_page(ref: Reference) -> str:
    sections = []
    for cat in CATEGORY_ORDER:
        entries = []
        if cat == "Sub-block":
            names = sorted(ref.blocks)
        elif cat == "Unidentified":
            names = sorted({t for t in ref.field_types if t.startswith("0x")})
        else:
            names = sorted(n for n, d in TYPE_DOCS.items() if d[0] == cat)
        for name in names:
            users = ref.field_types.get(name, [])
            examples = ", ".join(
                f'<a href="{d}/{esc(slug(owner))}.html#{esc(slug(fld))}">'
                f'<code>{esc(owner)}.{esc(fld)}</code></a>' for d, owner, fld in users[:3])
            more = f" and {len(users) - 3} more" if len(users) > 3 else ""
            table = ""
            if cat == "Sub-block":
                block = ref.blocks[name]
                words = block["keywords"]
                writes = "a nested block ended by <code>End</code>"
                if block.get("fields"):
                    detail = ("The engine reads it through its own field table, so its "
                              "keywords carry types and offsets of their own.")
                    rows = "\n".join(
                        f'<tr><td class="fname"><code>{esc(f["name"])}</code></td>'
                        f'<td>{type_link(ref, f["type"], "")}</td></tr>'
                        for f in block["fields"])
                    table = (f'<table class="fields sub"><thead><tr><th>Keyword</th>'
                             f'<th>Type</th></tr></thead><tbody>{rows}'
                             f'</tbody></table>')
                elif words:
                    detail = ("The parser reads the block by hand; the keywords it "
                              "compares against are "
                              + ", ".join(f"<code>{esc(w)}</code>" for w in words) + ".")
                else:
                    detail = ("A nested block whose keywords the extractor could not "
                              "recover: the parser neither uses a field table nor "
                              "compares against plain strings.")
            elif cat == "Unidentified":
                writes = "unknown"
                detail = ("The parse function at this address has not been identified, so "
                          "neither the syntax nor the stored form is documented here.")
            else:
                _cat, writes, detail = TYPE_DOCS[name]
                writes, detail = prose(writes), prose(detail)
            enum = ref.enum_for_type(name)
            enum_link = (f'<p class="tokens">Tokens come from '
                         f'<a href="enums.html#{esc(slug(enum))}">{esc(enum)}</a>.</p>'
                         if enum else "")
            entries.append(f"""
<article class="type" id="{esc(slug(name))}">
  <h3><code>{esc(name)}</code><span class="count">{len(users)} field{'' if len(users) == 1 else 's'}</span></h3>
  <p class="writes"><span class="label">You write</span> {writes}</p>
  <p>{detail}</p>
  {enum_link}
  {f'<p class="uses"><span class="label">Used by</span> {examples}{more}</p>' if examples else ''}
  {table}
</article>""")
        if entries:
            anchor = "unidentified" if cat == "Unidentified" else slug(cat)
            sections.append(f'<section id="{anchor}"><h2>{esc(cat)} types</h2>'
                            + "\n".join(entries) + "</section>")
    intro = """<p class="lead">A field's type is its parse function: the code the engine
runs on the rest of the line. Everything below was read out of those functions - the
constant a real is scaled by, the range it is checked against, the array a token is
looked up in.</p>"""
    return page(ref, "Types", intro + "\n".join(sections),
                subtitle="What each field type accepts and how the engine stores it",
                active="types")


def enums_page(ref: Reference) -> str:
    sections = []
    for name, enum in sorted(ref.enums.items(), key=lambda kv: kv[0].lower()):
        members = enum["members"]
        values = enum.get("values")
        cells = "\n".join(
            f'<li><span class="idx">{values[i] if values else i}</span>'
            f'<code>{esc(m)}</code></li>' for i, m in enumerate(members))
        users = enum["users"]
        used = ", ".join(
            f'<a href="{d}/{esc(slug(owner))}.html#{esc(slug(fld))}">'
            f'<code>{esc(owner)}.{esc(fld)}</code></a>' for d, owner, fld in users[:4])
        more = f" and {len(users) - 4} more" if len(users) > 4 else ""
        cross = ""
        if enum["sage_ini"]:
            theirs = ref.sage_enums[enum["sage_ini"]][0]
            if len(theirs) == len(members):
                cross = (f'Agrees with <code>sage_ini</code>\'s '
                         f'<code>{esc(enum["sage_ini"])}</code>, member for member.')
            elif len(theirs) < len(members):
                cross = (f'<code>sage_ini</code>\'s <code>{esc(enum["sage_ini"])}</code> '
                         f'stops at {len(theirs)}; the engine list continues to '
                         f'{len(members)}.')
            else:
                cross = (f'<code>sage_ini</code>\'s <code>{esc(enum["sage_ini"])}</code> '
                         f'carries {len(theirs)} names against the engine\'s '
                         f'{len(members)}.')
        kind = ("token to value lookup" if enum["kind"] == "lookup"
                else "index list, first member is 0")
        if not enum["engine_named"] and not enum["sage_ini"]:
            cross += (" The binary does not name the list, so the name above is this "
                      "site's, taken from the field that reads it.")
        where = ", ".join(f"<code>{esc(va)}</code>" for va in enum["tables"])
        copies = (f" The same list is compiled in at {len(enum['tables'])} addresses."
                  if len(enum["tables"]) > 1 else "")
        sections.append(f"""
<article class="enum" id="{esc(slug(name))}">
  <h2>{esc(name)}<span class="count">{len(members)} members</span></h2>
  {f'<p>{esc(enum["doc"].splitlines()[0])}</p>' if enum["doc"] else ''}
  <p class="note">Read from the engine's own name array at {where} ({kind}).{copies}
  {cross}</p>
  {f'<p class="uses"><span class="label">Used by</span> {used}{more}</p>' if used else ''}
  <ol class="members">{cells}</ol>
</article>""")
    intro = """<p class="lead">These are the engine's token lists, read from the arrays
its parsers resolve names against, so a member's position here is the value the engine
stores. Where <code>sage_ini</code> models the same list, the two are compared.</p>"""
    return page(ref, "Enumerations", intro + "\n".join(sections),
                subtitle=f"{len(ref.enums)} token lists recovered from the binary",
                active="enums")


def index_page(ref: Reference) -> str:
    groups = "\n".join(
        f'<a class="group" href="modules.html#{slug(label)}"><b>{esc(label)}</b>'
        f'<span>{sum(1 for m in ref.modules if ref.category(m["name"]) == label)}</span></a>'
        for _s, label, _b in CATEGORIES
        if any(ref.category(m["name"]) == label for m in ref.modules))
    blocks = len(ref.ini_blocks)
    body = f"""
<p class="lead">Every module the ROTWK engine registers and every block type its INI
loader dispatches on, with the keywords each accepts, the type of every keyword and the
value it holds when you leave the line out - read out of the binary rather than
transcribed.</p>

<section>
<h2>Start here</h2>
<div class="tiles">
  <a class="tile" href="modules.html"><b>Modules</b>
    <span>All {len(ref.modules)} modules, grouped by the interface they attach to. Each
    page lists its fields with types and defaults, and an INI block you can paste with
    every keyword at its default.</span></a>
  <a class="tile" href="types.html"><b>Types</b>
    <span>What each type accepts and how the engine stores it - which reals are scaled
    into radians or logic frames, which strings are references into another INI file.</span></a>
  <a class="tile" href="blocks.html"><b>Blocks</b>
    <span>The {blocks} block types the INI loader dispatches on - <code>Object</code>,
    <code>Weapon</code>, <code>Locomotor</code>, <code>GameData</code> and the rest -
    read through field tables of their own.</span></a>
  <a class="tile" href="enums.html"><b>Enumerations</b>
    <span>The engine's token lists in engine order, read from the arrays its parsers
    resolve names against, cross-checked against <code>sage_ini</code>.</span></a>
  <a class="tile" href="check.html"><b>Check a block</b>
    <span>Paste INI and have every keyword checked against these tables: unknown
    keywords, values of the wrong shape, tokens that are not in the list, and lines
    that only repeat a default.</span></a>
</div>
</section>

<section>
<h2>Browse by group</h2>
<div class="groups">{groups}</div>
</section>

<section>
<h2>How to read a module page</h2>
<ul class="legend">
  <li><b>Field</b> - the INI keyword, spelled as the engine's parse table spells it.</li>
  <li><b>Type</b> - the parse function behind the keyword. Hover it for what it accepts,
      click it for the full entry. A second, smaller link appears when the field's tokens
      come from a fixed list, and a <span class="reflink">&rarr; Block</span> when
      <code>sage_ini</code> knows what the string has to name - the engine itself parses
      those as plain strings and says nothing about what they match.</li>
  <li><b>Default</b> - what the module's constructor writes before the block is read,
      so it is the value in force when the keyword is absent. A <span class="none">-</span>
      means constant tracking could not resolve the write, which in practice means an
      empty string or container rather than an unset field.</li>
</ul>
</section>

<section>
<h2>Where this comes from</h2>
<p>The engine registers each module with a factory that builds a 16-byte-stride table of
<code>{{keyword, parseFn, userData, offset}}</code>. Those tables give the field names,
their offsets and their parse functions. Defaults come from tracking constants through
each module's <code>ModuleData</code> constructor; enum members come from the name arrays
the parsers resolve tokens against; sub-block schemas come from the keywords their
parsers compare against.</p>
<p class="note">Read from <code>game.dat</code> build {ENGINE_BUILD}. Numbers are what
this build does - another build can differ. Nothing here is transcribed from another
reference, so where this site and another disagree, both are worth re-checking.</p>
</section>
"""
    return page(ref, "SAGE module reference", body,
                subtitle="Modules, fields, types and compiled-in defaults, "
                         "read out of the ROTWK engine", active="index")


def field_data(ref: Reference) -> str:
    """Every schema the checker validates against: modules, INI blocks, sub-blocks.

    One entry per field - the kind to check it against, the token list if it has one,
    and the default - so a pasted block can be told what the engine would make of it.
    """
    schemas: dict[str, dict[str, list]] = {}

    def add(name: str, fields: list[dict]) -> None:
        entry = schemas.setdefault(name, {})
        for f in fields:
            found = ref.target_of(name, f) if "default" in f else None
            entry.setdefault(f["name"], [field_kind(ref, f["type"]),
                                         ref.enum_for_field(f), f.get("default"),
                                         f["type"], found[0] if found else None])

    for module in ref.modules:
        add(module["name"], module["fields"])
    for name, blk in ref.ini_blocks.items():
        add(name, blk["fields"])
    for name, blk in ref.blocks.items():
        if blk.get("fields"):
            add(name, blk["fields"])
        else:
            entry = schemas.setdefault(name, {})
            for word in blk["keywords"]:
                entry.setdefault(word, ["text", None, None, "AsciiString"])
    data = {
        "schemas": schemas,
        "modules": sorted(m["name"] for m in ref.modules),
        "blocks": sorted(ref.ini_blocks),
    }
    return "window.WIKI_FIELDS = " + json.dumps(data, separators=(",", ":")) + ";\n"


def check_page(ref: Reference) -> str:
    body = """
<p class="lead">Paste a block - an <code>Object</code>, a <code>Weapon</code>, a
<code>Behavior = ...</code> module, anything with an <code>End</code> - and every
keyword in it is checked against what the engine's own parser accepts: is the keyword
one this block has, is the value the shape its type wants, is that token in the list.
Lines that only repeat a compiled-in default are called out too, since they do nothing.</p>
<p class="note">Nothing leaves the page: the schemas are already loaded, and the check
runs here.</p>
<div class="checkbar">
  <button id="checkrun" type="button">Check</button>
  <button id="checkclear" class="ghost" type="button">Clear</button>
  <span id="checksummary"></span>
</div>
<textarea id="checkinput" spellcheck="false" rows="14"
  placeholder="Behavior = ProductionUpdate ModuleTag_01
  MaxQueueEntries = 20
  GiveNoXP = Yes
End"></textarea>
<div id="checkout"></div>
"""
    return page(ref, "Check a block", body,
                subtitle="Validate a pasted INI block against the engine's field tables",
                active="check", extra="fields.js")


def search_data(ref: Reference) -> str:
    """The sidebar tree and the search index, as a script so `file://` works."""
    modules = [{"n": m["name"], "c": ref.category(m["name"]),
                "f": [f["name"] for f in m["fields"]]} for m in ref.modules]
    blocks = [{"n": name, "f": [f["name"] for f in blk["fields"]]}
              for name, blk in sorted(ref.ini_blocks.items(), key=lambda kv: kv[0].lower())]
    types = [[t, ref.type_category(t)]
             for t in sorted(ref.field_types) if not t.startswith("0x")]
    data = {
        "modules": modules,
        "blocks": blocks,
        "groups": [label for _s, label, _b in CATEGORIES],
        "types": types,
        "enums": sorted(ref.enums),
        "members": {name: enum["members"] for name, enum in sorted(ref.enums.items())},
        "pages": [["index.html", "Home"], ["modules.html", "All modules"],
                  ["blocks.html", "All blocks"], ["types.html", "Types"],
                  ["enums.html", "Enumerations"], ["check.html", "Check a block"]],
    }
    return "window.WIKI = " + json.dumps(data, separators=(",", ":")) + ";\n"


# The reference is one site over every module, with no faction anywhere in it, so it takes the
# default skin. `sage_utils.webtheme` holds the palette the aggregate pages and the replay
# browser read too - the three are published side by side and used to disagree about what a
# panel is.
CSS = webtheme.wiki_tokens(webtheme.STEEL) + """
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg); font-family: var(--sans);
  font-size: 15px; line-height: 1.6;
}
code, pre, kbd { font-family: var(--mono); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.skip { position: absolute; left: -9999px; }
.skip:focus { left: 8px; top: 8px; background: var(--bg); padding: 8px; z-index: 10; }

#sidebar {
  position: fixed; inset: 0 auto 0 0; width: 288px; border-right: 1px solid var(--line);
  background: var(--panel); overflow-y: auto; padding: 18px 0 40px; z-index: 5;
}
.brand {
  display: block; padding: 0 18px 14px; font-weight: 650; font-size: 17px;
  letter-spacing: .2px; color: var(--fg);
}
.brand span { display: block; font-weight: 400; font-size: 12px; color: var(--muted); }
.searchbox { position: relative; padding: 0 14px 10px; }
.searchbox input {
  width: 100%; padding: 8px 30px 8px 10px; border: 1px solid var(--line);
  border-radius: 7px; background: var(--bg); color: var(--fg); font-size: 13px;
}
.searchbox input:focus { outline: 2px solid var(--accent); border-color: transparent; }
.searchbox kbd {
  position: absolute; right: 22px; top: 8px; font-size: 11px; color: var(--muted);
  border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; background: var(--panel);
}
#results { padding: 0 8px 8px; }
#results .hit {
  display: block; padding: 6px 10px; border-radius: 6px; font-size: 13px; color: var(--fg);
}
#results a.hit:hover, #results .hit.on, #results .group summary:hover {
  background: var(--accent-soft); text-decoration: none;
}
#results .hit b { font-weight: 600; }
#results .hit span { color: var(--muted); font-size: 11.5px; display: block; }
#results .group { padding: 0; }
#results .group summary {
  padding: 6px 10px 6px 22px; border-radius: 6px; cursor: pointer; list-style: none;
  position: relative;
}
#results .group summary::-webkit-details-marker { display: none; }
#results .group summary::before {
  content: "+"; position: absolute; left: 9px; top: 6px; color: var(--muted);
  font-family: var(--mono);
}
#results .group[open] summary::before { content: "-"; }
#results .group a.sub {
  display: block; padding: 3px 10px 3px 26px; font-size: 12.5px; color: var(--fg);
}
#results .group a.sub:hover { background: var(--accent-soft); text-decoration: none; }
#results .empty { padding: 8px 12px; color: var(--muted); font-size: 13px; }
#nav .group > summary {
  cursor: pointer; padding: 5px 18px; font-size: 12px; text-transform: uppercase;
  letter-spacing: .6px; color: var(--muted); list-style: none;
}
#nav .group > summary::-webkit-details-marker { display: none; }
#nav .group > summary::before { content: "> "; }
#nav .group[open] > summary::before { content: "v "; }
#nav a {
  display: block; padding: 3px 18px 3px 30px; font-size: 13.5px; color: var(--fg);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
#nav a:hover { background: var(--accent-soft); text-decoration: none; }
#nav a.on { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
#nav .pages { padding: 4px 0 10px; border-bottom: 1px solid var(--line); margin-bottom: 8px; }
#nav .pages a { padding-left: 18px; font-weight: 500; }

#menu { display: none; }
main {
  margin-left: 288px; padding: 26px 34px 80px; max-width: 1080px;
}
.pagehead { border-bottom: 1px solid var(--line); margin-bottom: 22px; padding-bottom: 12px; }
h1 { font-size: 26px; margin: 0; letter-spacing: -.2px; }
.sub { color: var(--muted); margin: 6px 0 0; font-size: 14px; }
h2 { font-size: 19px; margin: 34px 0 10px; }
h3 { font-size: 15px; margin: 0 0 6px; }
.lead { font-size: 15.5px; max-width: 70ch; }
.note { color: var(--muted); font-size: 13.5px; max-width: 80ch; }
footer {
  margin-top: 54px; padding-top: 14px; border-top: 1px solid var(--line);
  color: var(--muted); font-size: 12.5px;
}

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.tile {
  border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; color: var(--fg);
}
.tile:hover { border-color: var(--accent); text-decoration: none; }
.tile b { display: block; margin-bottom: 4px; }
.tile span { color: var(--muted); font-size: 13px; }
.groups { display: flex; flex-wrap: wrap; gap: 8px; }
.group {
  border: 1px solid var(--line); border-radius: 20px; padding: 5px 14px; font-size: 13px;
  color: var(--fg);
}
.group:hover { border-color: var(--accent); text-decoration: none; }
.group span { color: var(--muted); margin-left: 6px; }
.legend li { margin-bottom: 5px; max-width: 80ch; }

dl.facts { display: flex; flex-wrap: wrap; gap: 8px 26px; margin: 0 0 18px; }
dl.facts div { display: flex; flex-direction: column; }
dl.facts dt { font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); }
dl.facts dd { margin: 0; font-size: 15px; }

table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
.fields th, .fields td {
  text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top;
}
.fields th {
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
  border-bottom: 1px solid var(--line); position: sticky; top: 0; background: var(--bg);
}
.sortable th { cursor: pointer; user-select: none; }
.sortable th:hover { color: var(--accent); }
.fields tbody tr:hover { background: var(--panel); }
.fields tbody tr:target { background: var(--accent-soft); }
.fields .num { text-align: right; white-space: nowrap; }
.fname code { font-weight: 600; }
.none { color: var(--muted); }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: 12.5px; }
pre { background: var(--code); padding: 14px; border-radius: 9px; overflow-x: auto; }
pre code { background: none; padding: 0; font-size: 12.5px; line-height: 1.55; }
.t {
  display: inline-block; padding: 1px 7px; border-radius: 5px; font-family: var(--mono);
  font-size: 12px; border: 1px solid transparent; background: var(--code); color: var(--fg);
}
.t:hover { border-color: var(--accent); text-decoration: none; }
.t[data-tip] { position: relative; }
.t[data-tip]:hover::after, .t[data-tip]:focus-visible::after {
  content: attr(data-tip); position: absolute; left: 0; top: calc(100% + 6px); z-index: 20;
  width: max-content; max-width: 360px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--panel); color: var(--fg);
  font-family: var(--sans); font-size: 12.5px; line-height: 1.45; font-weight: 400;
  white-space: normal; box-shadow: 0 6px 20px rgba(0, 0, 0, .28); pointer-events: none;
}
td:last-child .t[data-tip]:hover::after { left: auto; right: 0; }
/* A field's type reads by hue, and the hue means the same thing on every page, so these are
   not the skin's to set - only its ground is. The light column these had is gone with the
   light page: keeping it would have painted #1d6fb8 scalars onto a gunmetal ground for any
   reader whose OS asks for light. */
.t-scalar { color: #74b6f0; } .t-text { color: #77d3a1; } .t-enumeration { color: #c39bec; }
.t-flag { color: #e0a458; } .t-reference { color: #ef8fb8; } .t-sub { color: #aab; }
.t-unknown { color: var(--muted); border-style: dashed; border-color: var(--line); }
.enumref { font-size: 11.5px; margin-left: 6px; }
.reflink {
  font-size: 11.5px; margin-left: 6px; color: var(--muted); position: relative;
  border-bottom: 1px dotted var(--line);
}
a.reflink:hover { color: var(--accent); text-decoration: none; }
.reflink[data-tip]:hover::after {
  content: attr(data-tip); position: absolute; left: 0; top: calc(100% + 6px); z-index: 20;
  width: max-content; max-width: 340px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--panel); color: var(--fg);
  font-family: var(--sans); font-size: 12.5px; line-height: 1.45; white-space: normal;
  box-shadow: 0 6px 20px rgba(0, 0, 0, .28); pointer-events: none;
}
/* the column is sized here rather than by its content, so typing never reflows the table */
.fields td.val { position: relative; width: 210px; }
.fieldval {
  width: 100%; padding: 4px 8px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--bg); color: var(--fg); font-family: var(--mono); font-size: 12.5px;
}
.fieldval:focus { outline: 2px solid var(--accent); border-color: transparent; }
input.fieldval::placeholder { color: var(--muted); opacity: .55; }
.fieldval.bad { border-color: var(--bad); background: var(--bad-soft); }
select.fieldval { padding: 3px 6px; }
select.fieldval[multiple] { padding: 2px; height: 88px; overflow-y: auto; }
select.fieldval[multiple] option { padding: 1px 4px; border-radius: 3px; }
/* out of flow, so a message costs the row no height either */
.why {
  position: absolute; left: 0; top: calc(100% - 5px); z-index: 6; width: max-content;
  max-width: 260px; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--bad);
  background: var(--panel); color: var(--bad); font-size: 11.5px; line-height: 1.35;
  white-space: normal; box-shadow: 0 4px 14px rgba(0, 0, 0, .22);
}
.why:empty { display: none; }
/* The checker is a working surface, not a page of prose: the editor as wide as the window and
   the toolbar in reach. It used to force its own dark palette against a light page; the whole
   reference is that dark now, so only the layout is left here. */
:root[data-active="check"] main { max-width: none; }
:root[data-active="check"] .lead { font-size: 14px; }

.checkbar {
  display: flex; align-items: center; gap: 10px; margin: 16px 0 10px;
  position: sticky; top: 0; z-index: 4; padding: 10px 0; background: var(--bg);
}
.checkbar button {
  border: 1px solid transparent; border-radius: 10px; padding: 9px 20px; font-size: 13.5px;
  font-weight: 600; letter-spacing: .2px; cursor: pointer; font-family: var(--sans);
  color: var(--bg); background: linear-gradient(180deg, var(--accent-hi), var(--accent));
  box-shadow: 0 1px 0 rgba(255, 255, 255, .18) inset,
              0 8px 20px -10px var(--accent);
  transition: transform .12s ease, filter .12s ease, box-shadow .12s ease;
}
.checkbar button:hover { filter: brightness(1.06); transform: translateY(-1px); }
.checkbar button:active { transform: translateY(0); box-shadow: none; }
.checkbar button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.checkbar button.ghost {
  background: var(--panel); color: var(--fg); border-color: var(--line); box-shadow: none;
  font-weight: 500;
}
.checkbar button.ghost:hover { border-color: var(--accent); color: var(--accent); }
#checksummary {
  margin-left: auto; font-size: 12.5px; color: var(--muted); padding: 6px 14px;
  border: 1px solid var(--line); border-radius: 999px; background: var(--panel);
  white-space: nowrap;
}
#checksummary:empty { display: none; }
#checksummary.bad { color: var(--bad); border-color: currentColor; }
#checksummary.good { color: var(--ok); border-color: currentColor; }
#checkinput {
  width: 100%; height: min(62vh, 720px); padding: 18px 20px; border-radius: 14px;
  border: 1px solid var(--line); background: var(--code); color: var(--fg);
  font-family: var(--mono); font-size: 13px; line-height: 1.65; resize: vertical;
  tab-size: 2; box-shadow: 0 1px 0 rgba(255, 255, 255, .03) inset,
              0 24px 60px -40px rgba(0, 0, 0, .9);
}
#checkinput::placeholder { color: var(--muted); opacity: .6; }
#checkinput:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft), 0 24px 60px -40px rgba(0, 0, 0, .9);
}
.checktable {
  margin-top: 20px; font-family: var(--mono); font-size: 12.5px;
  border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
  background: var(--panel);
}
.checktable td {
  padding: 4px 12px; vertical-align: top; border-bottom: 1px solid transparent;
  border-left: 3px solid transparent;
}
.checktable .lineno {
  text-align: right; color: var(--muted); width: 1%; user-select: none; opacity: .7;
}
.checktable .linetext { white-space: pre-wrap; width: 55%; }
.checktable .linenote { color: var(--muted); font-family: var(--sans); font-size: 12px; }
.checktable tr.error td:first-child { border-left-color: var(--bad); }
.checktable tr.error { background: var(--bad-soft); }
.checktable tr.error .linetext, .checktable tr.error .linenote { color: var(--bad); }
.checktable tr.warn td:first-child { border-left-color: var(--part); }
.checktable tr.warn .linenote { color: var(--part); }
.checktable tr.block td:first-child { border-left-color: var(--accent); }
.checktable tr.block .linetext { font-weight: 600; }
.checktable tr.ok .linenote { color: var(--muted); }
.checktable tr:hover { background: var(--accent-soft); }
.checktable tr:hover { background: var(--panel); }
details.defaults { margin-top: 14px; }
details.defaults summary { cursor: pointer; font-size: 13.5px; }
details.defaults pre { margin-top: 8px; }
.inirow { display: flex; align-items: flex-start; gap: 10px; margin-top: 26px; }
.inirow .skeleton { flex: 1; min-width: 0; margin-top: 0; }
.copyini {
  border: 1px solid var(--line); border-radius: 7px; background: var(--panel); color: var(--fg);
  padding: 5px 12px; font-size: 12.5px; cursor: pointer; font-family: var(--sans);
}
.copyini:hover { border-color: var(--accent); color: var(--accent); }
#ini .set { color: var(--accent); font-weight: 600; }
.skeleton { margin-top: 26px; }
.skeleton summary { cursor: pointer; font-size: 14px; }
.count { color: var(--muted); font-weight: 400; font-size: 12.5px; margin-left: 8px; }
ul.modgrid { list-style: none; padding: 0; margin: 0; columns: 3; column-gap: 22px; }
ul.modgrid li { break-inside: avoid; font-size: 13.5px; padding: 1px 0; }
ul.modgrid .count { font-size: 11px; }

article.type, article.enum {
  border-top: 1px solid var(--line); padding: 16px 0;
}
article.type h3 code { background: none; padding: 0; font-size: 14.5px; }
.writes .label, .uses .label, .tokens .label {
  font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
  margin-right: 6px;
}
article.type p, article.enum p { margin: 4px 0; max-width: 80ch; font-size: 13.5px; }
ol.members { list-style: none; padding: 0; margin: 10px 0 0; }
ol.members li { display: flex; gap: 8px; align-items: baseline; font-size: 12.5px; }
ol.members .idx { color: var(--muted); font-family: var(--mono); font-size: 11px; min-width: 26px; text-align: right; }
ol.members code { background: none; padding: 0; }

@media (max-width: 900px) {
  #sidebar { transform: translateX(-100%); transition: transform .18s ease; }
  body.nav-open #sidebar { transform: none; }
  main { margin-left: 0; padding: 18px 16px 60px; }
  #menu {
    display: block; position: fixed; right: 12px; top: 12px; z-index: 6;
    background: var(--panel); color: var(--fg); border: 1px solid var(--line);
    border-radius: 7px; padding: 7px 12px; font-size: 13px; cursor: pointer;
  }
  ul.modgrid { columns: 1; }
}
"""

JS = r"""
(function () {
  var body = document.body, root = document.documentElement;
  var base = root.getAttribute('data-base') || '';
  var active = root.getAttribute('data-active') || '';
  var W = window.WIKI;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // sidebar: the fixed pages, then one collapsible section per module group
  var nav = document.getElementById('nav');
  var pages = el('div', 'pages');
  // there are 200 block types; listing them all would bury the modules, so the sidebar
  // carries the one link and lets `blocks.html` do the listing
  var onBlock = (W.blocks || []).some(function (b) { return b.n === active; });
  W.pages.forEach(function (p) {
    var here = active === p[0].replace('.html', '') || (onBlock && p[0] === 'blocks.html');
    var a = el('a', here ? 'on' : '', p[1]);
    a.href = base + p[0];
    pages.appendChild(a);
  });
  nav.appendChild(pages);

  function navGroup(label, entries, dir) {
    if (!entries.length) return;
    var d = el('details', 'group');
    d.appendChild(el('summary', null, label + ' (' + entries.length + ')'));
    entries.forEach(function (e) {
      var a = el('a', e.n === active ? 'on' : '', e.n);
      a.href = base + dir + '/' + e.n.replace(/[^A-Za-z0-9_-]/g, '-') + '.html';
      d.appendChild(a);
      if (e.n === active) d.open = true;
    });
    nav.appendChild(d);
  }

  var byGroup = {};
  W.modules.forEach(function (m) { (byGroup[m.c] = byGroup[m.c] || []).push(m); });
  W.groups.forEach(function (g) { navGroup(g, byGroup[g] || [], 'm'); });

  // search over module names, field names, types and enums
  var q = document.getElementById('q'), out = document.getElementById('results');
  function slug(s) { return s.replace(/[^A-Za-z0-9_-]/g, '-'); }
  function modHref(mod, field) {
    return 'm/' + slug(mod) + '.html' + (field ? '#' + slug(field) : '');
  }
  var index = [], byField = {};
  function own(entry, dir, name) {
    // a keyword that several blocks declare is one result carrying all of them
    entry.f.forEach(function (f) {
      if (!byField[f]) { byField[f] = { k: f, t: 'field', mods: [] }; index.push(byField[f]); }
      byField[f].mods.push({ n: name, d: dir });
    });
  }
  W.modules.forEach(function (m) {
    index.push({ k: m.n, t: 'module', h: modHref(m.n), s: m.c });
    own(m, 'm', m.n);
  });
  (W.blocks || []).forEach(function (b) {
    index.push({ k: b.n, t: 'block', h: 'b/' + slug(b.n) + '.html', s: 'INI block' });
    own(b, 'b', b.n);
  });
  Object.keys(byField).forEach(function (f) {
    var e = byField[f];
    e.s = e.mods.length === 1 ? e.mods[0].n : e.mods.length + ' blocks';
    if (e.mods.length === 1) e.h = e.mods[0].d + '/' + slug(e.mods[0].n) + '.html#' + slug(f);
  });
  W.types.forEach(function (t) {
    index.push({
      k: t[0], t: 'type', s: t[1].toLowerCase(),
      h: 'types.html#' + t[0].replace(/[^A-Za-z0-9_-]/g, '-')
    });
  });
  W.enums.forEach(function (e) {
    index.push({ k: e, t: 'enum', s: 'enumeration', h: 'enums.html#' + e.replace(/[^A-Za-z0-9_-]/g, '-') });
  });

  var rank = { module: 0, block: 1, type: 2, enum: 3, field: 4 };
  function search(term) {
    var needle = term.toLowerCase(), hits = [];
    for (var i = 0; i < index.length && hits.length < 400; i++) {
      var pos = index[i].k.toLowerCase().indexOf(needle);
      if (pos >= 0) hits.push({ e: index[i], p: pos });
    }
    hits.sort(function (a, b) {
      return (a.p - b.p) || (rank[a.e.t] - rank[b.e.t]) ||
             (a.e.k.length - b.e.k.length) || a.e.k.localeCompare(b.e.k);
    });
    return hits.slice(0, 40);
  }

  var cursor = -1;
  function render(hits) {
    out.innerHTML = '';
    cursor = -1;
    if (!hits.length) {
      out.appendChild(el('div', 'empty', 'No match'));
    }
    hits.forEach(function (h) {
      var e = h.e;
      if (e.t === 'field' && !e.h) {
        var d = el('details', 'hit group');
        var sum = el('summary');
        sum.appendChild(el('b', null, e.k));
        sum.appendChild(el('span', null, 'field - ' + e.s));
        d.appendChild(sum);
        e.mods.forEach(function (mod) {
          var link = el('a', 'sub', mod.n);
          link.href = base + mod.d + '/' + slug(mod.n) + '.html#' + slug(e.k);
          d.appendChild(link);
        });
        out.appendChild(d);
        return;
      }
      var a = el('a', 'hit');
      a.href = base + e.h;
      a.appendChild(el('b', null, e.k));
      a.appendChild(el('span', null, e.t + ' - ' + e.s));
      out.appendChild(a);
    });
    out.hidden = false;
    nav.hidden = true;
  }
  function clear() { out.hidden = true; out.innerHTML = ''; nav.hidden = false; cursor = -1; }

  q.addEventListener('input', function () {
    var v = q.value.trim();
    if (v.length < 2) { clear(); return; }
    render(search(v));
  });
  q.addEventListener('keydown', function (e) {
    var hits = out.querySelectorAll('.hit');
    if (e.key === 'Escape') { q.value = ''; clear(); q.blur(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!hits.length) return;
      e.preventDefault();
      if (cursor >= 0) hits[cursor].classList.remove('on');
      cursor = (cursor + (e.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length;
      hits[cursor].classList.add('on');
      hits[cursor].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && cursor >= 0) {
      var hit = hits[cursor];
      if (hit.tagName === 'DETAILS') hit.open = !hit.open; else hit.click();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); }
  });

  // typed-in values: checked against the field's type, then written into the INI block
  var iniCode = document.getElementById('ini');
  var fieldTable = document.querySelector('table.fields[data-module]');
  var NUM = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;
  var RANGES = { int8: [-128, 127], uint8: [0, 255], uint16: [0, 65535] };
  var PARTS = { coord3: ['X', 'Y', 'Z'], rgb: ['R', 'G', 'B'], rgba: ['R', 'G', 'B', 'A'] };

  function memberOf(list, token) {
    var t = token.replace(/^[+-]/, '').toUpperCase();
    if (t === 'ALL' || t === 'NONE') return true;
    for (var i = 0; i < list.length; i++) if (list[i].toUpperCase() === t) return true;
    return false;
  }

  function complain(value, kind, enumName) {
    var toks = value.split(/\s+/), list = enumName ? (W.members || {})[enumName] : null;
    if (value.charAt(0) === '#') return '';   // an INI macro, resolved at load time
    switch (kind) {
      case 'bool':
        return /^(yes|no)$/i.test(value) ? '' : 'expected Yes or No';
      case 'int': case 'int8': case 'uint8': case 'uint16':
        if (!/^[+-]?\d+$/.test(value)) return 'expected a whole number';
        var lim = RANGES[kind], n = parseInt(value, 10);
        if (lim && (n < lim[0] || n > lim[1])) return 'expected ' + lim[0] + ' to ' + lim[1];
        return '';
      case 'real': case 'positive': case 'nonneg': case 'nonpos':
        if (!NUM.test(value)) return 'expected a number';
        var f = parseFloat(value);
        if (kind === 'positive' && !(f > 0)) return 'expected a number above 0';
        if (kind === 'nonneg' && f < 0) return 'expected 0 or more';
        if (kind === 'nonpos' && f > 0) return 'expected 0 or less';
        return '';
      case 'intrange':
        if (toks.length !== 2 || !/^[+-]?\d+$/.test(toks[0]) || !/^[+-]?\d+$/.test(toks[1]))
          return 'expected two whole numbers';
        return '';
      case 'coord3': case 'rgb': case 'rgba':
        var keys = PARTS[kind];
        for (var j = 0; j < toks.length; j++) {
          var m = /^([A-Za-z]+):(.*)$/.exec(toks[j]);
          if (!m || keys.indexOf(m[1].toUpperCase()) < 0 || !NUM.test(m[2]))
            return 'expected ' + keys.map(function (k) { return k + ':<number>'; }).join(' ');
        }
        return '';
      case 'enum':
        if (toks.length !== 1) return 'expected a single token';
        return (list && !memberOf(list, toks[0])) ? toks[0] + ' is not in ' + enumName : '';
      case 'flags':
        if (!list) return '';
        for (var k = 0; k < toks.length; k++)
          if (!memberOf(list, toks[k])) return toks[k] + ' is not in ' + enumName;
        return '';
      case 'pair':
        if (toks.length !== 2) return 'expected exactly two tokens';
        if (list) for (var q = 0; q < 2; q++)
          if (!memberOf(list, toks[q])) return toks[q] + ' is not in ' + enumName;
        return '';
      case 'keyed':
        if (toks.length < 2) return 'expected a moment, then a name';
        return (list && !memberOf(list, toks[0])) ? toks[0] + ' is not in ' + enumName : '';
      case 'module':
        var known = window.WIKI_FIELDS;
        if (known && known.modules.indexOf(toks[0]) < 0)
          return toks[0] + ' is not a module the engine registers';
        return toks.length < 2 ? 'expected a module, then a tag' : '';
      default:
        return '';
    }
  }

  function fillPickers() {
    var picks = document.querySelectorAll('select.fieldval[data-members]');
    for (var i = 0; i < picks.length; i++) {
      var pick = picks[i], list = (W.members || {})[pick.getAttribute('data-members')] || [];
      for (var j = 0; j < list.length; j++) {
        var opt = document.createElement('option');
        opt.textContent = list[j];
        pick.appendChild(opt);
      }
    }
  }

  function controlValue(control) {
    if (control.tagName !== 'SELECT') return control.value.trim();
    if (!control.multiple) return control.value.trim();
    var sign = control.getAttribute('data-sign') || '', picked = [];
    for (var i = 0; i < control.options.length; i++)
      if (control.options[i].selected) picked.push(sign + control.options[i].value);
    return picked.join(' ');
  }

  function rebuildIni() {
    var inputs = fieldTable.querySelectorAll('.fieldval');
    var written = [], width = 0, i;
    for (i = 0; i < inputs.length; i++) {
      var inp = inputs[i], typed = controlValue(inp);
      var value = typed || inp.getAttribute('data-default') || '';
      // a keyword with neither a typed value nor a default is not a line you could paste
      if (!value) continue;
      var name = inp.getAttribute('data-field');
      written.push({ name: name, value: value, typed: !!typed });
      if (name.length > width) width = name.length;
    }
    iniCode.textContent = '';
    var head = document.createElement('span');
    head.textContent = fieldTable.getAttribute('data-module') + ' ModuleTag_01\n';
    iniCode.appendChild(head);
    written.forEach(function (line) {
      var pad = line.name;
      while (pad.length < width) pad += ' ';
      var span = document.createElement('span');
      if (line.typed) span.className = 'set';
      span.textContent = '  ' + pad + ' = ' + line.value + '\n';
      iniCode.appendChild(span);
    });
    iniCode.appendChild(document.createTextNode('End'));
  }

  if (fieldTable && iniCode) {
    fillPickers();
    fieldTable.addEventListener('change', onValue);
    fieldTable.addEventListener('input', onValue);
  }

  function onValue(e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains('fieldval')) return;
      var value = controlValue(inp);
      var why = value ? complain(value, inp.getAttribute('data-kind'),
                                 inp.getAttribute('data-enum')) : '';
      inp.classList.toggle('bad', !!why);
      inp.setAttribute('aria-invalid', why ? 'true' : 'false');
      if (why) inp.title = why; else inp.removeAttribute('title');
      var note = inp.parentNode.querySelector('.why');
      if (note) note.textContent = why;
      rebuildIni();
  }

  // paste a block, check every keyword in it against the engine's field tables
  var checkInput = document.getElementById('checkinput');

  function stripComment(line) {
    var out = '', quoted = false;
    for (var i = 0; i < line.length; i++) {
      var c = line.charAt(i);
      if (c === '"') quoted = !quoted;
      if (!quoted && (c === ';' || (c === '/' && line.charAt(i + 1) === '/'))) break;
      out += c;
    }
    return out;
  }

  function schemaFor(name) {
    var F = window.WIKI_FIELDS;
    return (F && F.schemas[name]) || null;
  }

  function isModule(name) {
    var F = window.WIKI_FIELDS;
    return !!(F && F.modules.indexOf(name) >= 0);
  }

  function isBlockType(name) {
    var F = window.WIKI_FIELDS;
    return !!(F && F.blocks.indexOf(name) >= 0);
  }

  function checkText(text) {
    var lines = text.split(/\r?\n/), stack = [], report = [], seen = [];
    var totals = { keywords: 0, errors: 0, redundant: 0, blocks: 0 };

    function top() { return stack.length ? stack[stack.length - 1] : null; }

    for (var n = 0; n < lines.length; n++) {
      var raw = lines[n], line = stripComment(raw).trim();
      var row = { no: n + 1, text: raw, state: 'plain', note: '' };
      if (!line) { report.push(row); continue; }

      if (/^end$/i.test(line)) {
        if (!stack.length) {
          row.state = 'error';
          row.note = 'End without a block to close';
          totals.errors++;
        } else {
          var done = stack.pop();
          row.state = 'block';
          row.note = 'closes ' + (done.name || 'the block');
        }
        report.push(row);
        continue;
      }

      var eq = line.indexOf('='), key, value;
      if (eq >= 0) {
        key = line.slice(0, eq).trim();
        value = line.slice(eq + 1).trim();
      } else {
        var words = line.split(/\s+/);
        key = words[0];
        value = words.slice(1).join(' ');   // `Object GondorSoldier` names the block
      }
      var first = value.split(/\s+/)[0] || '';
      var scope = top();
      var schema = scope && scope.name ? schemaFor(scope.name) : null;
      var spec = schema ? schema[key] : null;

      // what the keyword does comes from the schema it sits in: a `Module` keyword
      // attaches the module its value names, a keyword typed as a block opens that
      // block, and a keyword with no value that names a block is a header
      var opened = null, unknownModule = false;
      if (spec && spec[0] === 'module') {
        opened = schemaFor(first) ? first : null;
        unknownModule = !opened;
      } else if (spec && schemaFor(spec[3])) {
        opened = spec[3];
      } else if (!spec && isModule(first)) {
        opened = first;
      } else if (schemaFor(key) && (!spec || !value)) {
        opened = key;
      } else if (eq < 0 && scope) {
        // a keyword on a line of its own opens something; without a schema for it the
        // honest thing is to skip its contents rather than judge them
        unknownModule = true;
      }

      if (opened) {
        stack.push({ name: opened, line: n + 1, set: {} });
        seen.push(stack[stack.length - 1]);
        totals.blocks++;
        if (spec) scope.set[key] = true;
        row.state = 'block';
        row.note = 'opens ' + opened;
        report.push(row);
        continue;
      }
      if (unknownModule) {
        stack.push({ name: null, line: n + 1, set: {} });
        row.state = 'warn';
        row.note = (spec && spec[0] === 'module' ? first : key) +
                   ' opens a block with no schema here, so its contents are not checked';
        report.push(row);
        continue;
      }

      if (!scope) {
        row.state = 'warn';
        row.note = 'outside any block';
        report.push(row);
        continue;
      }
      if (!scope.name) { report.push(row); continue; }

      totals.keywords++;
      if (!spec) {
        row.state = 'error';
        row.note = key + ' is not a keyword of ' + scope.name;
        totals.errors++;
        report.push(row);
        continue;
      }
      scope.set[key] = true;
      var why = value ? complain(value, spec[0], spec[1]) : '';
      if (why) {
        row.state = 'error';
        row.note = why;
        totals.errors++;
      } else if (spec[2] !== null && spec[2] !== undefined && value === String(spec[2])) {
        row.state = 'warn';
        row.note = 'same as the default, so the line does nothing';
        totals.redundant++;
      } else {
        row.state = 'ok';
        row.note = spec[4] ? 'names a ' + spec[4] : spec[3];
      }
      report.push(row);
    }

    stack.forEach(function (open) {
      totals.errors++;
      report.push({ no: lines.length, text: '', state: 'error',
                    note: (open.name || 'block') + ' opened on line ' + open.line +
                          ' is never closed' });
    });
    return { report: report, totals: totals, seen: seen };
  }

  function renderCheck(result) {
    var out = document.getElementById('checkout');
    out.innerHTML = '';
    var table = el('table', 'checktable');
    var body = document.createElement('tbody');
    result.report.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.className = row.state;
      var no = el('td', 'lineno', String(row.no));
      var text = el('td', 'linetext', row.text);
      var note = el('td', 'linenote', row.note);
      tr.appendChild(no);
      tr.appendChild(text);
      tr.appendChild(note);
      body.appendChild(tr);
    });
    table.appendChild(body);
    out.appendChild(table);

    result.seen.forEach(function (scope) {
      var schema = schemaFor(scope.name);
      if (!schema) return;
      var missing = Object.keys(schema).filter(function (k) {
        return !scope.set[k] && schema[k][2] !== null && schema[k][2] !== undefined;
      });
      if (!missing.length) return;
      var d = el('details', 'defaults');
      d.appendChild(el('summary', null,
        scope.name + ': ' + missing.length + ' keyword' + (missing.length === 1 ? '' : 's') +
        ' you did not set, and what they default to'));
      var pre = document.createElement('pre');
      var width = 0;
      missing.forEach(function (k) { if (k.length > width) width = k.length; });
      pre.textContent = missing.map(function (k) {
        var pad = k;
        while (pad.length < width) pad += ' ';
        return '  ' + pad + ' = ' + schema[k][2];
      }).join('\n');
      d.appendChild(pre);
      out.appendChild(d);
    });

    var t = result.totals;
    var summary = document.getElementById('checksummary');
    summary.className = t.errors ? 'bad' : 'good';
    summary.textContent = t.keywords + ' keyword' + (t.keywords === 1 ? '' : 's') +
      ' in ' + t.blocks + ' block' + (t.blocks === 1 ? '' : 's') + ' - ' +
      t.errors + ' problem' + (t.errors === 1 ? '' : 's') + ', ' +
      t.redundant + ' line' + (t.redundant === 1 ? '' : 's') + ' equal to the default';
  }

  if (checkInput) {
    var run = function () { renderCheck(checkText(checkInput.value)); };
    document.getElementById('checkrun').addEventListener('click', run);
    document.getElementById('checkclear').addEventListener('click', function () {
      checkInput.value = '';
      document.getElementById('checkout').innerHTML = '';
      document.getElementById('checksummary').textContent = '';
    });
    var pending = null;
    checkInput.addEventListener('input', function () {
      clearTimeout(pending);
      pending = setTimeout(run, 350);
    });
  }

  var copyBtn = document.querySelector('.copyini');
  if (copyBtn && iniCode) {
    copyBtn.addEventListener('click', function () {
      var text = iniCode.textContent;
      function done() {
        var was = copyBtn.textContent;
        copyBtn.textContent = 'Copied';
        setTimeout(function () { copyBtn.textContent = was; }, 1400);
      }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); } catch (err) { /* nothing to do */ }
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    });
  }

  // column sort
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var dir = {};
    table.querySelectorAll('th').forEach(function (th, col) {
      th.addEventListener('click', function () {
        var rows = Array.prototype.slice.call(table.tBodies[0].rows);
        dir[col] = !dir[col];
        rows.sort(function (a, b) {
          var x = a.cells[col].textContent.trim(), y = b.cells[col].textContent.trim();
          var nx = parseFloat(x), ny = parseFloat(y);
          var c = (!isNaN(nx) && !isNaN(ny) && x !== '' && y !== '')
                  ? nx - ny : x.localeCompare(y);
          return dir[col] ? c : -c;
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
  });

  var menu = document.getElementById('menu');
  if (menu) menu.addEventListener('click', function () { body.classList.toggle('nav-open'); });
})();
"""


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build(out_dir: str) -> int:
    """Write the whole site, returning the number of pages written."""
    with open(MODULE_JSON, encoding="utf-8") as fh:
        modules = json.load(fh)
    with open(TYPE_JSON, encoding="utf-8") as fh:
        types = json.load(fh)
    ref = Reference(modules, types)

    for stale in ("m", "b"):
        if os.path.isdir(os.path.join(out_dir, stale)):
            shutil.rmtree(os.path.join(out_dir, stale))
    write(os.path.join(out_dir, "assets", "wiki.css"), CSS.lstrip())
    write(os.path.join(out_dir, "assets", "wiki.js"), JS.lstrip())
    write(os.path.join(out_dir, "assets", "data.js"), search_data(ref))
    write(os.path.join(out_dir, "index.html"), index_page(ref))
    write(os.path.join(out_dir, "modules.html"), modules_page(ref))
    write(os.path.join(out_dir, "blocks.html"), blocks_page(ref))
    write(os.path.join(out_dir, "assets", "fields.js"), field_data(ref))
    write(os.path.join(out_dir, "check.html"), check_page(ref))
    write(os.path.join(out_dir, "types.html"), types_page(ref))
    write(os.path.join(out_dir, "enums.html"), enums_page(ref))
    for module in ref.modules:
        write(os.path.join(out_dir, "m", slug(module["name"]) + ".html"),
              module_page(ref, module))
    for name, block in ref.ini_blocks.items():
        write(os.path.join(out_dir, "b", slug(name) + ".html"),
              block_page(ref, name, block))
    return len(ref.modules) + len(ref.ini_blocks) + 6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="output directory (default: build/wiki)")
    args = ap.parse_args()
    pages = build(args.out)
    print("wrote %d pages to %s" % (pages, os.path.normpath(args.out)))


if __name__ == "__main__":
    main()
