"""Acceptance gate over the Edain apt corpus: every `.apt`/`.const` pair under the
mod's `apt` and `apt_widescreen` folders must round-trip apt -> xml -> apt -> xml
with byte-identical XML. Runs through the same machinery as `sage-apt check`, so
the CLI and this gate cannot drift apart. Skipped when the corpus is absent."""

from pathlib import Path

import pytest

from sage_apt.check import OK, all_ok, check_paths

pytestmark = pytest.mark.full


def _edain_apt_dirs() -> list[Path]:
    """The mod's apt folders, derived from the `edain=` root in corpus_roots.txt
    (which points at `..._mod/data/ini`; the apt dirs are siblings of `data`)."""
    roots_file = Path(__file__).resolve().parent.parent / "corpus_roots.txt"
    if not roots_file.is_file():
        return []
    for line in roots_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        label, path = line.split("=", 1)
        if label.strip() == "edain":
            mod = Path(path.strip()).parents[1]
            return [d for d in (mod / "apt", mod / "apt_widescreen") if d.is_dir()]
    return []


def test_edain_apt_corpus_round_trips():
    apt_dirs = _edain_apt_dirs()
    if not apt_dirs:
        pytest.skip("Edain apt corpus not present")
    results = check_paths(apt_dirs)
    failures = [f"{r.path}: {r.status} {r.message}".rstrip() for r in results if r.status != OK]
    assert all_ok(results), "\n".join(failures) or "no .apt pairs found"
