"""Breakdown of unmodeled (`unknown-attribute`) fields by their parent block.

Builds the corpus, runs the `unknown-attribute` rule, and groups every still-untyped
field by the block that carries it - the schema-coverage to-do list, biggest gaps
first. Each block lists its distinct missing attributes with how often each appears,
so the highest-leverage fields to model next are the ones at the top.

Usage: python tools/missing_attributes.py <root> [<root> ...] [--top N]
  --top N   show only the N most common missing attributes per block (default: all)
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sage_ini.loader import load_game  # noqa: E402
from sage_lint.rules import UnknownAttributeRule  # noqa: E402
from sage_lint.rules.base import run_rules  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    top = None
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2

    by_block: dict[str, Counter] = {}
    for root in (Path(p) for p in args):
        loaded = load_game(root)
        for diag in run_rules(loaded.game, [UnknownAttributeRule]):
            block = diag.extra["type"]
            by_block.setdefault(block, Counter())[diag.extra["key"]] += 1

    unique_total = sum(len(attrs) for attrs in by_block.values())
    occ_total = sum(sum(attrs.values()) for attrs in by_block.values())
    print(
        f"{len(by_block)} blocks with missing attributes, "
        f"{unique_total} unique attributes, {occ_total} occurrences"
    )

    # Biggest coverage gaps first: most distinct missing attributes, then most occurrences.
    for block in sorted(by_block, key=lambda b: (-len(by_block[b]), -sum(by_block[b].values()))):
        attrs = by_block[block]
        print(f"\n{block}  ({len(attrs)} unique, {sum(attrs.values())} occurrences)")
        for attr, occ in attrs.most_common(top):
            print(f"    {occ:7}  {attr}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
