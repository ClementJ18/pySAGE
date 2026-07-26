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

__all__ = ["build", "TYPE_DOCS", "CATEGORIES"]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
DOCS = os.path.join(HERE, os.pardir, "docs")
MODULE_JSON = os.path.join(DOCS, "module-reference.json")
TYPE_JSON = os.path.join(DOCS, "module-types.json")
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
}

# Token lists the binary does not name and `sage_ini` does not model, named here after
# what the module that reads them calls them.
ENUM_NAMES = {
    "0x00db0e7c": "StructureCollapsePhase",
    "0x00db0ed0": "RubbleRisePhase",
    "0x00db0f20": "StructureTopplePhase",
    "0x00d9e6bc": "LodLevel",
}


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
        self.type_tables: dict[str, str] = types["types"]
        self.engine_enums: dict[str, str] = types["enums"]
        self.sage_enums = self._sage_enums()
        self.enums = self._name_enums()
        self.field_types = self._field_types()

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
        users: dict[str, list[tuple[str, str]]] = {}
        from_type: dict[str, str] = {}
        for m in self.modules:
            for f in m["fields"]:
                if f.get("userdata"):
                    users.setdefault(f["userdata"], []).append((m["name"], f["name"]))
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
                        or users.get(va, [("", "Unnamed")])[0][1] + "Values")
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
            name = matched or (users.get(va, [("", "Unnamed")])[0][1] + "Values")
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

    def _field_types(self) -> dict[str, list[tuple[str, str]]]:
        """type name -> the fields that use it."""
        out: dict[str, list[tuple[str, str]]] = {}
        for m in self.modules:
            for f in m["fields"]:
                out.setdefault(f["type"], []).append((m["name"], f["name"]))
        return out

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
         subtitle: str = "", active: str = "") -> str:
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


def field_rows(ref: Reference, module: dict, base: str) -> str:
    rows = []
    for f in module["fields"]:
        enum = ref.enum_for_field(f)
        extra = ""
        if enum:
            extra = (f' <a class="enumref" href="{base}enums.html#{esc(slug(enum))}">'
                     f'{esc(enum)}</a>')
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


def ini_skeleton(ref: Reference, module: dict) -> str:
    """The module's block with every keyword at the value it holds when left out.

    A keyword whose default could not be recovered is left out rather than written
    blank, since a blank line is not something you could paste.
    """
    written = [f for f in module["fields"] if f["default"] is not None]
    width = max((len(f["name"]) for f in written), default=0)
    lines = [f'{module["name"]} ModuleTag_01']
    lines += [f'  {f["name"]:<{width}} = {f["default"]}' for f in written]
    lines.append("End")
    return esc("\n".join(lines))


