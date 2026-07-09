"""Typed-coverage report for module headers across the corpora.

For every `Behavior`/`ClientBehavior`/`Body`/`Draw`/... header, report how many
distinct module types resolve to a typed class versus stay generic, and list
the most common still-generic types - the input to typed-coverage decisions.

Usage: python tools/module_coverage.py <root> [<root> ...]
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sage_ini.model.definitions  # noqa: E402,F401  (register classes)
from sage_ini.model.objects import REGISTRY  # noqa: E402
from sage_ini.parser.io import iter_ini_files, read_text  # noqa: E402
from sage_ini.parser.lexer import tokenize  # noqa: E402

HEADER = re.compile(r"^(Behavior|ClientBehavior|ClientUpdate|Body|Draw)\s*=\s*(\w+)")


def main() -> int:
    counts: Counter = Counter()
    by_category: dict[str, Counter] = {}

    for root in (Path(p) for p in sys.argv[1:]):
        for path in iter_ini_files(root):
            for line in tokenize(read_text(path), file=str(path)):
                match = HEADER.match(line.content)
                if match:
                    category, module = match.group(1), match.group(2)
                    counts[module] += 1
                    by_category.setdefault(category, Counter())[module] += 1

    typed = {m: n for m, n in counts.items() if m in REGISTRY}
    generic = {m: n for m, n in counts.items() if m not in REGISTRY}

    print(f"distinct module types: {len(counts)}")
    print(f"  typed:   {len(typed):4} types, {sum(typed.values()):7} occurrences")
    print(f"  generic: {len(generic):4} types, {sum(generic.values()):7} occurrences")

    for category, modules in sorted(by_category.items()):
        gen = {m: n for m, n in modules.items() if m not in REGISTRY}
        rate = 100 * (len(modules) - len(gen)) / len(modules) if modules else 0.0
        print(f"\n{category}: {len(modules) - len(gen)}/{len(modules)} types typed ({rate:.1f}%)")
        for module, occ in sorted(gen.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    generic  {occ:6}  {module}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
