"""Categorize root-file diagnostics for a corpus: structural vs environmental.

Structural codes (parser's job) must be zero; environmental codes
(unresolved/cyclic includes - missing data in this corpus pairing) are
reported separately.

Usage: categorize_roots.py <root> [<overlay> ...]
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sage_ini.parser.blockparser import parse_file  # noqa: E402,PLC0415
from sage_ini.stats import ini_root, root_files  # noqa: E402,PLC0415

STRUCTURAL = {"stray-end", "unclosed-block", "unclosed-script"}

root = Path(sys.argv[1])
layers = [ini_root(root)] + [ini_root(Path(p)) for p in sys.argv[2:]]

structural_files = []
env_only = 0
clean = 0
codes = Counter()

for path in root_files(root):
    result = parse_file(path, resolve_includes=True, include_layers=layers)
    if not result.diagnostics:
        clean += 1
        continue
    file_codes = [d.code for d in result.diagnostics]
    codes.update(file_codes)
    if any(c in STRUCTURAL for c in file_codes):
        structural_files.append((path, file_codes))
    else:
        env_only += 1

print(f"clean: {clean}, env-only: {env_only}, structural: {len(structural_files)}")
print(f"all codes: {dict(codes)}")
for path, file_codes in structural_files[:30]:
    print(f"  STRUCTURAL {path.name}: {Counter(file_codes)}")
