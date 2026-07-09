"""Batch round-trip validator for `.apt`/`.const` pairs, shared by the `sage-apt
check` CLI and the corpus acceptance gate.

Each pair is decompiled, recompiled, and re-decompiled in a temporary directory so
the inputs are never touched. A pair is `ok` when the second XML matches the first,
`unstable` when they differ, and `error` when a conversion raises.
"""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sage_apt.aptfile import AptError, apt_to_xml, xml_to_apt

OK = "ok"
UNSTABLE = "unstable"
ERROR = "error"


@dataclass
class CheckResult:
    """Outcome of round-tripping one `.apt` pair."""

    path: Path
    status: str
    message: str = ""

    def as_dict(self) -> dict:
        return {"path": str(self.path), "status": self.status, "message": self.message}


def collect_apts(paths) -> list[Path]:
    """Resolve the CLI arguments to a de-duplicated, ordered list of `.apt` paths.

    A directory contributes every `*.apt` inside it that has a sibling `.const`
    (loose `.apt` files whose `.const` lives inside a `.big` are skipped). A file
    argument is normalised to its `.apt` sibling and always included, so a genuinely
    missing input surfaces as an `error` result rather than vanishing.
    """
    apts: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            apts.append(path)

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for apt in sorted(p.glob("*.apt")):
                if apt.with_suffix(".const").exists():
                    add(apt)
        else:
            add(p.with_suffix(".apt"))
    return apts


def _round_trip(apt_path: Path) -> str:
    """Decompile, recompile, and re-decompile `apt_path` in a temp dir; return
    `OK` if the two XMLs match, else `UNSTABLE`. Raises `AptError` on failure."""
    const_path = apt_path.with_suffix(".const")
    with tempfile.TemporaryDirectory(prefix="sage_apt_check_") as tmp:
        work_apt = Path(tmp) / apt_path.name
        if apt_path.exists():
            shutil.copy(apt_path, work_apt)
        if const_path.exists():
            shutil.copy(const_path, work_apt.with_suffix(".const"))

        xml_path = apt_to_xml(work_apt)
        first = xml_path.read_bytes()
        xml_to_apt(xml_path)
        apt_to_xml(work_apt)
        second = xml_path.read_bytes()

    return OK if first == second else UNSTABLE


def check_one(apt_path) -> CheckResult:
    """Round-trip a single `.apt` pair, classifying the outcome."""
    apt_path = Path(apt_path)
    try:
        return CheckResult(apt_path, _round_trip(apt_path))
    except AptError as exc:
        return CheckResult(apt_path, ERROR, exc.reason)
    except Exception as exc:  # noqa: BLE001 - any parse/pack failure is an ERROR result
        return CheckResult(apt_path, ERROR, str(exc))


def check_paths(paths) -> list[CheckResult]:
    """Round-trip every `.apt` pair reachable from `paths` (files or directories)."""
    return [check_one(apt) for apt in collect_apts(paths)]


def all_ok(results) -> bool:
    """True when every result is `OK` (an empty result set counts as not-ok)."""
    return bool(results) and all(r.status == OK for r in results)
