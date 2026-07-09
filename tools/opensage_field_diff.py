"""Compare the fields sage_ini parses against the OpenSAGE C# engine.

OpenSAGE (a GPLv3 C# reimplementation, vendored under `OpenSAGE-master/`) is the
format-semantics reference for sage_ini. Each of its parseable blocks is an
`IniParseTable<T>` whose entries are `{ "FieldName", (parser, x) => ... }`; this
tool extracts those field sets and lines them up against the typed sage_ini model
classes, so we can see which keys each side knows about.

Run from the repo root:  python tools/opensage_field_diff.py
Writes `opensage_field_diff.md` (per-object field diff) next to the repo root.
"""

from __future__ import annotations

import re
from pathlib import Path

import sage_ini.model.game  # noqa: F401  (force the full model to register)
from sage_ini.model.objects import REGISTRY, IniObject, resolve_annotation

REPO = Path(__file__).resolve().parent.parent
OPENSAGE_SRC = REPO / "OpenSAGE-master" / "src"
REPORT = REPO / "opensage_field_diff.md"

# Sage class name -> OpenSAGE table name, for matches the normalizer can't make on
# its own (a sage name that collides with an unrelated OpenSAGE table, or a rename
# with no shared stem). Keep this small; most matches come from the normalizer.
MANUAL_ALIASES = {
    "Object": "ObjectDefinition",
    "ChildObject": "ObjectDefinition",
    "ObjectReskin": "ObjectDefinition",
}

SUFFIXES = ("", "ModuleData", "Template", "Definition", "Data", "Behavior")


# Two ways OpenSAGE spells a parse table: `new IniParseTable<T>{...}` (incl. inside a
# `.Concat(...)`), and the target-typed `IniParseTable<T> FieldParseTable = new(){...}`.
_TABLE = re.compile(r"new\s+IniParseTable<(\w+)>|IniParseTable<(\w+)>\s+\w+\s*=\s*new\s*\(\s*\)")
_ENTRY = re.compile(r'\{\s*"([^"]+)"\s*,\s*\(parser,\s*x\)\s*=>\s*(.*?)\}\s*,?', re.DOTALL)
_PARSEFN = re.compile(r"parser\.(Parse\w+)")
_TYPECALL = re.compile(r"(\w+)\.Parse\(parser")
# `= SomeBase.FieldParseTable.Concat(new IniParseTable<This>{...})` - the parse
# table is built by extending a base class's table.
_CONCAT_BASE = re.compile(r"(\w+)\.FieldParseTable\s*\.\s*Concat\s*\(\s*$")


def _table_body(text: str, start: int) -> str:
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace : i + 1]
    return text[brace:]


def _entry_kind(rhs: str) -> str:
    pf = _PARSEFN.search(rhs)
    if pf:
        return pf.group(1)
    tc = _TYPECALL.search(rhs)
    if tc:
        return tc.group(1) + ".Parse"
    return rhs.strip()[:40]


