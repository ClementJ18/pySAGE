"""Audit every field still typed `String`/`Opaque` and propose a dedicated type.

The migration away from blanket `String`/`Opaque` annotations is driven by a review
table: this tool builds it. It inventories every `String`/`Opaque` field declaration in
the model (via the source AST, so each row carries its `file:line` and exact current
annotation), samples the real values each field takes across the given corpus roots, and
makes a best-guess at the dedicated type the data supports - with a confidence flag so the
confident rows can be skim-approved and the rest scrutinized.

Nothing is changed: the output is a Markdown table (and a CSV alongside) for a human to
correct the `proposed` column before any annotation is rewritten.

Usage: python tools/string_field_audit.py <root> [<root> ...] [--out PATH] [--samples N]
  <root>        corpus root(s) to sample values from (omit to inventory only, no guesses)
  --out PATH    output path stem (default: string_field_audit); writes .md and .csv
  --samples N   distinct sample values to show per field (default: 8)
"""

import ast
import csv
import enum as _enum
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sage_ini.loader import load_game  # noqa: E402
from sage_ini.model import enums as e  # noqa: E402
from sage_ini.model.objects import REGISTRY, IniObject  # noqa: E402

MODEL_DIR = ROOT / "sage_ini" / "model"

# Tools that consume the typed model. A field one of them reads is high-priority to type: its
# value is actually used downstream, so a precise type pays off immediately.
CONSUMER_PKGS = ("sage_ui", "sage_wiki", "sage_lint")


def consumer_sources() -> dict[str, str]:
    """The concatenated Python source of each consumer package, for field-reference scanning."""
    sources: dict[str, str] = {}
    for pkg in CONSUMER_PKGS:
        pkg_dir = ROOT / pkg
        if pkg_dir.is_dir():
            sources[pkg] = "\n".join(
                path.read_text(encoding="utf-8") for path in pkg_dir.rglob("*.py")
            )
    return sources


def consumers_using(field: str, sources: dict[str, str]) -> list[str]:
    """Which consumer packages reference `field` - as an attribute access (`obj.Field`) or a
    quoted key (`"Field"`). Bare-name matches are skipped to avoid false hits on common words."""
    pattern = re.compile(rf"""(\.{re.escape(field)}\b|["']{re.escape(field)}["'])""")
    return [pkg for pkg, src in sources.items() if pattern.search(src)]


# Asset-file extensions seen in INI fields; a value carrying one is a Filename, not free text.
ASSET_EXTS = (".w3d", ".tga", ".dds", ".bmp", ".wav", ".mp3", ".bik", ".ini", ".lua", ".fnt")


def annotation_mentions_target(node: ast.expr) -> str | None:
    """If an annotation expression names `Untyped`/`Opaque` (bare, `t.`-qualified, or inside a
    `List[...]`/`Nullable[...]` subscript), return a short label for it, else None. The clean,
    intentional `String` is *not* tracked - it is a reviewed choice, not backlog."""
    found: set[str] = set()
    container = ""

    def visit(n: ast.expr) -> None:
        nonlocal container
        if isinstance(n, ast.Name) and n.id in ("Untyped", "Opaque"):
            found.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in ("Untyped", "Opaque"):
            found.add(n.attr)
        elif isinstance(n, ast.Subscript):
            base = n.value
            name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            if name in ("List", "Nullable", "FlagList"):
                container = name
            for child in ast.iter_child_nodes(n.slice):
                if isinstance(child, ast.expr):
                    visit(child)
            visit(n.slice if isinstance(n.slice, ast.expr) else base)

    visit(node)
    if not found:
        return None
    base = "/".join(sorted(found))
    return f"{container}[{base}]" if container else base


