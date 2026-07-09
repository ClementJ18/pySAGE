"""Audit reference-typing coverage: every field that is *not* yet typed as a cross-reference
but whose real values resolve as names in a Game table - i.e. a reference the schema does not
yet declare as one.

The dangling-reference rule only judges fields the model types as references (a `Reference`
alias, or a definition class used as an annotation). A field left as `String`/`Opaque`/
`Untyped`/`List[str]` whose values nonetheless name objects, upgrades, weapons, sciences, ...
is an invisible reference: a dangling one there is caught by nothing. This tool finds those.

Like `string_field_audit`, it changes nothing: it inventories the candidate fields (with their
`file:line` and current annotation from the source AST), samples the real values each takes
across the corpus, and for each proposes the `Reference(table)` the data supports - with a
resolution fraction and a confidence flag, and the target table grouped as gameplay vs asset
(art/audio names routinely live outside the data set, so an asset match is typed but should
stay out of the rule's flagging). A human corrects the `proposed` column before any retype.

Usage: python tools/reference_audit.py <root> [<root> ...] [--out PATH] [--samples N]
                                       [--min-frac F] [--gameplay-only]
"""

from __future__ import annotations

import argparse
import ast
import csv
import enum as _enum
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sage_ini.loader import load_game  # noqa: E402
from sage_ini.model import enums as _e  # noqa: E402
from sage_ini.model.objects import IniObject, resolve_annotation  # noqa: E402
from sage_ini.model.types import KeyedRecord, Reference  # noqa: E402
from sage_ini.walk import walk_objects  # noqa: E402

MODEL_DIR = ROOT / "sage_ini" / "model"

# Tables whose names are art/audio/UI assets. A field of one of these is a real reference and
# worth typing, but the names are routinely defined outside the gameplay data set, so the
# dangling-reference rule excludes them (see `sage_lint.rules.references._ASSET_TABLES`). We
# carry the same split here so the report can be read gameplay-first.
ASSET_TABLES = frozenset(
    {
        "audioevents",
        "dialogevents",
        "musictracks",
        "multisounds",
        "fxlists",
        "mappedimages",
        "cursors",
        "particlesystems",
        "evaevents",
        "videos",
        "ambientstreams",
        "livingworldsounds",
    }
)

# Real (strict) enums: a field already typed as one whose tokens happen to match a table's
# names (DEFAULT/Low/High/...) is an enum, not a reference - flag those matches as low.
_ENUMS = tuple(o for o in vars(_e).values() if isinstance(o, _enum.EnumType) and o.__members__)

# Tables that exist but are never cross-referenced by name: config/LOD singletons whose member
# blocks are named after enum tokens (Low/Medium/High), so a field's enum value coincides with a
# block name. Excluding them stops the audit proposing a reference where the value is an enum.
NON_REFERENCE_TABLES = frozenset({"staticgamelods", "dynamicgamelods"})


def is_reference(conv) -> bool:
    """Whether `conv` already resolves a cross-reference: a `Reference` alias (soft, passes a
    dangling name through), a definition class used as an annotation (strict, raises on a
    dangling name), or a container/record holding one of those."""
    if isinstance(conv, Reference):
        return True
    if isinstance(conv, type) and issubclass(conv, IniObject) and getattr(conv, "key", None):
        return True
    for attr in ("element", "inner", "value_type", "value"):
        el = getattr(conv, attr, None)
        if el is not None:
            try:
                if is_reference(resolve_annotation(el)):
                    return True
            except KeyError:
                pass
    # container converters that hold several element types (tuples, unions): a reference in
    # any slot already covers the field (e.g. `Tuple[Object, Int]`, `Union[Object, FactionSide]`).
    for attr in ("element_types", "types"):
        for el in getattr(conv, attr, None) or ():
            try:
                if is_reference(resolve_annotation(el)):
                    return True
            except KeyError:
                pass
    if isinstance(conv, type) and issubclass(conv, KeyedRecord):
        return any(is_reference(resolve_annotation(a)) for a in conv._keyspec.values())
    return False


def converter_label(conv) -> str:
    """A short label for the current converter, e.g. `Untyped`, `Opaque`, `List`."""
    return conv.__name__ if isinstance(conv, type) else type(conv).__name__


def is_enum_converter(conv) -> bool:
    """A strict enum, or a FakeEnum/open enum defined in the enums module: a field typed as one
    whose tokens happen to match a table's names is an enum, not a reference."""
    if isinstance(conv, type) and issubclass(conv, _ENUMS):
        return True
    mod = getattr(type(conv) if not isinstance(conv, type) else conv, "__module__", "")
    return mod.endswith("model.enums")