def extract_opensage() -> dict[str, dict[str, str]]:
    """Class name -> {field name: parse-kind}, with parse tables built by
    `Base.FieldParseTable.Concat(...)` resolved transitively so inherited keys
    are counted on the subclass too."""
    own: dict[str, dict[str, str]] = {}
    bases: dict[str, str] = {}
    for path in OPENSAGE_SRC.rglob("*.cs"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for m in _TABLE.finditer(text):
            cls = m.group(1) or m.group(2)
            fields = own.setdefault(cls, {})
            for e in _ENTRY.finditer(_table_body(text, m.end())):
                fields[e.group(1)] = _entry_kind(e.group(2))
            # Did this `new IniParseTable<cls>` extend a base table?
            cb = _CONCAT_BASE.search(text[: m.start()].rstrip())
            if cb and cb.group(1) != cls:
                bases[cls] = cb.group(1)

    def resolve(cls: str, seen: frozenset) -> dict[str, str]:
        merged: dict[str, str] = {}
        base = bases.get(cls)
        if base and base in own and base not in seen:
            merged.update(resolve(base, seen | {cls}))
        merged.update(own.get(cls, {}))
        return merged

    return {cls: resolve(cls, frozenset()) for cls in own}


def extract_sage() -> dict[str, dict]:
    # IniObject's own annotations are engine config (`key`, `header_arity`, the
    # `_fieldspec`/`_marker_*` caches), not INI keys; they merge into every
    # subclass's `_fieldspec`, so drop them.
    meta = set(IniObject.__annotations__)

    def conv_name(ann) -> str:
        try:
            conv = resolve_annotation(ann)
        except (KeyError, NameError, AttributeError, TypeError):
            return str(ann)
        cls = conv if isinstance(conv, type) else type(conv)
        return cls.__name__

    out: dict[str, dict] = {}
    for name, cls in REGISTRY.items():
        fields = {
            f: conv_name(a)
            for f, a in cls._fieldspec.items()
            if f not in meta and not f.startswith("_")
        }
        # Sub-blocks sage_ini routes through `nested_attributes`/`marker_groups`
        # are real INI keys it parses; OpenSAGE lists them in its parse table, so
        # count them here too (marked by how sage_ini handles them, not a type).
        # A nested group's INI keyword is either the group name (`Draw`) or any of
        # its member type names (`Nuggets` -> `DamageNugget`, `ProjectileNugget`...).
        for grp, allowed in cls._nested.items():
            fields.setdefault(grp, "<nested>")
            for entry in allowed:
                member = entry if isinstance(entry, str) else entry.__name__
                fields.setdefault(member, "<nested>")
        for _grp, spec in cls._marker_groups.items():
            for marker in spec.markers:
                fields.setdefault(marker, "<group>")
            for key in spec.keys:
                fields.setdefault(key, "<group>")
        out[name] = {"key": getattr(cls, "key", None), "fields": fields}
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def build_matches(sage: dict, opensage: dict) -> tuple[dict[str, str], list[str]]:
    """sage class -> opensage table, plus the list of sage classes with no match."""
    by_norm: dict[str, list[str]] = {}
    for name in opensage:
        by_norm.setdefault(_norm(name), []).append(name)

    matches: dict[str, str] = {}
    unmatched: list[str] = []
    for name in sage:
        if name in MANUAL_ALIASES and MANUAL_ALIASES[name] in opensage:
            matches[name] = MANUAL_ALIASES[name]
            continue
        if name in opensage:  # exact wins over suffixed
            matches[name] = name
            continue
        hit = None
        for suf in SUFFIXES:
            cands = by_norm.get(_norm(name + suf))
            if cands:
                hit = cands[0]
                break
        if hit:
            matches[name] = hit
        else:
            unmatched.append(name)
    return matches, unmatched


def field_diff(sage_fields: dict, os_fields: dict):
    """Return (common, sage_only, os_only, case_only). Field names compared
    case-insensitively, since SAGE INI keys are matched that way; a name present
    on both sides with a different casing is reported separately as noise."""
    s_lower = {f.lower(): f for f in sage_fields}
    o_lower = {f.lower(): f for f in os_fields}
    common, case_only = [], []
    for low in s_lower.keys() & o_lower.keys():
        if s_lower[low] == o_lower[low]:
            common.append(s_lower[low])
        else:
            case_only.append((s_lower[low], o_lower[low]))
    sage_only = [s_lower[low] for low in s_lower.keys() - o_lower.keys()]
    os_only = [o_lower[low] for low in o_lower.keys() - s_lower.keys()]
    return sorted(common), sorted(sage_only), sorted(os_only), sorted(case_only)


def main() -> None:
    sage = extract_sage()
    opensage = extract_opensage()
    matches, unmatched = build_matches(sage, opensage)
    matched_os = set(matches.values())

    rows = []
    for s_name in sorted(matches):
        os_name = matches[s_name]
        common, s_only, o_only, case_only = field_diff(sage[s_name]["fields"], opensage[os_name])
        rows.append((s_name, os_name, common, s_only, o_only, case_only))

    lines: list[str] = []
    w = lines.append
    w("# sage_ini ↔ OpenSAGE field-parsing diff")
    w("")
    w("Generated by `tools/opensage_field_diff.py`. Compares the INI keys each side")
    w("parses, per object. `sage-only` = parsed by sage_ini but absent from the")
    w("OpenSAGE parse table; `OpenSAGE-only` = the reverse (a key we don't model yet).")
    w("Field names are matched case-insensitively.")
    w("")
    w(f"- sage_ini classes: **{len(sage)}**")
    w(f"- OpenSAGE parse tables: **{len(opensage)}**")
    identical = sum(1 for r in rows if not (r[3] or r[4] or r[5]))
    w(f"- matched: **{len(matches)}**  |  sage classes unmatched: **{len(unmatched)}**")
    w(f"- matched objects whose field sets agree exactly: **{identical}**")
    w("")
    w("> Note: a few keywords show as *OpenSAGE-only* because OpenSAGE lists them as")
    w("> explicit parse-table entries while sage_ini handles them structurally rather")
    w("> than as declared fields - generic module slots on an object (`Behavior`,")
    w("> `Body`, `ClientUpdate`, `Locomotor`). These are parsed by both, not real gaps.")
    w("")

    # Summary table, sorted by total divergence.
    w("## Summary (matched objects, by divergence)")
    w("")
    w("| sage_ini | OpenSAGE | common | sage-only | OpenSAGE-only | case-only |")
    w("|---|---|---:|---:|---:|---:|")
    for s_name, os_name, common, s_only, o_only, case_only in sorted(
        rows, key=lambda r: -(len(r[3]) + len(r[4]))
    ):
        if not (s_only or o_only or case_only):
            continue
        w(
            f"| {s_name} | {os_name} | {len(common)} | "
            f"{len(s_only)} | {len(o_only)} | {len(case_only)} |"
        )
    w("")

    # Per-object detail.
    w("## Per-object detail")
    w("")
    for s_name, os_name, _common, s_only, o_only, case_only in sorted(rows):
        if not (s_only or o_only or case_only):
            continue
        w(f"### {s_name} → {os_name}")
        w("")
        if s_only:
            w(f"**sage-only ({len(s_only)})** - parsed by sage_ini, not by OpenSAGE:")
            w("")
            w("> " + ", ".join(s_only))
            w("")
        if o_only:
            w(f"**OpenSAGE-only ({len(o_only)})** - in OpenSAGE, not modeled by sage_ini:")
            w("")
            w("> " + ", ".join(o_only))
            w("")
        if case_only:
            w(f"**case mismatches ({len(case_only)})** - sage / OpenSAGE:")
            w("")
            w("> " + ", ".join(f"{a}/{b}" for a, b in case_only))
            w("")

    # Unmatched.
    w("## sage_ini classes with no OpenSAGE parse table")
    w("")
    w("These are either inline sub-blocks OpenSAGE parses within a parent (not their")
    w("own `IniParseTable`), abstract sage base classes, or genuine gaps.")
    w("")
    for name in sorted(unmatched):
        key = sage[name]["key"]
        tag = f" *(table: {key})*" if key else ""
        w(f"- `{name}` ({len(sage[name]['fields'])} fields){tag}")
    w("")

    os_unmatched = sorted(set(opensage) - matched_os)
    w(f"## OpenSAGE parse tables with no sage_ini class ({len(os_unmatched)})")
    w("")
    for name in os_unmatched:
        w(f"- `{name}` ({len(opensage[name])} fields)")
    w("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT}")
    print(f"  sage classes: {len(sage)}  OpenSAGE tables: {len(opensage)}")
    print(f"  matched: {len(matches)}  unmatched sage: {len(unmatched)}")


if __name__ == "__main__":
    main()