def inventory() -> list[dict]:
    """Every `String`/`Opaque` field declaration in the model, from the source AST."""
    rows: list[dict] = []
    for path in sorted(MODEL_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    label = annotation_mentions_target(stmt.annotation)
                    if label is not None:
                        rows.append(
                            {
                                "file": path.name,
                                "line": stmt.lineno,
                                "class": cls.name,
                                "field": stmt.target.id,
                                "current": label,
                            }
                        )
    return rows


def walk_objects(game):
    """Every loaded `IniObject` instance: the registered tables plus their nested sub-objects,
    modules, and typed marker groups (where most module fields actually live)."""
    seen: set[int] = set()
    stack = [obj for table in game.tables.values() for obj in table.values()]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        yield obj
        stack.extend(obj._modules)
        for items in obj._nested_data.values():
            stack.extend(items)
        for items in obj._marker_grouped.values():
            stack.extend(i for i in items if isinstance(i, IniObject))


def sample_values(games, rows) -> dict[tuple[str, str], Counter]:
    """For each `(class, field)` row, the distinct raw values it takes across the corpora,
    attributed to the class that declares the field (matched by `isinstance`)."""
    by_field: dict[str, list[tuple]] = {}
    for row in rows:
        cls = REGISTRY.get(row["class"])
        if cls is not None:  # KeyedRecord rows aren't in the registry; left unsampled
            by_field.setdefault(row["field"], []).append((cls, (row["class"], row["field"])))

    counters: dict[tuple[str, str], Counter] = {}
    for game in games:
        for obj in walk_objects(game):
            for field, candidates in by_field.items():
                if field not in obj._fields:
                    continue
                raw = obj._fields[field]
                values = raw if isinstance(raw, list) else [raw]
                for cls, ident in candidates:
                    if isinstance(obj, cls):
                        counters.setdefault(ident, Counter()).update(values)
    return counters


# Real (strict) enums only: a FakeEnum exposes `__members__` as a property, not a member map.
_ENUMS = [obj for obj in vars(e).values() if isinstance(obj, _enum.EnumType) and obj.__members__]


def _is_number(token: str) -> bool:
    body = token.strip().rstrip("%").rstrip("fF")
    try:
        float(body)
        return True
    except ValueError:
        return False


def _is_int(token: str) -> bool:
    body = token.strip().rstrip("%").rstrip("fF")
    return body.lstrip("-").isdigit()


def _looks_like_asset(token: str) -> bool:
    low = token.lower()
    return low.endswith(ASSET_EXTS) or "/" in token or "\\" in token


def _looks_like_label(token: str) -> bool:
    head, sep, _ = token.partition(":")
    return bool(sep) and head.isupper() and head.isidentifier()


def guess_type(field: str, tokens: list[str], games) -> tuple[str, str, str]:
    """Best-guess `(proposed_type, confidence, note)` for a field from its sampled values.
    Confidence is high/low; an empty sample yields a name-only guess flagged low."""
    fl = field.lower()
    if not tokens:
        # No corpus evidence: fall back to the field name alone, always low confidence.
        if fl.endswith(("bone", "bonename")):
            return ("Bone", "low", "name-based, no samples")
        return ("?", "low", "no corpus samples")

    n = len(tokens)
    flat = [t for tok in tokens for t in tok.split()] or tokens
    # Whether sampled *values* are mostly several tokens - a compound/list field, not a scalar.
    # Such a field can't be a bare scalar type, so any scalar guess drops to low confidence.
    multi = sum(1 for tok in tokens if len(tok.split()) > 1) / n > 0.4
    scalar_conf = "low" if multi else "high"
    multi_note = " (multi-token: list/compound?)" if multi else ""

    def frac(pred) -> float:
        return sum(1 for t in flat if pred(t)) / len(flat)

    # All-numeric: a misfiled number, or a list of them when the values are multi-token.
    if all(_is_number(t) for t in flat):
        kind = "Int" if all(_is_int(t) for t in flat) else "Float"
        if multi:
            return (f"List[{kind}]", "low", f"{len(flat)} numeric tokens, multi-token")
        return (kind, "high", f"{len(flat)} numeric tokens")
    if all(t.strip().lower() in ("yes", "no") for t in flat):
        return ("Bool", "high", "Yes/No")

    # Asset paths / filenames: map to the specific marker type by the extensions seen.
    if frac(_looks_like_asset) > 0.6:
        exts = {t.lower().rsplit(".", 1)[-1] for t in flat if "." in t}
        base = {
            frozenset({"tga", "dds", "bmp"}): "TextureFile",
            frozenset({"w3d"}): "ModelFile",
            frozenset({"wav", "mp3"}): "AudioFile",
            frozenset({"map"}): "MapFile",
        }
        kind = "Filename"
        for keys, name in base.items():
            if exts & keys:
                kind = name
                break
        kind = f"List[{kind}]" if multi else kind
        return (kind, scalar_conf, "asset extensions / paths" + multi_note)

    # Localized string-table labels.
    if frac(_looks_like_label) > 0.6:
        return ("Label", scalar_conf, "UPPER:colon labels" + multi_note)

    # Strict enum membership: every token names a member of the same enum.
    for enum in _ENUMS:
        members = set(enum.__members__)
        if all(t in members for t in flat):
            kind = f"List[{enum.__name__}]" if multi else enum.__name__
            conf = "high" if (n > 1 and not multi) else "low"
            return (kind, conf, f"all in {enum.__name__}" + multi_note)

    # Cross-reference: tokens resolve as names in a single game table.
    table_hits: Counter = Counter()
    for game in games:
        for t in flat:
            for key, table in game.tables.items():
                if t in table:
                    table_hits[key] += 1
    if table_hits and games:
        key, hits = table_hits.most_common(1)[0]
        if hits / len(flat) > 0.6:
            return (f'Reference("{key}")', "low", f"{hits}/{len(flat)} resolve in {key}")

    # Name-shaped opaque tokens.
    if fl.endswith(("bone", "bonename")):
        return ("Bone", "low", "bone-named")
    if "mesh" in fl or "subobject" in fl:
        return ("SubObject", "low", "mesh/subobject-named")

    return ("String", "low", "free text (unresolved)")


def write_outputs(rows, counters, games, out_stem: Path, samples: int) -> None:
    sources = consumer_sources()
    enriched = []
    for row in rows:
        ident = (row["class"], row["field"])
        counter = counters.get(ident, Counter())
        tokens = [tok for tok, _ in counter.most_common()]
        shown = "; ".join(f"{tok!r}×{counter[tok]}" for tok in tokens[:samples])
        proposed, confidence, note = guess_type(row["field"], tokens, games)
        consumers = consumers_using(row["field"], sources)
        enriched.append(
            {
                **row,
                "occurrences": sum(counter.values()),
                "distinct": len(counter),
                "samples": shown,
                "proposed": proposed,
                "confidence": confidence,
                "note": note,
                "consumers": ",".join(consumers),
                "priority": "PRIORITY" if consumers else "",
            }
        )

    # Consumer-read fields first (a downstream tool uses the value), then confident, then most
    # used. These are the highest-leverage to type next.
    enriched.sort(
        key=lambda r: (
            not r["consumers"],
            r["file"],
            -(r["confidence"] == "high"),
            -r["occurrences"],
        )
    )

    prio = sum(1 for r in enriched if r["consumers"])
    md = out_stem.with_suffix(".md")
    with md.open("w", encoding="utf-8") as fh:
        fh.write("# Untyped / Opaque field audit\n\n")
        fh.write(
            f"{len(enriched)} field declarations still typed Untyped/Opaque (the backlog; "
            "fields intentionally kept as clean `String` are excluded). "
            f"{prio} are read by {', '.join(CONSUMER_PKGS)} (**PRIORITY**, listed first). "
            "Correct the **proposed** column.\n\n"
        )
        fh.write(
            "| pri | consumers | file:line | class | field | current | proposed | conf "
            "| samples | note |\n"
        )
        fh.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for r in enriched:
            loc = f"{r['file']}:{r['line']}"
            fh.write(
                f"| {r['priority']} | {r['consumers']} | {loc} | {r['class']} | {r['field']} "
                f"| {r['current']} | {r['proposed']} | {r['confidence']} | {r['samples']} "
                f"| {r['note']} |\n"
            )

    csv_path = out_stem.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "priority",
                "consumers",
                "file",
                "line",
                "class",
                "field",
                "current",
                "proposed",
                "confidence",
                "occurrences",
                "distinct",
                "samples",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(enriched)

    high = sum(1 for r in enriched if r["confidence"] == "high")
    print(
        f"{len(enriched)} rows ({high} high-confidence, {prio} consumer-priority); "
        f"wrote {md.name} and {csv_path.name}"
    )


def main() -> int:
    args = sys.argv[1:]
    out_stem = ROOT / "string_field_audit"
    samples = 8
    if "--out" in args:
        i = args.index("--out")
        out_stem = Path(args[i + 1])
        del args[i : i + 2]
    if "--samples" in args:
        i = args.index("--samples")
        samples = int(args[i + 1])
        del args[i : i + 2]

    rows = inventory()
    games = []
    for root in args:
        loaded = load_game(Path(root))
        loaded.game.validate()  # drive lazy conversion so references populate tables
        games.append(loaded.game)
    if not args:
        print("no corpus roots given: inventory only, no value samples or guesses")

    counters = sample_values(games, rows) if games else {}
    write_outputs(rows, counters, games, out_stem, samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
