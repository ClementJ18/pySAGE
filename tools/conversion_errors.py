"""Breakdown of value conversion failures by `Block.field`.

The companion to `missing_attributes.py`: once a field is *typed*, a wrong converter
turns a real corpus value into a `conversion-error`. This builds the corpus and groups
those failures by the field that raised them, with a sample bad value each - the signal
that a freshly typed field needs a looser converter (e.g. `String` instead of `Float`).

Usage: python tools/conversion_errors.py <root> [<root> ...] [--filter Substr]
  --filter Substr   only show fields whose `Block.field` contains Substr
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sage_ini.loader import load_game  # noqa: E402
from sage_lint.linter import lint_game  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    substr = None
    if "--filter" in args:
        i = args.index("--filter")
        substr = args[i + 1]
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2

    counts: Counter = Counter()
    samples: dict[str, str] = {}
    for root in (Path(p) for p in args):
        for diag in lint_game(load_game(root)):
            if diag.code != "conversion-error":
                continue
            block = diag.extra.get("type", "?")
            field = diag.extra.get("field", "?")
            key = f"{block}.{field}"
            counts[key] += 1
            samples.setdefault(key, diag.extra.get("error", diag.message))

    rows = [(k, n) for k, n in counts.items() if substr is None or substr in k]
    print(f"{len(rows)} fields with conversion errors, {sum(n for _, n in rows)} occurrences")
    for key, occ in sorted(rows, key=lambda kv: -kv[1]):
        print(f"\n{occ:7}  {key}")
        print(f"         e.g. {samples[key]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