def module_page(ref: Reference, module: dict) -> str:
    base = "../"
    mask = module.get("interface_mask") or ""
    facts = []
    if mask.startswith("0x") or mask.isdigit():
        facts.append(f'<div><dt>Interface mask</dt><dd><code>{esc(mask)}</code></dd></div>')
    unknown = [f for f in module["fields"] if f["type"].startswith("0x")]
    warn = ""
    if unknown:
        names = ", ".join(f'<code>{esc(f["name"])}</code>' for f in unknown)
        verb = "uses" if len(unknown) == 1 else "use"
        warn = (f'<p class="note">{len(unknown)} field'
                f'{"" if len(unknown) == 1 else "s"} on this module {verb} a parse '
                f'function that has not been identified, so the type column shows its '
                f'address: {names}.</p>')
    body = f"""
{f'<dl class="facts">{"".join(facts)}</dl>' if facts else ''}
{warn}
<table class="fields sortable" data-module="{esc(module["name"])}">
<thead><tr><th>Field</th><th>Type</th><th>Default</th><th>Value</th></tr></thead>
<tbody>
{field_rows(ref, module, base)}
</tbody>
</table>
<div class="inirow">
<details class="skeleton">
<summary>INI block, every keyword at its default</summary>
<p class="note">The engine writes these values before it reads the block, so a keyword
you leave out behaves exactly as if you had written the line below. Fill in the value
column above and the line follows. Keywords whose default could not be recovered are
left out until you give them a value. The leading keyword (<code>Behavior</code>,
<code>Draw</code>, <code>Body</code>, ...) depends on which interface you are
attaching.</p>
<pre><code id="ini">{ini_skeleton(ref, module)}</code></pre>
</details>
<button class="copyini" type="button">Copy INI</button>
</div>
"""
    return page(ref, module["name"], body, base=base, active=module["name"])


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
                f'<a href="m/{esc(slug(mod))}.html#{esc(slug(fld))}">'
                f'<code>{esc(mod)}.{esc(fld)}</code></a>' for mod, fld in users[:3])
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
            f'<a href="m/{esc(slug(mod))}.html#{esc(slug(fld))}">'
            f'<code>{esc(mod)}.{esc(fld)}</code></a>' for mod, fld in users[:4])
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
    body = f"""
<p class="lead">Every behaviour, update, draw and body module the ROTWK engine
registers, with the INI keywords it accepts, the type of each keyword, where it sits in
the module's data and the value it holds when you leave the line out.</p>

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
  <a class="tile" href="enums.html"><b>Enumerations</b>
    <span>The engine's token lists in engine order, read from the arrays its parsers
    resolve names against, cross-checked against <code>sage_ini</code>.</span></a>
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
      come from a fixed list.</li>
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


def search_data(ref: Reference) -> str:
    """The sidebar tree and the search index, as a script so `file://` works."""
    modules = [{"n": m["name"], "c": ref.category(m["name"]),
                "f": [f["name"] for f in m["fields"]]} for m in ref.modules]
    types = [[t, ref.type_category(t)]
             for t in sorted(ref.field_types) if not t.startswith("0x")]
    data = {
        "modules": modules,
        "groups": [label for _s, label, _b in CATEGORIES],
        "types": types,
        "enums": sorted(ref.enums),
        "members": {name: enum["members"] for name, enum in sorted(ref.enums.items())},
        "pages": [["index.html", "Home"], ["modules.html", "All modules"],
                  ["types.html", "Types"], ["enums.html", "Enumerations"]],
    }
    return "window.WIKI = " + json.dumps(data, separators=(",", ":")) + ";\n"


CSS = """
:root {
  --bg: #ffffff; --fg: #1c2024; --muted: #626b75; --line: #e3e7eb;
  --panel: #f7f8fa; --accent: #2f5bd0; --accent-soft: #e8eefc;
  --code: #f2f4f7; --warn: #9a5b00; --ok: #1c7c48; --part: #9a6a00;
  --bad: #c02b3a; --bad-soft: #fdf1f2;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171a; --fg: #e6e9ec; --muted: #98a2ad; --line: #262c33;
    --panel: #1a1e22; --accent: #7aa2f7; --accent-soft: #1d2839;
    --code: #1e2429; --warn: #e0a458; --ok: #6fcf97; --part: #e0b458;
    --bad: #f2777a; --bad-soft: #2a1c1f;
  }
}
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
.t-scalar { color: #1d6fb8; } .t-text { color: #1c7c48; } .t-enumeration { color: #8a4bbd; }
.t-flag { color: #b4691a; } .t-reference { color: #b53d7a; } .t-sub { color: #556; }
.t-unknown { color: var(--muted); border-style: dashed; border-color: var(--line); }
@media (prefers-color-scheme: dark) {
  .t-scalar { color: #74b6f0; } .t-text { color: #77d3a1; } .t-enumeration { color: #c39bec; }
  .t-flag { color: #e0a458; } .t-reference { color: #ef8fb8; } .t-sub { color: #aab; }
}
.enumref { font-size: 11.5px; margin-left: 6px; }
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
  W.pages.forEach(function (p) {
    var a = el('a', active === p[0].replace('.html', '') ? 'on' : '', p[1]);
    a.href = base + p[0];
    pages.appendChild(a);
  });
  nav.appendChild(pages);

  var byGroup = {};
  W.modules.forEach(function (m) { (byGroup[m.c] = byGroup[m.c] || []).push(m); });
  W.groups.forEach(function (g) {
    var mods = byGroup[g];
    if (!mods) return;
    var d = el('details', 'group');
    var s = el('summary', null, g + ' (' + mods.length + ')');
    d.appendChild(s);
    mods.forEach(function (m) {
      var a = el('a', m.n === active ? 'on' : '', m.n);
      a.href = base + 'm/' + m.n.replace(/[^A-Za-z0-9_-]/g, '-') + '.html';
      d.appendChild(a);
      if (m.n === active) d.open = true;
    });
    nav.appendChild(d);
  });

  // search over module names, field names, types and enums
  var q = document.getElementById('q'), out = document.getElementById('results');
  function slug(s) { return s.replace(/[^A-Za-z0-9_-]/g, '-'); }
  function modHref(mod, field) {
    return 'm/' + slug(mod) + '.html' + (field ? '#' + slug(field) : '');
  }
  var index = [], byField = {};
  W.modules.forEach(function (m) {
    index.push({ k: m.n, t: 'module', h: modHref(m.n), s: m.c });
    // a keyword that several modules declare is one result carrying all of them
    m.f.forEach(function (f) {
      if (!byField[f]) { byField[f] = { k: f, t: 'field', mods: [] }; index.push(byField[f]); }
      byField[f].mods.push(m.n);
    });
  });
  Object.keys(byField).forEach(function (f) {
    var e = byField[f];
    e.s = e.mods.length === 1 ? e.mods[0] : e.mods.length + ' modules';
    if (e.mods.length === 1) e.h = modHref(e.mods[0], f);
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

  var rank = { module: 0, type: 1, enum: 2, field: 3 };
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
          var link = el('a', 'sub', mod);
          link.href = base + modHref(mod, e.k);
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

    if os.path.isdir(os.path.join(out_dir, "m")):
        shutil.rmtree(os.path.join(out_dir, "m"))
    write(os.path.join(out_dir, "assets", "wiki.css"), CSS.lstrip())
    write(os.path.join(out_dir, "assets", "wiki.js"), JS.lstrip())
    write(os.path.join(out_dir, "assets", "data.js"), search_data(ref))
    write(os.path.join(out_dir, "index.html"), index_page(ref))
    write(os.path.join(out_dir, "modules.html"), modules_page(ref))
    write(os.path.join(out_dir, "types.html"), types_page(ref))
    write(os.path.join(out_dir, "enums.html"), enums_page(ref))
    for module in ref.modules:
        write(os.path.join(out_dir, "m", slug(module["name"]) + ".html"),
              module_page(ref, module))
    return len(ref.modules) + 5


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="output directory (default: build/wiki)")
    args = ap.parse_args()
    pages = build(args.out)
    print("wrote %d pages to %s" % (pages, os.path.normpath(args.out)))


if __name__ == "__main__":
    main()