def source_index() -> dict[tuple[str, str], tuple[str, int, str]]:
    """`(class, field) -> (file, line, annotation-source)` for every annotated field in the
    model, so each candidate row can carry an actionable `file:line` and its current text."""
    index: dict[tuple[str, str], tuple[str, int, str]] = {}
    for path in sorted(MODEL_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    src = ast.get_source_segment(text, stmt.annotation) or ""
                    index[(cls.name, stmt.target.id)] = (path.name, stmt.lineno, src)
    return index


def sample(games) -> tuple[dict, dict]:
    """`((class, field) -> Counter of raw tokens)` for every non-reference field reachable in
    the corpora, plus `((class, field) -> converter label)`. Only alphabetic, colon-free
    single tokens are kept (a reference is one bareword; coordinates and labels are not)."""
    tokens: dict[tuple[str, str], Counter] = defaultdict(Counter)
    labels: dict[tuple[str, str], str] = {}
    enumish: set[tuple[str, str]] = set()
    for game in games:
        for obj in walk_objects(game):
            fspec = type(obj)._fieldspec
            for key, raw in obj.fields.items():
                if key not in fspec:
                    continue
                try:
                    conv = resolve_annotation(fspec[key])
                except KeyError:
                    continue
                if is_reference(conv):
                    continue
                ident = (type(obj).__name__, key)
                labels[ident] = converter_label(conv)
                if is_enum_converter(conv):
                    enumish.add(ident)
                raw_list = raw if isinstance(raw, list) else [raw]
                for item in raw_list:
                    if not isinstance(item, str):
                        continue
                    for tok in item.split():
                        if tok and tok[0].isalpha() and ":" not in tok:
                            tokens[ident][tok] += 1
    return tokens, labels, enumish


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path, help="corpus root(s) to sample values from")
    ap.add_argument("--out", default="reference_audit", help="output stem (.md and .csv)")
    ap.add_argument("--samples", type=int, default=6, help="sample values shown per field")
    ap.add_argument("--min-frac", type=float, default=0.5, help="min resolution fraction to list")
    ap.add_argument("--gameplay-only", action="store_true", help="drop asset-table matches")
    args = ap.parse_args()

    games = [load_game(root).game for root in args.roots]
    names = {
        k: {n.lower() for n in v}
        for g in games
        for k, v in g.tables.items()
        if v and k not in NON_REFERENCE_TABLES
    }

    tokens, labels, enumish = sample(games)
    src = source_index()

    rows = []
    for ident, ctr in tokens.items():
        distinct = list(ctr)
        if len(distinct) < 2:
            continue  # a single value is too thin to judge a whole field on
        low = [d.lower() for d in distinct]
        best_table, best_hits = None, 0
        for tname, tnames in names.items():
            hits = sum(1 for d in low if d in tnames)
            if hits > best_hits:
                best_table, best_hits = tname, hits
        frac = best_hits / len(low)
        if not best_table or frac < args.min_frac:
            continue
        if args.gameplay_only and best_table in ASSET_TABLES:
            continue
        cls, field = ident
        file, line, current = src.get(ident, ("?", 0, labels.get(ident, "?")))
        # Confidence: a clean full resolution on a gameplay table is high; an enum-typed field
        # or a partial/asset match is low (likeliest a coincidental token overlap or art name).
        high = frac >= 0.95 and best_table not in ASSET_TABLES and ident not in enumish
        rows.append(
            {
                "frac": frac,
                "class": cls,
                "field": field,
                "current": current,
                "proposed": f'Reference("{best_table}")',
                "table": best_table,
                "kind": "asset" if best_table in ASSET_TABLES else "gameplay",
                "confidence": "high" if high else "low",
                "n": len(distinct),
                "file": file,
                "line": line,
                "samples": " ".join(distinct[: args.samples]),
            }
        )

    rows.sort(key=lambda r: (r["kind"] != "gameplay", -r["frac"], r["class"], r["field"]))

    out_md = ROOT / f"{args.out}.md"
    out_csv = ROOT / f"{args.out}.csv"
    cols = [
        "confidence",
        "frac",
        "kind",
        "class",
        "field",
        "current",
        "proposed",
        "n",
        "file",
        "line",
        "samples",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: (f"{r[c]:.0%}" if c == "frac" else r[c]) for c in cols})

    gameplay = [r for r in rows if r["kind"] == "gameplay"]
    high = [r for r in gameplay if r["confidence"] == "high"]
    lines = [
        "# Reference-typing coverage audit",
        "",
        f"Fields not yet typed as references whose corpus values resolve as table names. "
        f"{len(rows)} candidates ({len(gameplay)} gameplay, {len(high)} high-confidence).",
        "",
        "| conf | % | kind | field | current | proposed | n | location | samples |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        loc = f"{r['file']}:{r['line']}"
        lines.append(
            f"| {r['confidence']} | {r['frac']:.0%} | {r['kind']} | "
            f"`{r['class']}.{r['field']}` | `{r['current']}` | `{r['proposed']}` | {r['n']} | "
            f"{loc} | {r['samples']} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} candidates ({len(gameplay)} gameplay, {len(high)} high-confidence)")
    print(f"wrote {out_md.name} and {out_csv.name}")


if __name__ == "__main__":
    main()
